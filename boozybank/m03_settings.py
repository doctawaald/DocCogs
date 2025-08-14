# M03 --- SETTINGS -----------------------------------------------------------
# Kanalen, toggles, reward-instellingen, games/featured, shopkoppeling, testmode
# + Health check command
# ---------------------------------------------------------------------------

# M03#1 IMPORTS
import discord
from redbot.core import checks, commands

# M03#1.1 HELPER
async def send_ok(ctx: commands.Context, text: str):
    try:
        await ctx.send(f"✅ {text}")
    except Exception:
        pass


class SettingsMixin:
    # M03#2 KANALEN & EXCLUSIONS
    @commands.command()
    @checks.admin()
    async def setquizchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).quiz_channel.set(ch.id)
        await send_ok(ctx, f"Quizkanaal ingesteld op {ch.mention}")

    @commands.command(name="setquiz")
    @checks.admin()
    async def setquiz_alias(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self.setquizchannel(ctx, channel)

    @commands.command()
    @checks.admin()
    async def setannouncechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).announce_channel.set(ch.id)
        await send_ok(ctx, f"Announce-kanaal ingesteld op {ch.mention}")

    @commands.command(name="setannounce")
    @checks.admin()
    async def setannounce_alias(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        await self.setannouncechannel(ctx, channel)

    @commands.command()
    @checks.admin()
    async def clearannouncechannel(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).announce_channel.clear()
        await send_ok(ctx, "Announce-kanaal gewist. Fallback: system channel.")

    @commands.command()
    @checks.admin()
    async def excludechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id not in exc:
                exc.append(ch.id)
        await send_ok(ctx, f"{ch.mention} uitgesloten van rewards.")

    @commands.command()
    @checks.admin()
    async def includechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id in exc:
                exc.remove(ch.id)
        await send_ok(ctx, f"{ch.mention} doet weer mee voor rewards.")

    # M03#3 REWARDS & TIMING
    @commands.command()
    @checks.admin()
    async def setchatreward(self, ctx: commands.Context, amount: int, cooldown_sec: int):
        amount = max(0, int(amount))
        cd = max(0, int(cooldown_sec))
        await self.config.guild(ctx.guild).chat_reward_amount.set(amount)
        await self.config.guild(ctx.guild).chat_reward_cooldown_sec.set(cd)
        await send_ok(ctx, f"Chat-reward gezet op +{amount} per {cd}s")

    @commands.command()
    @checks.admin()
    async def setvoicereward(self, ctx: commands.Context, amount: int, interval_sec: int):
        amount = max(0, int(amount))
        itv = max(0, int(interval_sec))
        await self.config.guild(ctx.guild).voice_reward_amount.set(amount)
        await self.config.guild(ctx.guild).voice_reward_interval_sec.set(itv)
        await send_ok(ctx, f"Voice-reward gezet op +{amount} per {itv}s")

    @commands.command()
    @checks.admin()
    async def setrandomdrop(self, ctx: commands.Context, amount: int):
        amount = max(0, int(amount))
        await self.config.guild(ctx.guild).random_drop_amount.set(amount)
        await send_ok(ctx, f"Random drop ingesteld op +{amount} Boo'z per dag")

    @commands.command()
    @checks.admin()
    async def setquizreward(self, ctx: commands.Context, amount: int):
        amount = max(0, int(amount))
        await self.config.guild(ctx.guild).quiz_reward_amount.set(amount)
        await send_ok(ctx, f"Quiz eindreward ingesteld op +{amount} Boo'z")

    @commands.command()
    @checks.admin()
    async def setquizlimit(self, ctx: commands.Context, limit: int):
        limit = max(0, int(limit))
        await self.config.guild(ctx.guild).quiz_daily_limit.set(limit)
        await send_ok(ctx, f"Quiz daily limit ingesteld op {limit}")

    @commands.command()
    @checks.admin()
    async def setquizresethour(self, ctx: commands.Context, hour_utc: int):
        hour = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).quiz_reward_reset_hour.set(hour)
        await send_ok(ctx, f"Quiz reset-uur (UTC) ingesteld op {hour}:00")

    # M03#4 TOGGLES
    @commands.command()
    @checks.admin()
    async def setautoclean(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).quiz_autoclean.set(on)
        await send_ok(ctx, f"Auto-clean is {'aan' if on else 'uit'}")

    @commands.command()
    @checks.admin()
    async def setcleandelay(self, ctx: commands.Context, seconds: int):
        s = max(0, int(seconds))
        await self.config.guild(ctx.guild).quiz_clean_delay.set(s)
        await send_ok(ctx, f"Cleanup delay ingesteld op {s}s")

    @commands.command()
    @checks.admin()
    async def setminvc(self, ctx: commands.Context, n: int):
        n = max(0, int(n))
        await self.config.guild(ctx.guild).min_vc_humans.set(n)
        await send_ok(ctx, f"Min. VC-humans ingesteld op {n}")

    @commands.command()
    @checks.admin()
    async def setautoquiz(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).auto_quiz_enabled.set(on)
        await send_ok(ctx, f"Auto-quiz is {'aan' if on else 'uit'}")

    @commands.command()
    @checks.admin()
    async def setafkignore(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).afk_excluded.set(on)
        await send_ok(ctx, f"AFK-kanaal negeren is {'aan' if on else 'uit'}")

    @commands.command()
    @checks.admin()
    async def setselfmuteignore(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).self_mute_excluded.set(on)
        await send_ok(ctx, f"Self-mute/deaf uitsluiten is {'aan' if on else 'uit'}")

    @commands.command(name="boozytestmode")
    @checks.admin()
    async def boozytestmode(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).global_testmode.set(on)
        await send_ok(ctx, f"Globale testmodus is {'aan' if on else 'uit'}")

    @commands.command()
    async def teststatus(self, ctx: commands.Context):
        on = await self.config.guild(ctx.guild).global_testmode()
        await ctx.send(f"🧪 Globale testmodus: **{'aan' if on else 'uit'}**")

    # M03#5 LLM
    @commands.command()
    @checks.admin()
    async def setllmmodel(self, ctx: commands.Context, *, model: str):
        model = model.strip()
        await self.config.guild(ctx.guild).llm_model.set(model)
        await send_ok(ctx, f"LLM-model gezet op `{model}`")

    @commands.command()
    @checks.admin()
    async def setllmtimeout(self, ctx: commands.Context, seconds: int):
        s = max(5, min(120, int(seconds)))
        await self.config.guild(ctx.guild).llm_timeout.set(s)
        await send_ok(ctx, f"LLM-timeout ingesteld op {s}s")

    # M03#6 OVERZICHT + HEALTH
    @commands.command()
    async def boozysettings(self, ctx: commands.Context):
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g.get("quiz_channel")) if g.get("quiz_channel") else None
        ach = ctx.guild.get_channel(g.get("announce_channel")) if g.get("announce_channel") else None
        excluded = [ctx.guild.get_channel(cid) for cid in g.get("excluded_channels", [])]
        exc_names = ", ".join(ch.mention for ch in excluded if ch) or "_geen_"

        lines = [
            "🛠 **Boozy settings**",
            f"• Quizkanaal: {qch.mention if qch else '_niet ingesteld_'}",
            f"• Announce-kanaal: {ach.mention if ach else '_system/fallback_'}",
            f"• Excluded: {exc_names}",
            f"• Globale testmodus: {'aan' if g.get('global_testmode', False) else 'uit'}",
            f"• Auto-clean: {'aan' if g.get('quiz_autoclean', True) else 'uit'} (delay {g.get('quiz_clean_delay',5)}s)",
            f"• Min. VC-humans: {g.get('min_vc_humans',3)}",
            f"• Auto-quiz: {'aan' if g.get('auto_quiz_enabled', True) else 'uit'}",
            f"• AFK negeren: {'aan' if g.get('afk_excluded', True) else 'uit'}",
            f"• Self-mute/deaf uitsluiten: {'aan' if g.get('self_mute_excluded', False) else 'uit'}",
            f"• Rewards: chat +{g.get('chat_reward_amount',1)}/{g.get('chat_reward_cooldown_sec',300)}s; "
            f"voice +{g.get('voice_reward_amount',1)}/{g.get('voice_reward_interval_sec',300)}s; "
            f"random drop +{g.get('random_drop_amount',10)}; "
            f"quiz +{g.get('quiz_reward_amount',50)} (limit {g.get('quiz_daily_limit',5)}; reset {g.get('quiz_reward_reset_hour',4)}:00 UTC)",
            f"• LLM: model `{g.get('llm_model','gpt-5-nano')}`, timeout {g.get('llm_timeout',45)}s",
        ]
        await ctx.send("\n".join(lines))

    @commands.command()
    async def boozyhealth(self, ctx: commands.Context):
        """Toont status van loops, API, random drop, featured cache, enz."""
        g = await self.config.guild(ctx.guild).all()
        # Tasks
        t1 = getattr(self, "_challenge_task", None)
        t2 = getattr(self, "_random_drop_task", None)
        def alive(t): return (t is not None) and (not t.done()) and (not t.cancelled())
        lines = [
            "🩺 **Boozy health**",
            f"• Challenge-loop: {'running' if alive(t1) else 'stopped'}",
            f"• RandomDrop-loop: {'running' if alive(t2) else 'stopped'}",
            f"• Featured cache dag: {g.get('challenge_featured_cache_day') or '_none_'}",
            f"• Featured vandaag: {', '.join(g.get('challenge_featured_today') or []) or '_none_'}",
            f"• Random drop vandaag: {'JA' if (g.get('random_drop_done_day') == (await self.config.guild(ctx.guild).random_drop_done_day())) else 'nee'}",
        ]
        try:
            tokens = await self.bot.get_shared_api_tokens("openai")
            has_api = bool(tokens.get("api_key"))
            lines.append(f"• OpenAI API key: {'gevonden' if has_api else 'niet gezet'}")
            lines.append(f"• LLM model: {g.get('llm_model','gpt-5-nano')} / timeout {g.get('llm_timeout',45)}s")
        except Exception:
            pass
        await ctx.send("\n".join(lines))
