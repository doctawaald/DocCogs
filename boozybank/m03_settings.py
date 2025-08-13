# M03 --- SETTINGS -----------------------------------------------------------
# Kanalen, toggles, reward-instellingen, games/featured beheer, shop
# + Globale testmodus + overzicht
# ---------------------------------------------------------------------------

# M03#1 IMPORTS
import discord
from redbot.core import checks, commands


# M03#2 MIXIN
class SettingsMixin:
    # ----------------- KANALEN & EXCLUSIONS --------------------------------
    # M03#2.1 Quizkanaal
    @commands.command()
    @checks.admin()
    async def setquizchannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Stel quizkanaal in (default: dit kanaal)."""
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).quiz_channel.set(ch.id)
        await ctx.send(f"✅ Quizkanaal ingesteld op {ch.mention}")

    # M03#2.2 Announce-kanaal
    @commands.command()
    @checks.admin()
    async def setannouncechannel(self, ctx: commands.Context, channel: discord.TextChannel | None = None):
        """Stel announce-kanaal in (challenge/community meldingen)."""
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).announce_channel.set(ch.id)
        await ctx.send(f"📣 Announce-kanaal ingesteld op {ch.mention}")

    @commands.command()
    @checks.admin()
    async def clearannouncechannel(self, ctx: commands.Context):
        """Verwijder announce-kanaal (fallback: system channel)."""
        await self.config.guild(ctx.guild).announce_channel.clear()
        await ctx.send("🧹 Announce-kanaal gewist. Fallback: system channel.")

    # M03#2.3 Exclude/Include kanaal voor rewards
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

    # ----------------- REWARDS & TIMING ------------------------------------
    # M03#2.4 Chat reward
    @commands.command()
    @checks.admin()
    async def setchatreward(self, ctx: commands.Context, amount: int, cooldown_sec: int):
        """!setchatreward <amount> <cooldown_sec>"""
        await self.config.guild(ctx.guild).chat_reward_amount.set(max(0, amount))
        await self.config.guild(ctx.guild).chat_reward_cooldown_sec.set(max(0, cooldown_sec))
        await ctx.send(f"💬 Chat: +{max(0,amount)} per {max(0,cooldown_sec)}s")

    # M03#2.5 Voice reward
    @commands.command()
    @checks.admin()
    async def setvoicereward(self, ctx: commands.Context, amount: int, interval_sec: int):
        """!setvoicereward <amount> <interval_sec>"""
        await self.config.guild(ctx.guild).voice_reward_amount.set(max(0, amount))
        await self.config.guild(ctx.guild).voice_reward_interval_sec.set(max(0, interval_sec))
        await ctx.send(f"🎙️ Voice: +{max(0,amount)} per {max(0,interval_sec)}s")

    # M03#2.6 Random drop
    @commands.command()
    @checks.admin()
    async def setrandomdrop(self, ctx: commands.Context, amount: int):
        """!setrandomdrop <amount> (1× per dag)"""
        await self.config.guild(ctx.guild).random_drop_amount.set(max(0, amount))
        await ctx.send(f"🎁 Random drop: +{max(0,amount)} Boo'z per dag")

    # M03#2.7 Quiz reward & limieten
    @commands.command()
    @checks.admin()
    async def setquizreward(self, ctx: commands.Context, amount: int):
        """!setquizreward <amount> (eindreward voor winnaar)"""
        await self.config.guild(ctx.guild).quiz_reward_amount.set(max(0, amount))
        await ctx.send(f"🏆 Quiz eindreward: +{max(0,amount)} Boo'z")

    @commands.command()
    @checks.admin()
    async def setquizlimit(self, ctx: commands.Context, limit: int):
        """!setquizlimit <n> (belonende quizzes per dag per user)"""
        await self.config.guild(ctx.guild).quiz_daily_limit.set(max(0, limit))
        await ctx.send(f"🚦 Quiz daily limit: **{max(0, limit)}**")

    @commands.command()
    @checks.admin()
    async def setquizresethour(self, ctx: commands.Context, hour_utc: int):
        """!setquizresethour <0-23> (UTC)"""
        hour = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).quiz_reward_reset_hour.set(hour)
        await ctx.send(f"⏰ Quiz reset-uur: {hour}:00 UTC")

    # ----------------- SYSTEEM TOGGLES -------------------------------------
    # M03#2.8 Auto-clean quiz
    @commands.command()
    @checks.admin()
    async def setautoclean(self, ctx: commands.Context, status: str):
        """!setautoclean on/off (quiz-berichten opruimen)"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).quiz_autoclean.set(on)
        await ctx.send(f"🧹 Auto-clean is **{'aan' if on else 'uit'}**.")

    # M03#2.9 Cleanup delay
    @commands.command()
    @checks.admin()
    async def setcleandelay(self, ctx: commands.Context, seconds: int):
        """!setcleandelay <s>"""
        s = max(0, int(seconds))
        await self.config.guild(ctx.guild).quiz_clean_delay.set(s)
        await ctx.send(f"⏳ Cleanup delay: **{s}s**")

    # M03#2.10 VC minimum
    @commands.command()
    @checks.admin()
    async def setminvc(self, ctx: commands.Context, n: int):
        """!setminvc <n> (min #humans in VC voor rewards/quiz/drop)"""
        n = max(0, int(n))
        await self.config.guild(ctx.guild).min_vc_humans.set(n)
        await ctx.send(f"👥 Min. VC-humans: **{n}**")

    # M03#2.11 Auto-quiz
    @commands.command()
    @checks.admin()
    async def setautoquiz(self, ctx: commands.Context, status: str):
        """!setautoquiz on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).auto_quiz_enabled.set(on)
        await ctx.send(f"🤖 Auto-quiz is **{'aan' if on else 'uit'}**.")

    # M03#2.12 AFK negeren / self-mute uitsluiten
    @commands.command()
    @checks.admin()
    async def setafkignore(self, ctx: commands.Context, status: str):
        """!setafkignore on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).afk_excluded.set(on)
        await ctx.send(f"😴 AFK-kanaal negeren: **{'aan' if on else 'uit'}**")

    @commands.command()
    @checks.admin()
    async def setselfmuteignore(self, ctx: commands.Context, status: str):
        """!setselfmuteignore on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).self_mute_excluded.set(on)
        await ctx.send(f"🔇 Self-mute/deaf uitsluiten: **{'aan' if on else 'uit'}**")

    # M03#2.13 Legacy test (bestaand)
    @commands.command()
    @checks.admin()
    async def settestmode(self, ctx: commands.Context, status: str):
        """!settestmode on/off (legacy paden)"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).test_mode.set(on)
        await ctx.send(f"🧪 Testmodus (legacy) is **{'aan' if on else 'uit'}**.")

    # M03#2.14 NIEUW: Globale testmodus
    @commands.command()
    @checks.admin()
    async def setglobaltest(self, ctx: commands.Context, status: str):
        """!setglobaltest on/off — alle Boo’z rewards uit voor *alles*"""
        on = status.lower() in ("on","aan","true","yes","1")
        await self.config.guild(ctx.guild).global_testmode.set(on)
        await ctx.send(f"🧪 Globale testmodus is **{'aan' if on else 'uit'}**.")

    @commands.command()
    async def teststatus(self, ctx: commands.Context):
        """Toon status van de globale testmodus."""
        on = await self.config.guild(ctx.guild).global_testmode()
        await ctx.send(f"🧪 Globale testmodus: **{'aan' if on else 'uit'}**")

    # ----------------- LLM SETTINGS ----------------------------------------
    # M03#2.15 Model + timeout
    @commands.command()
    @checks.admin()
    async def setllmmodel(self, ctx: commands.Context, *, model: str):
        """!setllmmodel <model> (bv. gpt-5-nano)"""
        await self.config.guild(ctx.guild).llm_model.set(model.strip())
        await ctx.send(f"🧠 LLM-model gezet op `{model.strip()}`")

    @commands.command()
    @checks.admin()
    async def setllmtimeout(self, ctx: commands.Context, seconds: int):
        """!setllmtimeout <seconden> (5..120)"""
        s = max(5, min(120, int(seconds)))
        await self.config.guild(ctx.guild).llm_timeout.set(s)
        await ctx.send(f"⏱️ LLM-timeout ingesteld op **{s}s**")

    # ----------------- SHOP -------------------------------------------------
    # M03#2.16 Prijs / rol / items
    @commands.command()
    @checks.admin()
    async def setshopprice(self, ctx: commands.Context, key: str, price: int):
        """!setshopprice <key> <price>"""
        key = key.lower().strip()
        async with self.config.guild(ctx.guild).shop() as shop:
            if key not in shop:
                shop[key] = {"price": max(0, price), "role_id": None}
            else:
                shop[key]["price"] = max(0, price)
        await ctx.send(f"🏪 Prijs van **{key}** gezet op **{max(0,price)}** Boo'z.")

    @commands.command()
    @checks.admin()
    async def setshoprole(self, ctx: commands.Context, key: str, role: discord.Role):
        """!setshoprole <key> <@rol>"""
        key = key.lower().strip()
        async with self.config.guild(ctx.guild).shop() as shop:
            if key not in shop:
                shop[key] = {"price": 0, "role_id": role.id}
            else:
                shop[key]["role_id"] = role.id
        await ctx.send(f"🎭 Rol **{role.name}** gekoppeld aan **{key}**.")

    @commands.command()
    @checks.admin()
    async def addshopitem(self, ctx: commands.Context, key: str, price: int = 0):
        """!addshopitem <key> [price]"""
        key = key.lower().strip()
        async with self.config.guild(ctx.guild).shop() as shop:
            shop[key] = {"price": max(0, price), "role_id": None}
        await ctx.send(f"🆕 Item **{key}** toegevoegd met prijs **{max(0,price)}** Boo'z.")

    @commands.command()
    @checks.admin()
    async def removeshopitem(self, ctx: commands.Context, key: str):
        """!removeshopitem <key>"""
        key = key.lower().strip()
        async with self.config.guild(ctx.guild).shop() as shop:
            if key in shop:
                del shop[key]
                await ctx.send(f"🗑️ Item **{key}** verwijderd.")
            else:
                await ctx.send("❌ Dat item bestaat niet.")

    # ----------------- GAMES / FEATURED ------------------------------------
    # M03#2.17 Game-lijst beheer
    @commands.command(name="addgame")
    @checks.admin()
    async def addgame(self, ctx: commands.Context, *, game: str):
        """Voeg een game toe aan de game-lijst (pool voor featured)."""
        game = game.strip()
        if not game:
            return await ctx.send("❌ Geef een geldige game-naam.")
        async with self.config.guild(ctx.guild).challenge_featured_list() as lst:
            if game in lst:
                return await ctx.send(f"ℹ️ **{game}** staat al in de lijst.")
            lst.append(game)
            lst_sorted = sorted(lst, key=str.lower)
        await ctx.send(f"🎮 Toegevoegd: **{game}**\nLijst: {', '.join(lst_sorted)}")

    @commands.command(name="removegame")
    @checks.admin()
    async def removegame(self, ctx: commands.Context, *, game: str):
        """Verwijder een game uit de game-lijst."""
        game = game.strip()
        async with self.config.guild(ctx.guild).challenge_featured_list() as lst:
            if game not in lst:
                return await ctx.send(f"❌ **{game}** staat niet in de lijst.")
            lst.remove(game)
            lst_sorted = sorted(lst, key=str.lower)
        await ctx.send(f"🗑️ Verwijderd: **{game}**\nLijst: {', '.join(lst_sorted) if lst_sorted else '_leeg_'}")

    @commands.command(name="setgamelist")
    @checks.admin()
    async def setgamelist(self, ctx: commands.Context, *, games_csv: str):
        """Overschrijf de game-lijst (komma-gescheiden)."""
        names = [g.strip() for g in games_csv.split(",") if g.strip()]
        names = sorted(list(dict.fromkeys(names)), key=str.lower)
        await self.config.guild(ctx.guild).challenge_featured_list.set(names)
        await ctx.send(f"🗂️ Game-lijst ingesteld: {', '.join(names) if names else '_leeg_'}")

    @commands.command()
    async def listgames(self, ctx: commands.Context):
        """Toon de huidige game-lijst."""
        lst = await self.config.guild(ctx.guild).challenge_featured_list()
        await ctx.send(f"🎮 Games: {', '.join(sorted(lst, key=str.lower)) if lst else '_leeg_'}")

    # M03#2.18 Featured modus
    @commands.command()
    @checks.admin()
    async def setfeaturedmode(self, ctx: commands.Context, mode: str):
        """Zet featured-modus: auto / manual."""
        m = mode.lower()
        if m not in ("auto", "manual"):
            return await ctx.send("❌ Kies 'auto' of 'manual'.")
        await self.config.guild(ctx.guild).challenge_featured_mode.set(m)
        await ctx.send(f"⚙️ Featured-modus: **{m}**")

    @commands.command()
    @checks.admin()
    async def setfeaturedcount(self, ctx: commands.Context, n: int):
        """Auto-modus: hoeveel games per dag kiezen (1..3)."""
        n = min(3, max(1, int(n)))
        await self.config.guild(ctx.guild).challenge_featured_count.set(n)
        await ctx.send(f"🔢 Featured auto-pick per dag: **{n}**")

    @commands.command()
    @checks.admin()
    async def setfeaturedday(self, ctx: commands.Context, weekday: str, *, games_csv: str):
        """
        Manual-modus: stel games voor een weekdag in.
        Voorbeeld: !setfeaturedday mon Fortnite, Rocket League
        """
        wk = weekday.lower()[:3]
        if wk not in {"mon","tue","wed","thu","fri","sat","sun"}:
            return await ctx.send("❌ Weekdag moet zijn: mon,tue,wed,thu,fri,sat,sun")
        games = [g.strip() for g in games_csv.split(",") if g.strip()]
        async with self.config.guild(ctx.guild).challenge_featured_week() as week:
            week[wk] = games
        await ctx.send(f"📅 {wk}: {', '.join(games) if games else '_leeg_'}")

    @commands.command()
    async def listfeatured(self, ctx: commands.Context):
        """Toon featured-modus, lijst en vandaag."""
        g = await self.config.guild(ctx.guild).all()
        mode = g.get("challenge_featured_mode", "auto")
        cnt = g.get("challenge_featured_count", 2)
        lst = g.get("challenge_featured_list", []) or []
        week = g.get("challenge_featured_week", {}) or {}
        today = g.get("challenge_featured_today", []) or []
        lines = [
            f"📋 Featured modus: **auto** (auto-pick count: {cnt})" if mode == "auto"
            else "📋 Featured modus: **manual**",
            f"• Lijst: {', '.join(sorted(lst, key=str.lower)) if lst else '_leeg_'}",
            f"• Vandaag: {', '.join(today) if today else 'n.v.t.'}",
            "• Week (manual): " + ", ".join(f\"{k}:{'/'.join(v)}\" for k, v in week.items()) if week else "• Week (manual): niet ingesteld",
        ]
        await ctx.send("\n".join(lines))

    # Handige diagnose
    @commands.command()
    @checks.admin()
    async def recalcfeatured(self, ctx: commands.Context):
        """(Admin) Bereken en cache 'featured today' meteen, en toon het resultaat."""
        today = await self._featured_today(ctx.guild)
        if today:
            await ctx.send(f"🎮 Featured today: {', '.join(today)}")
        else:
            await ctx.send("🎮 Featured today: _geen_ (controleer je gamelijst of modus)")

    # ----------------- OVERZICHT -------------------------------------------
    # M03#2.19 Overzicht
    @commands.command()
    async def boozysettings(self, ctx: commands.Context):
        """Toon huidige BoozyBank-instellingen (incl. games/featured & challenges)."""
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g.get("quiz_channel")) if g.get("quiz_channel") else None
        ach = ctx.guild.get_channel(g.get("announce_channel")) if g.get("announce_channel") else None
        excluded = [ctx.guild.get_channel(cid) for cid in g.get("excluded_channels", [])]
        exc_names = ", ".join(ch.mention for ch in excluded if ch) or "_geen_"

        raw_shop = (g.get("shop", {}) or {})
        shop_lines = [
            f"   - {k}: prijs {v.get('price',0)} | rol_id {v.get('role_id')}"
            for k, v in raw_shop.items()
        ] if raw_shop else ["   - _leeg_"]

        featured_mode = g.get("challenge_featured_mode", "auto")
        featured_count = g.get("challenge_featured_count", 2)
        featured_list = g.get("challenge_featured_list", []) or []
        featured_today = g.get("challenge_featured_today", []) or []
        reward_min = g.get("challenge_reward_min", 20)
        reward_max = g.get("challenge_reward_max", 60)

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
            f"• Debug: {'aan' if g.get('debug_quiz', False) else 'uit'}",
            f"• Testmodus (legacy): {'aan' if g.get('test_mode', False) else 'uit'}",
            "• **Rewards**:",
            f"   - Chat: +{g.get('chat_reward_amount',1)} / {g.get('chat_reward_cooldown_sec',300)}s",
            f"   - Voice: +{g.get('voice_reward_amount',1)} / {g.get('voice_reward_interval_sec',300)}s",
            f"   - Random drop: +{g.get('random_drop_amount',10)} per dag",
            f"   - Quiz eindreward: +{g.get('quiz_reward_amount',50)} | reset-uur (UTC): {g.get('quiz_reward_reset_hour',4)} | daily limit: {g.get('quiz_daily_limit',5)}",
            f"• LLM: model `{g.get('llm_model','gpt-5-nano')}`, timeout {g.get('llm_timeout',45)}s",
            "• **Shop**:",
        ]
        lines.extend(shop_lines)

        lines.extend([
            "• **Games/Featured**:",
            f"   - Game-lijst: {', '.join(sorted(featured_list, key=str.lower)) if featured_list else '_leeg_'}",
            f"   - Featured modus: {featured_mode} | auto-pick: {featured_count}",
            f"   - Featured vandaag: {', '.join(featured_today) if featured_today else '_n.v.t._'}",
            "• **Challenges**:",
            f"   - Auto-claim: {'aan' if g.get('challenge_auto_enabled', True) else 'uit'} | Daily count: {g.get('challenge_daily_count',4)} | Reset (UTC): {g.get('challenge_reset_hour',4)}:00",
            f"   - Reward-range (fallback/GPT clamp): {reward_min}..{reward_max}",
        ])

        await ctx.send("\n".join(lines))
