import re
import json
import aiohttp
import asyncio
import datetime
import discord
from typing import Optional, Dict, List
from redbot.core import commands

from .m01_utils import (
    MCQ, LETTERS, letter_index, sanitize_options, normalize_theme,
    pick_fallback, cutoff_ts_at_hour_utc, TEST_USER_ID
)

class QuizMixin:
    # ---------- interne helpers ----------
    async def _get_api_key(self) -> str | None:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    def _record_recent_mem(self, q: str) -> None:
        self._recent_questions.append(q)
        if len(self._recent_questions) > 50:
            self._recent_questions.pop(0)

    async def _get_asked_set(self, guild: discord.Guild) -> set[str]:
        lst = await self.config.guild(guild).asked_questions()
        return set(lst or [])

    async def _remember_question(self, guild: discord.Guild, q: str) -> None:
        async with self.config.guild(guild).asked_questions() as lst:
            lst.append(q)
            if len(lst) > 50:
                del lst[:-50]

    # ---------- LLM vraag ----------
    async def _llm_question(self, thema: str, moeilijkheid: str) -> Optional[MCQ]:
        api_key = await self._get_api_key()
        if not api_key:
            return None
        prompt = (
            "Genereer 1 uitdagende multiple-choice quizvraag als JSON. "
            "Velden: question (string), options (array van exact 4 korte, plausibele opties zonder labels), "
            "answer (letter A/B/C/D). Lever alleen JSON zonder extra tekst.\n"
            f"Thema: {thema}\nMoeilijkheid: {moeilijkheid} (richt op gevorderd/kennersniveau)\n"
            "- Maak het niet triviaal; kies geloofwaardige maar incorrecte foute opties.\n"
            "- Opties zonder 'A.' of '1)'; enkel de tekst."
        )
        try:
            async with aiohttp.ClientSession() as sess:
                payload = {
                    "model": "gpt-5-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.6,
                }
                headers = {"Authorization": f"Bearer {api_key}"}
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers=headers,
                    timeout=30,
                ) as r:
                    data = await r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if not m:
                return None
            obj = json.loads(m.group())
            q = str(obj.get("question", "")).strip()
            options = sanitize_options(obj.get("options", []))
            ans = str(obj.get("answer", "")).strip().upper()
            if not q or len(options) != 4 or ans not in LETTERS:
                return None
            return MCQ(q, options, ans)
        except Exception:
            return None

    async def _generate_mcq(self, guild: discord.Guild, thema: str, moeilijkheid: str) -> MCQ:
        asked_set = await self._get_asked_set(guild)
        tries = 0
        mcq: MCQ | None = None
        while tries < 8:
            candidate = await self._llm_question(thema, moeilijkheid)
            if not candidate:
                candidate = pick_fallback(thema)
            q = candidate.question.strip()
            if q not in asked_set and q not in self._recent_questions:
                mcq = candidate
                break
            tries += 1
        if mcq is None:
            mcq = pick_fallback(thema)
        self._record_recent_mem(mcq.question)
        await self._remember_question(guild, mcq.question)
        return mcq

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
        Start direct een BoozyQuiz™ met **5 vragen**.
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
    @commands.admin_or_permissions(manage_guild=True)
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
        from .m01_utils import letter_index  # local import to avoid cycles
        thema = normalize_theme(thema)
        self.quiz_active = True
        all_round_msgs: list[discord.Message] = []
        all_answer_msgs: list[discord.Message] = []
        if include_ask:
            all_round_msgs.append(include_ask)  # aanvraag meewissen
        scores: Dict[int, int] = {}

        try:
            for ronde in range(1, count + 1):
                async with channel.typing():
                    mcq = await self._generate_mcq(channel.guild, thema, moeilijkheid)

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
