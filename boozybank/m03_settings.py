# [03] SETTINGS — kanaal/exclusions + reward config + toggles

import discord
from redbot.core import checks, commands

class SettingsMixin:
    # [01] Kanaal & exclusions
    @commands.command()
    @checks.admin()
    async def setquizchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Stel quizkanaal in (default: dit kanaal)."""
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).quiz_channel.set(ch.id)
        await ctx.send(f"✅ Quizkanaal ingesteld op {ch.mention}")

    @commands.command()
    @checks.admin()
    async def excludechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Sluit kanaal uit van alle rewards (default: dit kanaal)."""
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id not in exc:
                exc.append(ch.id)
        await ctx.send(f"🚫 {ch.mention} uitgesloten van rewards.")

    @commands.command()
    @checks.admin()
    async def includechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Haal kanaal uit de uitsluitlijst (default: dit kanaal)."""
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id in exc:
                exc.remove(ch.id)
        await ctx.send(f"✅ {ch.mention} doet weer mee voor rewards.")

    # [02] Reward config
    @commands.command()
    @checks.admin()
    async def setchatreward(self, ctx: commands.Context, amount: int, cooldown_sec: int):
        """Stel chat reward in: !setchatreward <amount> <cooldown_sec>"""
        await self.config.guild(ctx.guild).chat_reward_amount.set(max(0, amount))
        await self.config.guild(ctx.guild).chat_reward_cooldown_sec.set(max(0, cooldown_sec))
        await ctx.send(f"💬 Chat reward: +{max(0,amount)} per {max(0,cooldown_sec)}s")

    @commands.command()
    @checks.admin()
    async def setvoicereward(self, ctx: commands.Context, amount: int, interval_sec: int):
        """Stel voice reward in: !setvoicereward <amount> <interval_sec>"""
        await self.config.guild(ctx.guild).voice_reward_amount.set(max(0, amount))
        await self.config.guild(ctx.guild).voice_reward_interval_sec.set(max(0, interval_sec))
        await ctx.send(f"🎙️ Voice reward: +{max(0,amount)} per {max(0,interval_sec)}s")

    @commands.command()
    @checks.admin()
    async def setrandomdrop(self, ctx: commands.Context, amount: int):
        """Stel random drop in: !setrandomdrop <amount> (1× per dag bij drukste VC)"""
        await self.config.guild(ctx.guild).random_drop_amount.set(max(0, amount))
        await ctx.send(f"🎁 Random drop: +{max(0,amount)} Boo'z per dag")

    @commands.command()
    @checks.admin()
    async def setquizreward(self, ctx: commands.Context, amount: int):
        """Stel quiz eindreward in: !setquizreward <amount>"""
        await self.config.guild(ctx.guild).quiz_reward_amount.set(max(0, amount))
        await ctx.send(f"🏆 Quiz eindreward: +{max(0,amount)} Boo'z")

    @commands.command()
    @checks.admin()
    async def setquizresethour(self, ctx: commands.Context, hour_utc: int):
        """Stel dagelijkse reset-uur (UTC) in: !setquizresethour <0-23>"""
        hour = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).quiz_reward_reset_hour.set(hour)
        await ctx.send(f"⏰ Reset-uur gezet op {hour}:00 UTC")

    @commands.command()
    @checks.admin()
    async def setquizlimit(self, ctx: commands.Context, limit: int):
        """Max belonende quizzes per dag per user: !setquizlimit <n>"""
        await self.config.guild(ctx.guild).quiz_daily_limit.set(max(0, limit))
        await ctx.send(f"🚦 Quiz daily limit: **{max(0, limit)}**")

    # [03] LLM settings
    @commands.command()
    @checks.admin()
    async def setllmmodel(self, ctx: commands.Context, *, model: str):
        """Stel het LLM-model in (bv. gpt-5-nano)."""
        await self.config.guild(ctx.guild).llm_model.set(model.strip())
        await ctx.send(f"🧠 LLM-model gezet op `{model.strip()}`")

    @commands.command()
    @checks.admin()
    async def setllmtimeout(self, ctx: commands.Context, seconds: int):
        """Stel de LLM-timeout (seconden) in."""
        s = max(5, min(120, int(seconds)))
        await self.config.guild(ctx.guild).llm_timeout.set(s)
        await ctx.send(f"⏱️ LLM-timeout ingesteld op **{s}s**")

    # [04] Debug toggle
    @commands.command()
    @checks.admin()
    async def boozydebug(self, ctx: commands.Context, status: str):
        """Zet quiz debug aan/uit (toont generatie-stats). Voorbeeld: !boozydebug on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).debug_quiz.set(on)
        await ctx.send(f"🔍 Debug is **{'aan' if on else 'uit'}**.")

    # [05] Overzicht
    @commands.command()
    async def boozysettings(self, ctx: commands.Context):
        """Toon huidige BoozyBank-instellingen."""
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g.get("quiz_channel")) if g.get("quiz_channel") else None
        excluded = [ctx.guild.get_channel(cid) for cid in g.get("excluded_channels", [])]
        exc_names = ", ".join(ch.mention for ch in excluded if ch) or "_geen_"
        asked_len = len(g.get("asked_questions", []))
        await ctx.send(
            "\n".join([
                "🛠 **Boozy settings**",
                f"• Quizkanaal: {qch.mention if qch else '_niet ingesteld_'}",
                f"• Excluded: {exc_names}",
                f"• Auto-clean: {'aan' if g.get('quiz_autoclean', True) else 'uit'} (delay {g.get('quiz_clean_delay',5)}s)",
                f"• Testmodus: {'aan' if g.get('test_mode', False) else 'uit'}",
                f"• Debug: {'aan' if g.get('debug_quiz', False) else 'uit'}",
                f"• Anti-dup history: {asked_len} vragen",
                "• **Rewards**:",
                f"   - Chat: +{g.get('chat_reward_amount',1)} / {g.get('chat_reward_cooldown_sec',300)}s",
                f"   - Voice: +{g.get('voice_reward_amount',1)} / {g.get('voice_reward_interval_sec',300)}s",
                f"   - Random drop: +{g.get('random_drop_amount',10)} per dag",
                f"   - Quiz eindreward: +{g.get('quiz_reward_amount',50)} | reset-uur (UTC): {g.get('quiz_reward_reset_hour',4)} | daily limit: {g.get('quiz_daily_limit',5)}",
                f"• LLM: model `{g.get('llm_model','gpt-5-nano')}`, timeout {g.get('llm_timeout',45)}s",
            ])
        )
