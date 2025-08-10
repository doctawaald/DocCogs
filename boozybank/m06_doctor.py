# [06] DOCTOR — check API key/model/endpoint

import aiohttp
from redbot.core import commands

class DoctorMixin:
    @commands.command()
    @commands.admin_or_permissions(manage_guild=True)
    async def boozydoctor(self, ctx: commands.Context):
        """Diagnose: check API key, model, endpoint en simpele test-call."""
        tokens = await self.bot.get_shared_api_tokens("openai")
        key = tokens.get("api_key")
        if not key:
            return await ctx.send("❌ Geen OpenAI API key gevonden. Zet hem met: `[p]set api openai api_key <KEY>`")

        g = await self.config.guild(ctx.guild).all()
        model = g.get("llm_model", "gpt-5-nano")
        timeout = int(g.get("llm_timeout", 45))

        await ctx.send(f"🔎 Testen… (model: `{model}`, timeout: {timeout}s)")
        payload = {
            "model": model,
            "messages": [{"role": "user", "content": "Beantwoord exact met: OK"}],
            "temperature": 0.1,
        }
        try:
            async with aiohttp.ClientSession() as s:
                async with s.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {key}",
                        "Content-Type": "application/json",
                    },
                    timeout=timeout,
                ) as r:
                    status = r.status
                    data = await r.json()
        except Exception as e:
            return await ctx.send(f"❌ Netwerk/timeout: `{e}`")

        if status != 200:
            return await ctx.send(f"❌ HTTP {status}: `{data}`")

        txt = (data.get("choices") or [{}])[0].get("message", {}).get("content", "").strip()
        if txt.upper().replace(".", "") == "OK":
            await ctx.send("✅ LLM bereikbaar en antwoordt zoals verwacht. Je zou nu echte vragen moeten krijgen.")
        else:
            await ctx.send(f"⚠️ Onverwacht antwoord: `{txt}` (choices: `{data.get('choices')}`)")
