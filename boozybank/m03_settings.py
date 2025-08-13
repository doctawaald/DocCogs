# [03] SETTINGS — kanalen/exclusions + rewards/interval + LLM + shop + toggles + Games/Featured

import discord
from redbot.core import checks, commands


class SettingsMixin:
    # ---------- Kanaal & exclusions ----------
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

    # ---------- Rewards & timing ----------
    @commands.command()
    @checks.admin()
    async def setchatreward(self, ctx: commands.Context, amount: int, cooldown_sec: int):
        """Stel chat reward in: !setchatreward <amount> <cooldown_sec>"""
        await self.config.guild(ctx.guild).chat_reward_amount.set(max(0, amount))
        await self.config.guild(ctx.guild).chat_reward_cooldown_sec.set(max(0, cooldown_sec))
        await ctx.send(f"💬 Chat: +{max(0,amount)} per {max(0,cooldown_sec)}s")

    @commands.command()
    @checks.admin()
    async def setvoicereward(self, ctx: commands.Context, amount: int, interval_sec: int):
        """Stel voice reward in: !setvoicereward <amount> <interval_sec>"""
        await self.config.guild(ctx.guild).voice_reward_amount.set(max(0, amount))
        await self.config.guild(ctx.guild).voice_reward_interval_sec.set(max(0, interval_sec))
        await ctx.send(f"🎙️ Voice: +{max(0,amount)} per {max(0,interval_sec)}s")

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
    async def setquizlimit(self, ctx: commands.Context, limit: int):
        """Max belonende quizzes per dag per user: !setquizlimit <n>"""
        await self.config.guild(ctx.guild).quiz_daily_limit.set(max(0, limit))
        await ctx.send(f"🚦 Quiz daily limit: **{max(0, limit)}**")

    @commands.command()
    @checks.admin()
    async def setquizresethour(self, ctx: commands.Context, hour_utc: int):
        """Stel dagelijkse reset-uur (UTC) in: !setquizresethour <0-23>"""
        hour = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).quiz_reward_reset_hour.set(hour)
        await ctx.send(f"⏰ Reset-uur gezet op {hour}:00 UTC")

    # ---------- Systeem toggles ----------
    @commands.command()
    @checks.admin()
    async def setautoclean(self, ctx: commands.Context, status: str):
        """Zet quiz auto-clean aan/uit: !setautoclean on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).quiz_autoclean.set(on)
        await ctx.send(f"🧹 Auto-clean is **{'aan' if on else 'uit'}**.")

    @commands.command()
    @checks.admin()
    async def setcleandelay(self, ctx: commands.Context, seconds: int):
        """Stel cleanup delay in seconden: !setcleandelay <s>"""
        s = max(0, int(seconds))
        await self.config.guild(ctx.guild).quiz_clean_delay.set(s)
        await ctx.send(f"⏳ Cleanup delay: **{s}s**")

    @commands.command()
    @checks.admin()
    async def setminvc(self, ctx: commands.Context, n: int):
        """Minimum #humans in VC voor rewards/quiz/drop: !setminvc <n>"""
        n = max(0, int(n))
        await self.config.guild(ctx.guild).min_vc_humans.set(n)
        await ctx.send(f"👥 Min. VC-humans: **{n}**")

    @commands.command()
    @checks.admin()
    async def setautoquiz(self, ctx: commands.Context, status: str):
        """Zet auto-quiz (dagelijks) aan/uit: !setautoquiz on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).auto_quiz_enabled.set(on)
        await ctx.send(f"🤖 Auto-quiz is **{'aan' if on else 'uit'}**.")

    @commands.command()
    @checks.admin()
    async def setafkignore(self, ctx: commands.Context, status: str):
        """Negeer AFK-kanaal voor VC-dingen: !setafkignore on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).afk_excluded.set(on)
        await ctx.send(f"😴 AFK-kanaal negeren: **{'aan' if on else 'uit'}**")

    @commands.command()
    @checks.admin()
    async def setselfmuteignore(self, ctx: commands.Context, status: str):
        """Sluit self-mute/deaf users uit voor voice-rewards: !setselfmuteignore on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).self_mute_excluded.set(on)
        await ctx.send(f"🔇 Self-mute/deaf uitsluiten: **{'aan' if on else 'uit'}**")

    @commands.command()
    @checks.admin()
    async def settestmode(self, ctx: commands.Context, status: str):
        """Zet testmodus (bypass VC-minimum voor vaste test-ID, zonder rewards): !settestmode on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).test_mode.set(on)
        await ctx.send(f"🧪 Testmodus is **{'aan' if on else 'uit'}**.")

    # ---------- LLM settings ----------
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

    @commands.command()
    @checks.admin()
    async def boozydebug(self, ctx: commands.Context, status: str):
        """Zet quiz debug aan/uit. Voorbeeld: !boozydebug on/off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).debug_quiz.set(on)
        await ctx.send(f"🔍 Debug is **{'aan' if on else 'uit'}**.")

    # ---------- Shop beheer ----------
    @commands.command()
    @checks.admin()
    async def setshopprice(self, ctx: commands.Context, key: str, price: int):
        """Zet prijs voor shop-item (bv. soundboard_access): !setshopprice <key> <price>"""
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
        """Koppel een rol aan een shop-item: !setshoprole <key> <@rol>"""
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
        """Voeg een shop-item toe (zonder rol): !addshopitem <key> [price]"""
        key = key.lower().strip()
        async with self.config.guild(ctx.guild).shop() as shop:
            shop[key] = {"price": max(0, price), "role_id": None}
        await ctx.send(f"🆕 Item **{key}** toegevoegd met prijs **{max(0,price)}** Boo'z.")

    @commands.command()
    @checks.admin()
    async def removeshopitem(self, ctx: commands.Context, key: str):
        """Verwijder een shop-item: !removeshopitem <key>"""
        key = key.lower().strip()
        async with self.config.guild(ctx.guild).shop() as shop:
            if key in shop:
                del shop[key]
                await ctx.send(f"🗑️ Item **{key}** verwijderd.")
            else:
                await ctx.send("❌ Dat item bestaat niet.")

    # ---------- Games/Featured (nieuwe alias-commands) ----------
    # Deze werken op dezelfde pool als de Featured auto-lijst die de challenges gebruikt.
    @commands.command(name="addgame")
    @checks.admin()
    async def addgame(self, ctx: commands.Context, *, game: str):
        """Voeg een game toe aan de game-lijst (gebruikt voor Featured/Challenges)."""
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
        """Overschrijf de game-lijst (komma-gescheiden). Voorbeeld: !setgamelist Fortnite, Rocket League, REPO"""
        names = [g.strip() for g in games_csv.split(",") if g.strip()]
        names = sorted(list(dict.fromkeys(names)), key=str.lower)  # uniek + sort
        await self.config.guild(ctx.guild).challenge_featured_list.set(names)
        await ctx.send(f"🗂️ Game-lijst ingesteld: {', '.join(names) if names else '_leeg_'}")

    @commands.command()
    async def listgames(self, ctx: commands.Context):
        """Toon de huidige game-lijst (auto-pool voor Featured/Challenges)."""
        lst = await self.config.guild(ctx.guild).challenge_featured_list()
        await ctx.send(f"🎮 Games: {', '.join(sorted(lst, key=str.lower)) if lst else '_leeg_'}")

    # ---------- Featured Games (bestaande beheerscommando's) ----------
    @commands.command()
    @checks.admin()
    async def addfeatured(self, ctx: commands.Context, *, game: str):
        """Voeg een game toe aan de featured-lijst (auto-modus gebruikt hieruit)."""
        game = game.strip()
        async with self.config.guild(ctx.guild).challenge_featured_list() as lst:
            if game not in lst:
                lst.append(game)
        await ctx.send(f"✅ Featured +: **{game}**")

    @commands.command()
    @checks.admin()
    async def rmfeatured(self, ctx: commands.Context, *, game: str):
        """Verwijder een game uit de featured-lijst."""
        game = game.strip()
        async with self.config.guild(ctx.guild).challenge_featured_list() as lst:
            if game in lst:
                lst.remove(game)
        await ctx.send(f"✅ Featured −: **{game}**")

    @commands.command()
    async def listfeatured(self, ctx: commands.Context):
        """Toon de featured-lijst en de ingestelde modus."""
        g = await self.config.guild(ctx.guild).all()
        mode = g.get("challenge_featured_mode", "auto")
        cnt = g.get("challenge_featured_count", 2)
        lst = g.get("challenge_featured_list", []) or []
        week = g.get("challenge_featured_week", {}) or {}
        today = g.get("challenge_featured_today", []) or []
        lines = [
            f"🗂️ Featured modus: **{mode}** (auto-pick count: {cnt})",
            f"• Lijst: {', '.join(sorted(lst, key=str.lower)) if lst else '_leeg_'}",
            f"• Vandaag: {', '.join(today) if today else '_n.v.t._'}",
            "• Week (manual): " + ", ".join(f"{k}:{'/'.join(v)}" for k, v in week.items()) if week else "• Week (manual): _niet ingesteld_",
        ]
        await ctx.send("\n".join(lines))

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
        Weekdagen: mon,tue,wed,thu,fri,sat,sun
        """
        wk = weekday.lower()[:3]
        if wk not in {"mon","tue","wed","thu","fri","sat","sun"}:
            return await ctx.send("❌ Weekdag moet zijn: mon,tue,wed,thu,fri,sat,sun")
        games = [g.strip() for g in games_csv.split(",") if g.strip()]
        async with self.config.guild(ctx.guild).challenge_featured_week() as week:
            week[wk] = games
        await ctx.send(f"📅 {wk}: {', '.join(games) if games else '_leeg_'}")

    # ---------- Challenge toggles ----------
    @commands.command()
    @checks.admin()
    async def setchallengeauto(self, ctx: commands.Context, status: str):
        """Auto-claim aan/uit: !setchallengeauto on/off"""
        on = status.lower() in ("on", "aan", "yes", "true", "1")
        await self.config.guild(ctx.guild).challenge_auto_enabled.set(on)
        await ctx.send(f"⚙️ Challenge auto-claim: **{'aan' if on else 'uit'}**")

    @commands.command()
    @checks.admin()
    async def setchallengecount(self, ctx: commands.Context, n: int):
        """Aantal dagelijkse challenges (1-5): !setchallengecount <n>"""
        n = min(5, max(1, int(n)))
        await self.config.guild(ctx.guild).challenge_daily_count.set(n)
        await ctx.send(f"🧮 Dagelijkse challenges: **{n}** (nieuwe set vanaf volgende reset of `!regenchallenges`)")

    @commands.command()
    @checks.admin()
    async def setchallengereward(self, ctx: commands.Context, min_amount: int, max_amount: int):
        """Range voor fallback-beloningen: !setchallengereward <min> <max>"""
        a = max(1, int(min_amount))
        b = max(a, int(max_amount))
        await self.config.guild(ctx.guild).challenge_reward_min.set(a)
        await self.config.guild(ctx.guild).challenge_reward_max.set(b)
        await ctx.send(f"💰 Challenge fallback rewards: **{a}..{b}** Boo'z")

    @commands.command()
    @checks.admin()
    async def setchallengeresethour(self, ctx: commands.Context, hour_utc: int):
        """Dagelijkse challenge reset-uur (UTC): !setchallengeresethour <0-23>"""
        h = min(23, max(0, int(hour_utc)))
        await self.config.guild(ctx.guild).challenge_reset_hour.set(h)
        await ctx.send(f"⏰ Challenge reset-uur: **{h}:00 UTC**")

    # ---------- Overzicht ----------
    @commands.command()
    async def boozysettings(self, ctx: commands.Context):
        """Toon huidige BoozyBank-instellingen (incl. games/featured & challenges)."""
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g.get("quiz_channel")) if g.get("quiz_channel") else None
        excluded = [ctx.guild.get_channel(cid) for cid in g.get("excluded_channels", [])]
        exc_names = ", ".join(ch.mention for ch in excluded if ch) or "_geen_"

        # Shop-regels
        raw_shop = (g.get("shop", {}) or {})
        if raw_shop:
            shop_lines = [
                f"   - {k}: prijs {v.get('price',0)} | rol_id {v.get('role_id')}"
                for k, v in raw_shop.items()
            ]
        else:
            shop_lines = ["   - _leeg_"]

        # Featured/Challenges
        featured_mode = g.get("challenge_featured_mode", "auto")
        featured_count = g.get("challenge_featured_count", 2)
        featured_list = g.get("challenge_featured_list", []) or []
        featured_today = g.get("challenge_featured_today", []) or []
        reward_min = g.get("challenge_reward_min", 25)
        reward_max = g.get("challenge_reward_max", 100)

        lines = [
            "🛠 **Boozy settings**",
            f"• Quizkanaal: {qch.mention if qch else '_niet ingesteld_'}",
            f"• Excluded: {exc_names}",
            f"• Auto-clean: {'aan' if g.get('quiz_autoclean', True) else 'uit'} (delay {g.get('quiz_clean_delay',5)}s)",
            f"• Min. VC-humans: {g.get('min_vc_humans',3)}",
            f"• Auto-quiz: {'aan' if g.get('auto_quiz_enabled', True) else 'uit'}",
            f"• AFK negeren: {'aan' if g.get('afk_excluded', True) else 'uit'}",
            f"• Self-mute/deaf uitsluiten: {'aan' if g.get('self_mute_excluded', False) else 'uit'}",
            f"• Debug: {'aan' if g.get('debug_quiz', False) else 'uit'}",
            f"• Testmodus: {'aan' if g.get('test_mode', False) else 'uit'}",
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
            f"   - Auto-claim: {'aan' if g.get('challenge_auto_enabled', True) else 'uit'} | Daily count: {g.get('challenge_daily_count',3)} | Reset (UTC): {g.get('challenge_reset_hour',4)}:00",
            f"   - Fallback reward-range: {reward_min}..{reward_max}",
        ])

        await ctx.send("\n".join(lines))
