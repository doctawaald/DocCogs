# M05 --- QUIZ --------------------------------------------------------------
from __future__ import annotations
import asyncio
import json
import re
from typing import List, Dict, Optional, Tuple
import aiohttp
import discord
from aiohttp import ClientTimeout
from redbot.core import commands

from .m01_utils import day_key_utc

COIN = "🪙"

MCQ_COUNT_DEFAULT = 5
QUESTION_TIMEOUT = 35  # per vraag
CLEANUP_DELAY_DEFAULT = 5


class QuizMixin:
    # M05#1 API
    async def _get_api_key(self) -> Optional[str]:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    # M05#2 LLM
    async def _llm_mcq_generate(self, guild: discord.Guild, thema: str, moeilijkheid: str, count: int) -> List[dict]:
        """
        Verwacht lijst met dicts: {question, choices:[A,B,C,D], answer_letter:'A'}
        Geen fallback – als dit faalt, quiz afbreken.
        """
        api_key = await self._get_api_key()
        if not api_key:
            return []

        model = await self.config.guild(guild).llm_model()
        timeout = int(await self.config.guild(guild).llm_timeout())

        # Prompt: *easy/medium/hard* met nadruk dat "easy" echt toegankelijk is
        moeilijkheid = (moeilijkheid or "easy").lower()
        if moeilijkheid not in ("easy","medium","hard"):
            moeilijkheid = "easy"

        sys_rules = (
            "Je bent een maker van toegankelijke, eerlijke meerkeuze-quizvragen voor Discord. "
            "Je schrijft in helder Nederlands, korte vragen, zonder trucjes."
        )
        user_prompt = (
            f"Genereer precies {count} unieke multiple-choice vragen in JSON (alleen JSON, geen tekst erbuiten). "
            f"Thema: '{thema}'. Moeilijkheid: '{moeilijkheid}'.\n"
            "Formaat per item:\n"
            "{\n"
            "  \"question\": \"string (max 120 tekens)\",\n"
            "  \"choices\": [\"A\", \"B\", \"C\", \"D\"],\n"
            "  \"answer_letter\": \"A\"|\"B\"|\"C\"|\"D\"\n"
            "}\n"
            "Regels:\n"
            "- Maak de vragen begrijpelijk en concreet; bij 'easy' vermijd specialistische of obscure kennis.\n"
            "- Antwoorden moeten eenduidig correct zijn.\n"
            "- GEEN dubbele of semantisch gelijke vragen binnen de set.\n"
            "- Gebruik geen codeblokken. Print alleen de JSON-array."
        )

        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": sys_rules},
                {"role": "user", "content": user_prompt},
            ],
        }

        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as sess:
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                ) as r:
                    status = r.status
                    data = await r.json()
        except Exception:
            return []

        if status != 200:
            return []

        content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        m = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
        if not m:
            return []
        try:
            items = json.loads(m.group(0))
            if not isinstance(items, list):
                return []
        except Exception:
            return []

        out: List[dict] = []
        seen_q = set()
        for it in items:
            q = str(it.get("question", "")).strip()
            choices = it.get("choices", [])
            ans = str(it.get("answer_letter", "A")).strip().upper()
            if not q or not isinstance(choices, list) or len(choices) != 4 or ans not in ("A","B","C","D"):
                continue
            # anti-duplicate binnen set
            normq = re.sub(r"\s+", " ", q.lower())
            if normq in seen_q:
                continue
            seen_q.add(normq)
            out.append({"question": q, "choices": [str(c) for c in choices], "answer_letter": ans})

        # exact 'count', anders fail
        if len(out) != count:
            return []
        return out

    # M05#3 QUIZ COMMAND
    @commands.command(name="boozyquiz")
    async def boozyquiz(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "easy", count: int = MCQ_COUNT_DEFAULT):
        """
        Start een quiz met N MCQ-vragen (default 5). Thema & moeilijkheid (easy/medium/hard).
        - Eén winnaar op het einde, die de reward krijgt (onder daily limit).
        - Geen fallback: als LLM faalt, stopt de quiz.
        """
        gconf = await self.config.guild(ctx.guild).all()
        qch_id = gconf.get("quiz_channel")
        channel = ctx.guild.get_channel(qch_id) if qch_id else ctx.channel

        # Denken-bericht i.p.v. typing() context (stabieler te cleanen)
        thinking = await channel.send(f"🤔 BoozyBoi denkt na over **{thema}**…")

        # Genereer set in één keer (minder kans op duplicates)
        items = await self._llm_mcq_generate(ctx.guild, thema, moeilijkheid, max(1, int(count)))
        if not items:
            await thinking.delete()
            return await channel.send("❌ Kan geen vragen genereren (LLM). Probeer een ander thema of later opnieuw.")

        await thinking.delete()

        # Score bijhouden
        scores: Dict[int, int] = {}  # user_id -> punten
        asked_msgs: List[discord.Message] = []
        auto_clean = bool(gconf.get("quiz_autoclean", True))
        clean_delay = int(gconf.get("quiz_clean_delay", CLEANUP_DELAY_DEFAULT))

        def fmt_q(i, total, q, choices):
            letters = ["A","B","C","D"]
            lines = [f"**Vraag {i}/{total}: {q}**"]
            for idx, c in enumerate(choices):
                lines.append(f"{letters[idx]}. {c}")
            lines.append("_Antwoord met A/B/C/D_")
            return "\n".join(lines)

        # Per vraag
        for idx, it in enumerate(items, start=1):
            qtext = it["question"]
            choices = it["choices"]
            correct = it["answer_letter"].upper()

            msg = await channel.send(fmt_q(idx, len(items), qtext, choices))
            asked_msgs.append(msg)

            answered_users: set[int] = set()

            def check(m: discord.Message):
                if m.channel.id != channel.id:
                    return False
                if m.author.bot:
                    return False
                c = m.content.strip().upper()
                if c not in {"A","B","C","D"}:
                    return False
                if m.author.id in answered_users:
                    return False
                return True

            winner: Optional[discord.Member] = None
            try:
                # tot TIMEOUT meerdere antwoorden toelaten; eerste juiste wint die vraag
                end = discord.utils.utcnow().timestamp() + QUESTION_TIMEOUT
                while discord.utils.utcnow().timestamp() < end:
                    left = max(0.0, end - discord.utils.utcnow().timestamp())
                    reply: discord.Message = await self.bot.wait_for("message", timeout=left, check=check)
                    answered_users.add(reply.author.id)
                    if reply.content.strip().upper() == correct:
                        winner = reply.author
                        # +1 punt
                        scores[winner.id] = scores.get(winner.id, 0) + 1
                        await channel.send(f"✅ **{winner.display_name}** is correct!")
                        asked_msgs.append(reply)
                        break
                    else:
                        await channel.send(f"❌ {reply.author.display_name}")
                        asked_msgs.append(reply)
            except asyncio.TimeoutError:
                pass

            if not winner:
                await channel.send(f"⏱️ Tijd voorbij. Juist antwoord was **{correct}**.")

        # EIND: winnaar bepalen (hoogste score; tie-breaker = eerste die dat puntental haalde)
        if not scores:
            return await channel.send("📪 Geen correcte antwoorden. Geen winnaar.")

        # reconstructeren wie zijn laatste punt eerder binnen had
        ranking: List[Tuple[int,int,float]] = []  # (user_id, score, last_ts)
        # We hebben geen timestamps per punt, dus gebruik simpele tie: hoogste score, dan willekeurig consistent op ID.
        # (Je kan dit later uitbreiden door per vraag winnaar-ts te loggen.)
        for uid, sc in scores.items():
            ranking.append((uid, sc, 0.0))
        ranking.sort(key=lambda x: (x[1], -x[0]), reverse=True)
        win_uid, win_score, _ = ranking[0]
        winner = ctx.guild.get_member(win_uid)

        # Reward alleen aan winnaar op het einde, en respecteer daily limit
        if not winner:
            return await channel.send("🏆 Winnaar niet gevonden? (onbekende fout)")

        # daily win limit
        userconf = await self.config.user(winner).all()
        day = day_key_utc()
        reset_hour = int(gconf.get("quiz_reward_reset_hour", 4))
        # Als dag verschilt → reset teller
        if userconf.get("quiz_day") != day:
            userconf["quiz_day"] = day
            userconf["quiz_wins_today"] = 0
            await self.config.user(winner).set_raw("quiz_day", value=day)
            await self.config.user(winner).set_raw("quiz_wins_today", value=0)

        limit = int(gconf.get("quiz_daily_limit", 5))
        reward = int(gconf.get("quiz_reward_amount", 50))
        testmode = bool(gconf.get("global_testmode", False))

        if userconf.get("quiz_wins_today", 0) >= limit:
            await channel.send(f"🏁 **{winner.display_name}** wint (score {win_score}), maar daily limit is bereikt — geen reward.")
        else:
            if testmode:
                await channel.send(f"🏁 **{winner.display_name}** wint (score {win_score}) — 🧪 testmodus: geen Boo'z uitgekeerd.")
            else:
                cur = await self.config.user(winner).booz()
                await self.config.user(winner).booz.set(int(cur) + reward)
                await self.config.user(winner).quiz_wins_today.set(int(userconf.get("quiz_wins_today", 0)) + 1)
                await channel.send(f"🏁 **{winner.display_name}** wint (score {win_score}) — {COIN} +{reward}")

        # Cleanup (indien aan)
        if auto_clean and clean_delay > 0:
            await asyncio.sleep(clean_delay)
            try:
                await asyncio.gather(*[m.delete() for m in asked_msgs if m and m.deletable])
            except Exception:
                pass
