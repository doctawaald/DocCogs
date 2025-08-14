# M03 --- SETTINGS -----------------------------------------------------------
from __future__ import annotations
import discord
from redbot.core import checks, commands

async def ok(ctx: commands.Context, msg: str):
    try:
        await ctx.send(f"✅ {msg}")
    except Exception:
        pass


class SettingsMixin:
    # M03#1 KANALEN
    @commands.command()
    @checks.admin()
    async def setquizchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).quiz_channel.set(ch.id)
        await ok(ctx, f"Quizkanaal: {ch.mention}")

    @commands.command()
    @checks.admin()
    async def setannouncechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).announce_channel.set(ch.id)
        await ok(ctx, f"Announce-kanaal: {ch.mention}")

    @commands.command()
    @checks.admin()
    async def clearannouncechannel(self, ctx: commands.Context):
        await self.config.guild(ctx.guild).announce_channel.clear()
        await ok(ctx, "Announce-kanaal gewist (fallback: system channel).")

    @commands.command()
    @checks.admin()
    async def excludechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id not in exc:
                exc.append(ch.id)
        await ok(ctx, f"{ch.mention} uitgesloten voor chat-rewards.")

    @commands.command()
    @checks.admin()
    async def includechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id in exc:
                exc.remove(ch.id)
        await ok(ctx, f"{ch.mention} telt weer mee voor chat-rewards.")

    # M03#2 REWARDS & TIMING
    @commands.command()
    @checks.admin()
    async def setchatreward(self, ctx: commands.Context, amount: int, cooldown_sec: int):
        amount = max(0, int(amount))
        cd = max(0, int(cooldown_sec))
        await self.config.guild(ctx.guild).chat_reward_amount.set(amount)
        await self.config.guild(ctx.guild).chat_reward_cooldown_sec.set(cd)
        await ok(ctx, f"Chat-reward +{amount} elke {cd}s")

    @commands.command()
    @checks.admin()
    async def setvoicereward(self, ctx: commands.Context, amount: int, interval_sec: int):
        amount = max(0, int(amount))
        itv = max(1, int(interval_sec))
        await self.config.guild(ctx.guild).voice_reward_amount.set(amount)
        await self.config.guild(ctx.guild).voice_reward_interval_sec.set(itv)
        await ok(ctx, f"Voice-reward +{amount} elke {itv}s")

    @commands.command()
    @checks.admin()
    async def setrandomdrop(self, ctx: commands.Context, amount: int):
        amount = max(0, int(amount))
        await self.config.guild(ctx.guild).random_drop_amount.set(amount)
        await ok(ctx, f"Random drop: +{amount} (1×/dag)")

    @commands.command()
    @checks.admin()
    async def setquizreward(self, ctx: commands.Context, amount: int):
        amount = max(0, int(amount))
        await self.config.guild(ctx.guild).quiz_reward_amount.set(amount)
        await ok(ctx, f"Quiz eindreward: +{amount}")

    @commands.command()
    @checks.admin()
    async def setquizlimit(self, ctx: commands.Context, limit: int):
        limit = max(0, int(limit))
        await self.config.guild(ctx.guild).quiz_daily_limit.set(limit)
        await ok(ctx, f"Quiz daily limit: {limit} win(s) met reward")

    @commands.command()
    @checks.admin()
    async def setquizresethour(self, ctx: commands.Context, hour_utc: int):
        hour = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).quiz_reward_reset_hour.set(hour)
        await ok(ctx, f"Quiz reset-uur (UTC): {hour}:00")

    # M03#3 TOGGLES
    @commands.command()
    @checks.admin()
    async def setautoclean(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).quiz_autoclean.set(on)
        await ok(ctx, f"Quiz auto-clean: {'aan' if on else 'uit'}")

    @commands.command()
    @checks.admin()
    async def setcleandelay(self, ctx: commands.Context, seconds: int):
        s = max(0, int(seconds))
        await self.config.guild(ctx.guild).quiz_clean_delay.set(s)
        await ok(ctx, f"Cleanup delay: {s}s")

    @commands.command()
    @checks.admin()
    async def setminvc(self, ctx: commands.Context, n: int):
        n = max(0, int(n))
        await self.config.guild(ctx.guild).min_vc_humans.set(n)
        await ok(ctx, f"Min. VC-humans: {n} (random drop)")

    @commands.command()
    @checks.admin()
    async def setafkignore(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).afk_excluded.set(on)
        await ok(ctx, f"AFK-kanaal negeren (voice reward): {'aan' if on else 'uit'}")

    @commands.command()
    @checks.admin()
    async def setselfmuteignore(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).self_mute_excluded.set(on)
        await ok(ctx, f"Self-mute/deaf uitsluiten (voice reward): {'aan' if on else 'uit'}")

    @commands.command(name="boozytestmode")
    @checks.admin()
    async def boozytestmode(self, ctx: commands.Context, status: str):
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).global_testmode.set(on)
        await ok(ctx, f"Globale testmodus: {'aan' if on else 'uit'}")

    @commands.command()
    async def teststatus(self, ctx: commands.Context):
        on = await self.config.guild(ctx.guild).global_testmode()
        await ctx.send(f"🧪 Globale testmodus: **{'aan' if on else 'uit'}**")

    # M03#4 LLM SETTINGS
    @commands.command()
    @checks.admin()
    async def setllmmodel(self, ctx: commands.Context, *, model: str):
        model = model.strip()
        await self.config.guild(ctx.guild).llm_model.set(model)
        await ok(ctx, f"LLM-model: `{model}`")

    @commands.command()
    @checks.admin()
    async def setllmtimeout(self, ctx: commands.Context, seconds: int):
        s = max(5, min(120, int(seconds)))
        await self.config.guild(ctx.guild).llm_timeout.set(s)
        await ok(ctx, f"LLM-timeout: {s}s")

    # M03#5 FEATURED GAMES (voor challenges & game-bound content)
    @commands.command(aliases=["addgame","addfeatured"])
    @checks.admin()
    async def addfeaturedgame(self, ctx: commands.Context, *, name: str):
        name = name.strip()
        if not name:
            return await ctx.send("Geef een geldige gamenaam.")
        async with self.config.guild(ctx.guild).challenge_featured_list() as lst:
            if name not in lst:
                lst.append(name)
        await ok(ctx, f"Toegevoegd aan featured: **{name}**")

    @commands.command(aliases=["delgame","delfeatured"])
    @checks.admin()
    async def delfeaturedgame(self, ctx: commands.Context, *, name: str):
        name = name.strip()
        async with self.config.guild(ctx.guild).challenge_featured_list() as lst:
            if name in lst:
                lst.remove(name)
        await ok(ctx, f"Verwijderd uit featured: **{name}**")

    @commands.command(aliases=["listgames","listfeatured"])
    async def featuredgames(self, ctx: commands.Context):
        lst = await self.config.guild(ctx.guild).challenge_featured_list()
        if not lst:
            return await ctx.send("📭 Geen featured games ingesteld.")
        await ctx.send("🕹️ **Featured games**: " + ", ".join(lst))

    # M03#6 SETTINGS OVERVIEW
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
            f"• Excluded (chat): {exc_names}",
            f"• Testmodus: {'aan' if g.get('global_testmode', False) else 'uit'}",
            f"• Chat: +{g.get('chat_reward_amount',1)}/{g.get('chat_reward_cooldown_sec',300)}s",
            f"• Voice: +{g.get('voice_reward_amount',1)}/{g.get('voice_reward_interval_sec',300)}s, "
            f"AFK-ignore: {'aan' if g.get('afk_excluded', True) else 'uit'}, "
            f"Self-mute-ignore: {'aan' if g.get('self_mute_excluded', False) else 'uit'}",
            f"• Random drop: +{g.get('random_drop_amount',10)} (min VC-humans {g.get('min_vc_humans',3)})",
            f"• Quiz: reward +{g.get('quiz_reward_amount',50)}, limit {g.get('quiz_daily_limit',5)}, reset {g.get('quiz_reward_reset_hour',4)}:00 UTC",
            f"• LLM: `{g.get('llm_model','gpt-5-nano')}`, timeout {g.get('llm_timeout',45)}s",
        ]
        await ctx.send("\n".join(lines))
