import re
import json
import aiohttp
import asyncio
import datetime
import discord
from typing import Optional, Dict, List
from redbot.core import commands, checks

from .m01_utils import (
    MCQ, LETTERS, letter_index, sanitize_options, normalize_theme,
    pick_fallback, cutoff_ts_at_hour_utc, TEST_USER_ID, canonical_question
)

# ---------------------------
# BoozyQuiz: batch-based flow
# ---------------------------

class QuizMixin:
    # ---------- interne helpers ----------
    async def _get_api_key(self) -> str | None:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    def _record_recent_mem(self, q: str) -> None:
        cq = canonical_question(q)
        self._recent_questions.append(cq)
        if len(self._recent_questions) > 50:
            self._recent_questions.pop(0)

    async def _get_asked_set(self, guild: discord.Guild) -> set[str]:
        lst = await self.config.guild(guild).asked_questions()
        return {canonical_question(x) for x in (lst or [])}

    async def _remember_question(self, guild: discord.Guild, q: str) -> None:
        cq = canonical_question(q)
        async with self.config.guild(guild).asked_questions() as lst:
            lst.append(cq)
            if len(lst) > 50:
                del lst[:-50]

    # ---------- LLM: batch generatie ----------
    async def _llm_batch_questions(self, thema: str, moeilijkheid: str, want: int = 8) -> List[MCQ]:
        """
        Vraag in één keer meerdere (want) MCQ's. We eisen thema-conform en JSON array.
        Items die off-topic of ongeldig zijn, worden genegeerd.
        """
        api_key = await self._get_api_key()
        if not api_key:
            return []

        prompt = (
            "Genereer een JSON-array met {want} uitdagende multiple-choice quizvragen. "
            "Elke entry is een object met velden: "
            "{question: string, options: [exact 4 korte plausibele opties ZONDER labels], answer: 'A'|'B'|'C'|'D'}. "
            "Lever *alleen* JSON (geen extra tekst).\n"
            f"Thema: {thema}\nMoeilijkheid: {moeilijkheid} (gevorderd/kennersniveau)\n"
            "- ELKE vraag MOET aantoonbaar binnen het opgegeven thema vallen; "
            "als je een vraag niet themaconform krijgt, laat die dan weg zodat de array korter kan zijn.\n"
            "- Opties zonder 'A.' of '1)'; enkel de tekst."
        ).replace("{want}", str(want))

        try:
            async with aiohttp.ClientSession() as sess:
                payload = {
                    "model": "gpt-5-nano",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.5,
                }
                headers = {"Authorization": f"Bearer {api_key}"}
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=45,
                ) as r:
                    data = await r.json()
        except Exception:
            return []

        content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")

        # Probeer een JSON array te extraheren
        arr_text = None
        m = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
        if m:
            arr_text = m.group(0)
        else:
            # Sommige modellen geven losstaande objecten onder elkaar; fallback: maak een array van objecten
            objs = re.findall(r"\{.*?\}", content, re.DOTALL)
            if objs:
                arr_text = "[" + ",".join(objs) + "]"

        if not arr_text:
            return []

        try:
            raw = json.loads(arr_text)
            if not isinstance(raw, list):
                return []
        except Exception:
            return []

        out: List[MCQ] = []
        for item in raw:
            try:
                q = str(item.get("question", "")).strip()
                options = sanitize_options(item.get("options", []))
                ans = str(item.get("answer", "")).strip().upper()
                if q and len(options) == 4 and ans in LETTERS:
                    out.append(MCQ(q, options, ans))
            except Exception:
                continue

        return out

    # ---------- Unieke set samenstellen ----------
    async def _generate_quiz_set(self, guild: discord.Guild, thema: str, moeilijkheid: str, count: int = 5) -> List[MCQ]:
        """
        Bouw een set van *count* unieke vragen:
        1) batch uit LLM
        2) filter op unique (persist + sessie)
        3) vul resterende plekken met fallbacks (ook uniek)
        """
        asked = await self._get_asked_set(guild)
        session_seen = set()  # canonicals binnen deze quiz
        unique: List[MCQ] = []

        # 1) LLM batch
        batch = await self._llm_batch_questions(thema, moeilijkheid, want=max(8, count + 3))
        for mcq in batch:
            cq = canonical_question(mcq.question)
            if cq in asked or cq in self._recent_questions or cq in session_seen:
                continue
            unique.append(mcq)
            session_seen.add(cq)
            if len(unique) >= count:
                break

                # 2) Fallbacks indien nodig
        tries = 0
        while len(unique) < count and tries < 100:
            f = pick_fallback(thema)
            cq = canonical_question(f.question)
            tries += 1
            if cq in asked or cq in self._recent_questions or cq in session_seen:
                continue
            unique.append(f)
            session_seen.add(cq)

        # Als we hier nog steeds te weinig unieke vragen hebben, degradeer netjes
        if len(unique) < count:
            # Voeg (tijdelijk) duplicates toe om te voorkomen dat we vastlopen
            need = count - len(unique)
            pool = [pick_fallback(thema) for _ in range(need)]
            unique.extend(pool[:need])

        # 3) Onthouden (persist + recent), zodat vervolgrondes ook beschermd zijn
        for mcq in unique:
            self._record_recent_mem(mcq.question)
            await self._remember_question(guild, mcq.question)

        # Check of we minder dan 'count' unieke vragen hebben
        if len({canonical_question(q.question) for q in unique}) < count:
            # Wordt straks in _start_quiz als waarschuwing getoond
            pass

        return unique

    # ---------- Cleanup ----------
    async def _cleanup_messages(self, channel: discord.TextChannel, to_delete: List[discord.Message]):
        if not to_delete:
            return
        try:
            bulk = [m for m in to_delete if (discord.utils.utcnow() - m.created_at).days < 14][:100]
            if len(bulk) == 1:
                await bulk[0].delete()
            elif len(bulk) > 1:
                await channel.delete_messages(bulk)
        except Exception:
            for m in to_delete:
                try:
                    if (discord.utils.utcnow() - m.created_at).days < 14:
                        await m.delete()
                except Exception:
                    pass

    # ---------- Commands ----------
    @commands.command()
    async def boozyquiz(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "hard"):
        """
        Start direct een BoozyQuiz™ met **5 vragen** (batch gegenereerd → minder dubbels).
        Vereist 3+ humans in voice, behalve als testmodus=aan en jij TEST_USER_ID bent.
        Reward alleen aan eindwinnaar(s); daily limit per persoon uit settings.
        """
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")

        g = await self.config.guild(ctx.guild).all()
        test_mode = bool(g.get("test_mode", False))
        allow_bypass = (test_mode and ctx.author.id == TEST_USER_ID)

        vc = ctx.author.voice.channel if ctx.author.voice else None
        humans = [m for m in (vc.members if vc else []) if not m.bot] if vc else []
        if not allow_bypass and len(humans) < 3:
            return await ctx.send("🔇 Je moet met minstens **3** gebruikers in een voice-kanaal zitten om te quizzen.")

        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid, is_test=allow_bypass, count=5, include_ask=None)

    @commands.command()
    @checks.admin()
    async def boozyquiztest(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "hard"):
        """Forceer een testquiz (altijd zonder rewards), handig voor solo testen."""
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")
        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid, is_test=True, count=5, include_ask=None)

    # ---------- Core quiz flow ----------
    async def _start_quiz(
        self,
        channel: discord.TextChannel,
        thema: str,
        moeilijkheid: str,
        is_test: bool,
        count: int,
        include_ask: discord.Message | None,
    ):
        thema = normalize_theme(thema)
        self.quiz_active = True
        all_round_msgs: list[discord.Message] = []
        all_answer_msgs: list[discord.Message] = []
        if include_ask:
            all_round_msgs.append(include_ask)  # aanvraag meewissen
        scores: Dict[int, int] = {}

        try:
            # ---- GENEREER VOORAF 5 UNIEKE VRAGEN ----
            async with channel.typing():
                questions = await self._generate_quiz_set(channel.guild, thema, moeilijkheid, count=count)
            try:
                uniq = {canonical_question(q.question) for q in questions}
                if len(uniq) < len(questions):
                    await channel.send(
                        "⚠️ Kon niet genoeg **unieke** vragen vinden binnen dit thema. "
                        "Er zijn tijdelijk een paar herhalingen toegevoegd om de quiz te kunnen starten."
                    )
            except Exception:
                pass

            for ronde, mcq in enumerate(questions, start=1):
                header = f"**Ronde {ronde}/{count}**\n"
                options_str = "\n".join(f"{LETTERS[i]}. {mcq.options[i]}" for i in range(4))
                qmsg = await channel.send(f"{header}❓ **{mcq.question}**\n*(antwoord met A/B/C/D — 25s)*\n{options_str}")
                all_round_msgs.append(qmsg)

                end_time = asyncio.get_event_loop().time() + 25
                winner = None
                attempted: set[int] = set()  # 1 poging per gebruiker

                while True:
                    timeout = max(0, end_time - asyncio.get_event_loop().time())
                    if timeout == 0:
                        break

                    def check(m: discord.Message) -> bool:
                        return (
                            m.channel == channel
                            and not m.author.bot
                            and m.content.upper().strip() in LETTERS
                            and m.author.id not in attempted
                        )

                    try:
                        msg = await self.bot.wait_for("message", timeout=timeout, check=check)
                    except asyncio.TimeoutError:
                        break

                    attempted.add(msg.author.id)
                    all_answer_msgs.append(msg)

                    if msg.content.upper().strip() == mcq.answer_letter.upper():
                        winner = msg.author
                        break
                    else:
                        try:
                            await msg.add_reaction("❌")
                        except Exception:
                            pass
                        continue

                if winner:
                    scores[winner.id] = scores.get(winner.id, 0) + 1
                    all_round_msgs.append(await channel.send(f"✅ {winner.mention} pakt deze ronde!"))
                else:
                    ct = mcq.options[letter_index(mcq.answer_letter)]
                    all_round_msgs.append(await channel.send(f"⌛ Tijd! Antwoord: **{mcq.answer_letter}** — {ct}"))

            # ---- Eindwinnaar(s) & rewards (alleen nu) ----
            if scores:
                g = await self.config.guild(channel.guild).all()
                excluded = g.get("excluded_channels", [])
                reward_amt = int(g.get("quiz_reward_amount", 50))
                limit = int(g.get("quiz_daily_limit", 5))
                reset_hour = int(g.get("quiz_reward_reset_hour", 4))
                cutoff = cutoff_ts_at_hour_utc(reset_hour)

                best = max(scores.values())
                winners_ids = [uid for uid, pts in scores.items() if pts == best]
                names = ", ".join(channel.guild.get_member(uid).display_name for uid in winners_ids if channel.guild.get_member(uid))
                summary = ["🏁 **Eindstand**"]
                for uid, pts in sorted(scores.items(), key=lambda x: x[1], reverse=True):
                    m = channel.guild.get_member(uid)
                    if m:
                        summary.append(f"• **{m.display_name}** — {pts} punt(en)")
                summary.append(f"🏆 Winnaar(s): {names or '_onbekend_'}")

                reward_notes: list[str] = []
                if channel.id in excluded:
                    reward_notes.append("geen rewards in excluded kanaal")
                elif is_test:
                    reward_notes.append("testmodus: geen rewards")
                elif reward_amt <= 0:
                    reward_notes.append("reward staat op 0")
                else:
                    for uid in winners_ids:
                        member = channel.guild.get_member(uid)
                        if not member:
                            continue
                        u = await self.config.user(member).all()
                        # reset teller indien over cutoff heen
                        if u.get("quiz_reward_reset_ts", 0.0) < cutoff:
                            await self.config.user(member).quiz_rewards_today.set(0)
                            await self.config.user(member).quiz_reward_reset_ts.set(datetime.datetime.utcnow().timestamp())
                            u["quiz_rewards_today"] = 0
                        # limit check
                        if u.get("quiz_rewards_today", 0) >= limit:
                            reward_notes.append(f"{member.display_name}: daglimiet bereikt (geen reward)")
                            continue
                        # uitbetalen
                        bal = u.get("booz", 0)
                        await self.config.user(member).booz.set(bal + reward_amt)
                        await self.config.user(member).quiz_rewards_today.set(u.get("quiz_rewards_today", 0) + 1)
                        reward_notes.append(f"{member.display_name}: +{reward_amt} Boo'z")

                if reward_notes:
                    summary.append("💰 Rewards: " + "; ".join(reward_notes))
                all_round_msgs.append(await channel.send("\n".join(summary)))
            else:
                all_round_msgs.append(await channel.send("🏁 **Eindstand**: _geen goede antwoorden dit keer._"))

        finally:
            self.quiz_active = False
            g = await self.config.guild(channel.guild).all()
            if g.get("quiz_autoclean", True):
                await asyncio.sleep(int(g.get("quiz_clean_delay", 5)))
                await self._cleanup_messages(channel, all_round_msgs + all_answer_msgs)
