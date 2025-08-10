# [05] QUIZ — batch MCQ generatie, uniek-filter, difficulty, stop, cleanup, debug

import re
import json
import aiohttp
import asyncio
import datetime
import discord
from typing import Optional, Dict, List, Tuple
from redbot.core import commands, checks

from .m01_utils import (
    MCQ, LETTERS, letter_index, sanitize_options, normalize_theme,
    pick_fallback, cutoff_ts_at_hour_utc, TEST_USER_ID, canonical_question
)

# een kleine jargonlijst om 'easy' vragen te filteren (licht, niet babymakkelijk)
EASY_JARGON = {
    "slew rate","bode","fourier","miller-effect","kircHhoff","superpositie",
    "transferfunctie","impedantie-matching","resonantiepiek","q-factor",
    "schmitt trigger","differentiator","integrator","phase margin","gain-bandwidth",
}

def looks_too_hard_for_easy(text: str) -> bool:
    t = re.sub(r"\s+", " ", str(text or "")).lower()
    if len(t) > 160:
        return True
    return any(k in t for k in EASY_JARGON)

class QuizMixin:
    # [01] API helpers
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

    # [02] LLM batch
    async def _llm_batch_questions(self, *, guild: discord.Guild, thema: str, moeilijkheid: str,
                                   want: int, model: str, timeout: int) -> List[MCQ]:
        api_key = await self._get_api_key()
        if not api_key:
            return []

        # difficulty instructie
        if (moeilijkheid or "").lower() == "easy":
            diff_line = ("Maak de vragen **licht makkelijk** (beginnersniveau), "
                         "vermíjd vakjargon en extreem technische termen. "
                         "Maximaal ~18 woorden per vraag. ")
        else:
            diff_line = "Maak de vragen uitdagend maar eerlijk. "

        prompt = (
            "Genereer een JSON-array met {want} multiple-choice quizvragen. "
            "Elke entry: {question: string, options: [exact 4 korte opties ZONDER labels], answer: 'A'|'B'|'C'|'D'}. "
            "Lever *alleen* JSON.\n"
            f"Thema: {thema}\n"
            f"{diff_line}"
            "Alle vragen MOETEN binnen het thema vallen."
        ).replace("{want}", str(want))

        try:
            async with aiohttp.ClientSession() as sess:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                    # geen temperature → Nano default (1)
                }
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout,
                ) as r:
                    status = r.status
                    data = await r.json()
        except Exception as e:
            print(f"[BoozyBank] LLM network error: {e}")
            return []

        if status != 200:
            print(f"[BoozyBank] LLM HTTP {status}: {data}")
            return []

        content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        arr_text = None
        m = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
        if m:
            arr_text = m.group(0)
        else:
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
        easy_mode = (moeilijkheid or "").lower() == "easy"
        for item in raw:
            try:
                q = str(item.get("question", "")).strip()
                options = sanitize_options(item.get("options", []))
                ans = str(item.get("answer", "")).strip().upper()
                if not (q and len(options) == 4 and ans in LETTERS):
                    continue
                if easy_mode and looks_too_hard_for_easy(q):
                    continue
                out.append(MCQ(q, options, ans))
            except Exception:
                continue
        return out

    # [03] Quizset generator
    async def _generate_quiz_set(self, channel: discord.TextChannel, thema: str, moeilijkheid: str, *,
                                 count: int, model: str, timeout: int) -> Tuple[List[MCQ], Dict[str, int | bool]]:
        guild = channel.guild
        asked = await self._get_asked_set(guild)
        session_seen = set()
        unique: List[MCQ] = []
        stats: Dict[str, int | bool] = {
            "llm_parsed": 0,
            "chosen_from_llm": 0,
            "chosen_fallbacks": 0,
            "duplicates_dropped": 0,
            "degraded": False,
        }

        batch = await self._llm_batch_questions(
            guild=guild, thema=thema, moeilijkheid=moeilijkheid,
            want=max(8, count + 3), model=model, timeout=timeout
        )
        stats["llm_parsed"] = len(batch)

        for mcq in batch:
            cq = canonical_question(mcq.question)
            if cq in asked or cq in self._recent_questions or cq in session_seen:
                stats["duplicates_dropped"] += 1
                continue
            unique.append(mcq)
            session_seen.add(cq)
            stats["chosen_from_llm"] += 1
            if len(unique) >= count:
                break

        # fallbacks (met cap, geen spin)
        tries = 0
        while len(unique) < count and tries < 100:
            f = pick_fallback(thema)
            cq = canonical_question(f.question)
            tries += 1
            if cq in asked or cq in self._recent_questions or cq in session_seen:
                continue
            unique.append(f)
            session_seen.add(cq)
            stats["chosen_fallbacks"] += 1

        if len(unique) < count:
            need = count - len(unique)
            pool = [pick_fallback(thema) for _ in range(need)]
            unique.extend(pool[:need])
            stats["degraded"] = True

        for mcq in unique:
            self._record_recent_mem(mcq.question)
            await self._remember_question(guild, mcq.question)

        # debug naar console:
        print(f"[BoozyBank] gen: parsed={stats['llm_parsed']} chosen_llm={stats['chosen_from_llm']} "
              f"fallbacks={stats['chosen_fallbacks']} dupes={stats['duplicates_dropped']} degraded={stats['degraded']}")

        return unique, stats

    # [04] Cleanup helper
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

    # [05] Commands
    @commands.command()
    async def boozyquiz(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "easy"):
        """Start een BoozyQuiz™ met 5 vragen (batch, uniek-filter, difficulty, eindreward)."""
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")
        g = await self.config.guild(ctx.guild).all()
        test_mode = bool(g.get("test_mode", False))
        allow_bypass = (test_mode and ctx.author.id == TEST_USER_ID)

        vc = ctx.author.voice.channel if ctx.author.voice else None
        humans = [m for m in (vc.members if vc else []) if not m.bot] if vc else []
        if not allow_bypass and len(humans) < 3:
            return await ctx.send("🔇 Je moet met minstens **3** gebruikers in een voice-kanaal zitten om te quizzen.")

        initial = [ctx.message]  # ook je aanvraag straks opruimen
        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid,
                               is_test=allow_bypass, count=5, include_ask=None, initial_msgs=initial)

    @commands.command(aliases=["boozystop"])
    async def boozyquit(self, ctx: commands.Context):
        """Stop de huidige quiz meteen (geen rewards)."""
        if not self.quiz_active:
            return await ctx.send("😶 Er is geen actieve quiz.")
        self.quiz_cancelled = True
        await ctx.send("⏹️ Quiz gestopt.")
        # de cleanup gebeurt in de quiz-loop

    @commands.command()
    @checks.admin()
    async def boozyquiztest(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "easy"):
        """Forceer een testquiz (altijd zonder rewards). Ook je startbericht wordt opgeruimd."""
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")
        initial = [ctx.message]
        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid,
                               is_test=True, count=5, include_ask=None, initial_msgs=initial)

    # [06] Core flow
    async def _start_quiz(
        self,
        channel: discord.TextChannel,
        thema: str,
        moeilijkheid: str,
        is_test: bool,
        count: int,
        include_ask: discord.Message | None,
        initial_msgs: List[discord.Message] | None,
    ):
        thema = normalize_theme(thema)
        self.quiz_active = True
        self.quiz_cancelled = False
        all_round_msgs: list[discord.Message] = []
        all_answer_msgs: list[discord.Message] = []
        if include_ask:
            all_round_msgs.append(include_ask)
        if initial_msgs:
            all_round_msgs.extend(initial_msgs)

        scores: Dict[int, int] = {}

        try:
            g = await self.config.guild(channel.guild).all()
            model = g.get("llm_model", "gpt-5-nano")
            timeout = int(g.get("llm_timeout", 45))
            debug = bool(g.get("debug_quiz", False))

            async with channel.typing():
                questions, stats = await self._generate_quiz_set(
                    channel, thema, moeilijkheid, count=count, model=model, timeout=timeout
                )

            if stats.get("degraded"):
                warn = await channel.send(
                    "⚠️ Kon niet genoeg **unieke** vragen vinden binnen dit thema. "
                    "Er zijn tijdelijk een paar herhalingen toegevoegd om de quiz te kunnen starten."
                )
                all_round_msgs.append(warn)

            if debug:
                dbg = await channel.send(
                    f"🔍 Gen-stats — model `{model}`: "
                    f"LLM parsed: {stats['llm_parsed']}, gekozen uit LLM: {stats['chosen_from_llm']}, "
                    f"fallbacks: {stats['chosen_fallbacks']}, dupes gedropt: {stats['duplicates_dropped']}, "
                    f"degraded: {stats['degraded']}"
                )
                all_round_msgs.append(dbg)

            for ronde, mcq in enumerate(questions, start=1):
                if self.quiz_cancelled:
                    break

                header = f"**Ronde {ronde}/{count}**\n"
                options_str = "\n".join(f"{LETTERS[i]}. {mcq.options[i]}" for i in range(4))
                qmsg = await channel.send(f"{header}❓ **{mcq.question}**\n*(antwoord met A/B/C/D — 25s)*\n{options_str}")
                all_round_msgs.append(qmsg)

                end_time = asyncio.get_event_loop().time() + 25
                winner = None
                attempted: set[int] = set()

                while True:
                    if self.quiz_cancelled:
                        break
                    timeout_left = max(0, end_time - asyncio.get_event_loop().time())
                    if timeout_left == 0:
                        break

                    def check(m: discord.Message) -> bool:
                        return (
                            m.channel == channel
                            and not m.author.bot
                            and m.content.upper().strip() in LETTERS
                            and m.author.id not in attempted
                        )
                    try:
                        msg = await self.bot.wait_for("message", timeout=timeout_left, check=check)
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

                if self.quiz_cancelled:
                    break

                if winner:
                    scores[winner.id] = scores.get(winner.id, 0) + 1
                    all_round_msgs.append(await channel.send(f"✅ {winner.mention} pakt deze ronde!"))
                else:
                    ct = mcq.options[letter_index(mcq.answer_letter)]
                    all_round_msgs.append(await channel.send(f"⌛ Tijd! Antwoord: **{mcq.answer_letter}** — {ct}"))

            # eindstand & eindreward (alleen als niet afgebroken en er scores zijn)
            if not self.quiz_cancelled and scores:
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
                        if u.get("quiz_reward_reset_ts", 0.0) < cutoff:
                            await self.config.user(member).quiz_rewards_today.set(0)
                            await self.config.user(member).quiz_reward_reset_ts.set(datetime.datetime.utcnow().timestamp())
                            u["quiz_rewards_today"] = 0
                        if u.get("quiz_rewards_today", 0) >= limit:
                            reward_notes.append(f"{member.display_name}: daglimiet bereikt (geen reward)")
                            continue
                        bal = u.get("booz", 0)
                        await self.config.user(member).booz.set(bal + reward_amt)
                        await self.config.user(member).quiz_rewards_today.set(u.get("quiz_rewards_today", 0) + 1)
                        reward_notes.append(f"{member.display_name}: +{reward_amt} Boo'z")

                if reward_notes:
                    summary.append("💰 Rewards: " + "; ".join(reward_notes))
                all_round_msgs.append(await channel.send("\n".join(summary)))
            elif self.quiz_cancelled:
                all_round_msgs.append(await channel.send("🛑 Quiz beëindigd."))

        finally:
            self.quiz_active = False
            g = await self.config.guild(channel.guild).all()
            if g.get("quiz_autoclean", True):
                await asyncio.sleep(int(g.get("quiz_clean_delay", 5)))
                await self._cleanup_messages(channel, all_round_msgs + all_answer_msgs)
