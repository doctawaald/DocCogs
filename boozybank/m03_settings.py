# ============================
# m03_settings.py
# ============================
from __future__ import annotations
import discord
from redbot.core import commands, checks

async def _ok(ctx: commands.Context, msg: str):
    try:
        await ctx.send(f"✅ {msg}")
    except Exception:
        pass

class SettingsMixin:
    # channels
    @commands.command()
    @checks.admin()
    async def setannouncechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).announce_channel.set(ch.id)
        await _ok(ctx, f"Announce-kanaal: {ch.mention}")

    @commands.command()
    @checks.admin()
    async def setquizchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).quiz_channel.set(ch.id)
        await _ok(ctx, f"Quizkanaal: {ch.mention}")

    @commands.command()
    @checks.admin()
    async def excludechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id not in exc:
                exc.append(ch.id)
        await _ok(ctx, f"{ch.mention} uitgesloten voor chat-rewards.")

    @commands.command()
    @checks.admin()
    async def includechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id in exc:
                exc.remove(ch.id)
        await _ok(ctx, f"{ch.mention} telt weer mee voor chat-rewards.")

    # toggles
    @commands.command(name="boozytestmode")
    @checks.admin()
    async def boozytestmode(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).global_testmode.set(on)
        await _ok(ctx, f"Globale testmodus: {'aan' if on else 'uit'}")

    @commands.command()
    async def teststatus(self, ctx: commands.Context):
        on = await self.config.guild(ctx.guild).global_testmode()
        await ctx.send(f"🧪 Testmodus: **{'aan' if on else 'uit'}**")

    @commands.command()
    @checks.admin()
    async def setafkignore(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).afk_excluded.set(on)
        await _ok(ctx, f"AFK-kanaal negeren: {'aan' if on else 'uit'}")

    @commands.command()
    @checks.admin()
    async def setselfmuteignore(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).self_mute_excluded.set(on)
        await _ok(ctx, f"Self-mute/deaf uitsluiten: {'aan' if on else 'uit'}")

    # rewards config
    @commands.command()
    @checks.admin()
    async def setchatreward(self, ctx: commands.Context, amount: int, cooldown_sec: int):
        await self.config.guild(ctx.guild).chat_reward_amount.set(max(0, int(amount)))
        await self.config.guild(ctx.guild).chat_reward_cooldown_sec.set(max(0, int(cooldown_sec)))
        await _ok(ctx, f"Chat-reward +{int(amount)} elke {int(cooldown_sec)}s")

    @commands.command()
    @checks.admin()
    async def setvoicereward(self, ctx: commands.Context, amount: int, interval_sec: int):
        await self.config.guild(ctx.guild).voice_reward_amount.set(max(0, int(amount)))
        await self.config.guild(ctx.guild).voice_reward_interval_sec.set(max(1, int(interval_sec)))
        await _ok(ctx, f"Voice-reward +{int(amount)} elke {int(interval_sec)}s")

    # quiz settings
    @commands.command()
    @checks.admin()
    async def setquizreward(self, ctx: commands.Context, amount: int):
        await self.config.guild(ctx.guild).quiz_reward_amount.set(max(0, int(amount)))
        await _ok(ctx, f"Quiz eindreward: +{int(amount)}")

    @commands.command()
    @checks.admin()
    async def setquizlimit(self, ctx: commands.Context, limit: int):
        await self.config.guild(ctx.guild).quiz_daily_limit.set(max(0, int(limit)))
        await _ok(ctx, f"Quiz daily limit: {int(limit)}")

    @commands.command()
    @checks.admin()
    async def setquizresethour(self, ctx: commands.Context, hour_utc: int):
        hour = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).quiz_reward_reset_hour.set(hour)
        await _ok(ctx, f"Quiz reset-uur (UTC): {hour}:00")

    @commands.command()
    @checks.admin()
    async def setquizdiffmult(self, ctx: commands.Context, easy: float, medium: float, hard: float):
        await self.config.guild(ctx.guild).quiz_diff_mult.set({"easy": float(easy), "medium": float(medium), "hard": float(hard)})
        await _ok(ctx, f"Quiz multipliers gezet: easy={easy}, medium={medium}, hard={hard}")

    # LLM
    @commands.command()
    @checks.admin()
    async def setllmmodel(self, ctx: commands.Context, *, model: str):
        await self.config.guild(ctx.guild).llm_model.set(model.strip())
        await _ok(ctx, f"LLM-model: `{model.strip()}`")

    @commands.command()
    @checks.admin()
    async def setllmtimeout(self, ctx: commands.Context, seconds: int):
        s = max(5, min(120, int(seconds)))
        await self.config.guild(ctx.guild).llm_timeout.set(s)
        await _ok(ctx, f"LLM-timeout: {s}s")

    # overview
    @commands.command()
    async def boozysettings(self, ctx: commands.Context):
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g.get("quiz_channel")) if g.get("quiz_channel") else None
        ach = ctx.guild.get_channel(g.get("announce_channel")) if g.get("announce_channel") else None
        exc = g.get("excluded_channels") or []
        exc_txt = ", ".join((ctx.guild.get_channel(i).mention for i in exc if ctx.guild.get_channel(i))) or "_geen_"
        lines = [
            "🛠 **Boozy settings**",
            f"• Announce: {ach.mention if ach else '_system_'}",
            f"• Quizkanaal: {qch.mention if qch else '_huidig_'}",
            f"• Testmode: {'aan' if g.get('global_testmode', False) else 'uit'}",
            f"• Chat: +{g.get('chat_reward_amount',1)}/{g.get('chat_reward_cooldown_sec',300)}s; Excluded: {exc_txt}",
            f"• Voice: +{g.get('voice_reward_amount',1)}/{g.get('voice_reward_interval_sec',300)}s; AFK-ignore: {'aan' if g.get('afk_excluded',True) else 'uit'}; Self-mute-ignore: {'aan' if g.get('self_mute_excluded',False) else 'uit'}",
            f"• LLM: {g.get('llm_model','gpt-5-nano')} (timeout {g.get('llm_timeout',45)}s)",
            f"• Quiz reward/limit: +{g.get('quiz_reward_amount',50)} / {g.get('quiz_daily_limit',5)}; reset {g.get('quiz_reward_reset_hour',4)}:00 UTC",
        ]
        await ctx.send("\n".join(lines))
