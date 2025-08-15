# ============================
# m05_quiz.py
# ============================
from __future__ import annotations
import asyncio, json, re
from typing import List, Dict, Optional
import aiohttp
import discord
from aiohttp import ClientTimeout
from redbot.core import commands
from .m01_utils import day_key_utc

class QuizMixin:
    # M05#1 API KEY
    async def _get_api_key(self) -> Optional[str]:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    # M05#2 LLM BATCH
    async def _llm_mcq_generate(self, guild: discord.Guild, thema: str, moeilijkheid: str, count: int) -> List[dict]:
        api_key = await self._get_api_key()
        if not api_key:
            return []
        g = await self.config.guild(guild).all()
        model = g.get("llm_model", "gpt-5-nano")
        timeout = int(g.get("llm_timeout", 45))
        moeilijkheid = (moeilijkheid or "easy").lower()
        if moeilijkheid not in ("easy","medium","hard"):
            moeilijkheid = "easy"
        sys = "Je schrijft toegankelijke, eenduidige meerkeuzevragen in NL."
        user = (
            f"Genereer precies {count} unieke MCQ's als JSON-array. Thema: '{thema}'. Moeilijkheid: '{moeilijkheid}'.\n"
            "Formaat per item: {\"question\":str, \"choices\":[A,B,C,D], \"answer_letter\": 'A'|'B'|'C'|'D' }.\n"
            "Regels: korte heldere vraag (<120 tekens), geen trucjes, geen dubbele/semantisch gelijke vragen, alleen JSON, geen codeblokken."
        )
        payload = {"model": model, "messages": [{"role":"system","content":sys},{"role":"user","content":user}]}
        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as sess:
                async with sess.post("https://api.openai.com/v1/chat/completions", json=payload, headers={"Authorization": f"Bearer {api_key}", "Content-Type":"application/json"}) as r:
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
        except Exception:
            return []
        out, seen = [], set()
        for it in items:
            q = str(it.get("question",""))
            ch = it.get("choices", [])
            ans = str(it.get("answer_letter","A")).upper()
            if not q or not isinstance(ch, list) or len(ch) != 4 or ans not in ("A","B","C","D"):
                continue
            normq = re.sub(r"\s+"," ", q.strip().lower())
            if normq in seen:
                continue
            seen.add(normq)
            out.append({"question": q.strip(), "choices": [str(x) for x in ch], "answer_letter": ans})
        return out if len(out) == count else []

    # M05#3 QUIZ COMMAND
    @commands.command(name="boozyquiz")
    async def boozyquiz(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "easy", count: int = 5):
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g.get("quiz_channel")) if g.get("quiz_channel") else ctx.channel
        thinking = await qch.send(f"🤔 BoozyBoi denkt na over **{thema}**…")
        items = await self._llm_mcq_generate(ctx.guild, thema, moeilijkheid, max(1, int(count)))
        if not items:
            await thinking.delete()
            return await qch.send("❌ Kan geen vragen genereren. Probeer later of ander thema.")
        await thinking.delete()

        scores: Dict[int, int] = {}
        asked_msgs: List[discord.Message] = []
        auto_clean = bool(g.get("quiz_autoclean", True))
        clean_delay = int(g.get("quiz_clean_delay", 5))

        def fmt_q(i, total, q, choices):
            letters = ["A","B","C","D"]
            lines = [f"**Vraag {i}/{total}: {q}**"]
            for idx, c in enumerate(choices):
                lines.append(f"{letters[idx]}. {c}")
            lines.append("_Antwoord met A/B/C/D_")
            return "\n".join(lines)

        for idx, it in enumerate(items, 1):
            qtext, choices, correct = it["question"], it["choices"], it["answer_letter"].upper()
            msg = await qch.send(fmt_q(idx, len(items), qtext, choices))
            asked_msgs.append(msg)
            answered = set()

            def check(m: discord.Message):
                if m.channel.id != qch.id or m.author.bot:
                    return False
                c = m.content.strip().upper()
                if c not in {"A","B","C","D"}:
                    return False
                if m.author.id in answered:
                    return False
                return True

            winner = None
            try:
                end = discord.utils.utcnow().timestamp() + 35
                while discord.utils.utcnow().timestamp() < end:
                    left = max(0.0, end - discord.utils.utcnow().timestamp())
                    rep: discord.Message = await self.bot.wait_for("message", timeout=left, check=check)
                    answered.add(rep.author.id)
                    if rep.content.strip().upper() == correct:
                        winner = rep.author
                        scores[winner.id] = scores.get(winner.id, 0) + 1
                        asked_msgs.append(rep)
                        await qch.send(f"✅ **{winner.display_name}** is correct!")
                        break
                    else:
                        asked_msgs.append(rep)
                        await qch.send(f"❌ {rep.author.display_name}")
            except asyncio.TimeoutError:
                pass
            if not winner:
                await qch.send(f"⏱️ Tijd voorbij. Juist was **{correct}**.")

        if not scores:
            return await qch.send("📪 Geen correcte antwoorden. Geen winnaar.")
        # kies hoogste score, tie-break: id desc consistent
        win_uid, win_score = sorted(scores.items(), key=lambda kv: (kv[1], -kv[0]), reverse=True)[0]
        member = ctx.guild.get_member(win_uid)
        if not member:
            return await qch.send("🏆 Winnaar niet gevonden.")

        # reward schaal per difficulty
        base = int(g.get("quiz_reward_amount", 50))
        mults = g.get("quiz_diff_mult", {"easy":1.0,"medium":1.25,"hard":1.5})
        diff = (moeilijkheid or "easy").lower()
        mult = float(mults.get(diff, 1.0))
        reward = int(base * mult)

        # daily limit
        u = await self.config.user(member).all()
        today = day_key_utc()
        if u.get("quiz_day") != today:
            await self.config.user(member).quiz_day.set(today)
            await self.config.user(member).quiz_wins_today.set(0)
            u["quiz_wins_today"] = 0
        limit = int(g.get("quiz_daily_limit", 5))
        if int(u.get("quiz_wins_today", 0)) >= limit:
            await qch.send(f"🏁 **{member.display_name}** wint (score {win_score}), maar daily limit is bereikt — geen reward.")
        else:
            newv = await self.add_booz(ctx.guild, member, reward, reason=f"Quiz win ({thema}/{diff})")
            await self.config.user(member).quiz_wins_today.set(int(u.get("quiz_wins_today", 0)) + 1)
            await qch.send(f"🏁 **{member.display_name}** wint (score {win_score}) — +{reward} Boo'z (saldo {newv})")

        if auto_clean and clean_delay > 0:
            await asyncio.sleep(clean_delay)
            try:
                await asyncio.gather(*[m.delete() for m in asked_msgs if m and m.deletable])
            except Exception:
                pass
