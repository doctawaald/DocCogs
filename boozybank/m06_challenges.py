# ============================
# m06_challenges.py
# ============================
from __future__ import annotations
import asyncio
from typing import Dict, List, Optional
import discord
from redbot.core import commands
from .m01_utils import (
    utc_ts, day_key_utc, cutoff_ts_at_hour_utc, seeded_daily_choice,
    scaled_reward_minutes, norm_game, short
)

class ChallengesMixin:
    # M06#1 INIT LOOP
    def __init__(self, *args, **kwargs):  # type: ignore
        super().__init__(*args, **kwargs)
        self._presence_sessions: Dict[int, Dict[int, dict]] = {}
        self._challenge_task = self.bot.loop.create_task(self._challenge_loop())

    def cog_unload(self):  # chained
        t = getattr(self, "_challenge_task", None)
        try:
            t and t.cancel()
        except Exception:
            pass

    # M06#2 PRESENCE
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or not after.guild:
            return
        # detect game name
        game = None
        for act in (after.activities or []):
            if str(getattr(act, "type", "")).lower().endswith("playing"):
                game = getattr(act, "name", None)
                break
        gid, uid = after.guild.id, after.id
        now = utc_ts()
        sess = self._presence_sessions.setdefault(gid, {})
        st = sess.get(uid) or {"game": None, "start": None}
        # flush prev
        if st.get("game") and st.get("start"):
            elapsed = max(0, now - st["start"])
            await self._accumulate(after.guild, after, st["game"], elapsed)
        # set new
        st["game"], st["start"] = (game, now) if game else (None, None)
        sess[uid] = st

    async def _accumulate(self, guild: discord.Guild, member: discord.Member, game: str, seconds: float):
        day = day_key_utc()
        async with self.config.user(member).all() as u:
            if u.get("challenge_day") != day:
                u["challenge_day"] = day
                u["challenge_total_secs"] = 0
                u["challenge_unique_games"] = []
                u["challenge_per_game"] = {}
                u["together_secs"] = 0
                u["together_game_secs"] = {}
            u["challenge_total_secs"] = int(u.get("challenge_total_secs",0) + int(seconds))
            per = u.get("challenge_per_game", {}) or {}
            per[game] = int(per.get(game,0) + int(seconds))
            u["challenge_per_game"] = per
            uniq = set(u.get("challenge_unique_games", []) or [])
            uniq.add(game)
            u["challenge_unique_games"] = list(uniq)

    # M06#3 DAILY SET
    async def _ensure_set(self, guild: discord.Guild):
        g = await self.config.guild(guild).all()
        reset_hour = int(g.get("challenge_reset_hour", 4))
        if float(g.get("challenge_set_ts", 0.0)) >= cutoff_ts_at_hour_utc(reset_hour) and (g.get("challenges_today") or []):
            return
        # featured game pick (optional)
        featured = g.get("challenge_featured_list") or []
        pick = seeded_daily_choice(featured, seed_extra=str(guild.id)) if featured else None
        # 4 challenges
        chs = []
        # 1) solo (beste sessie) — target 45 min
        chs.append({"type":"playtime_single","target":45,"reward":scaled_reward_minutes(45),"description":"Speel 45 min in één game vandaag"})
        # 2) group together — target 90 min (contribution-based)
        chs.append({"type":"community_total","target":90,"reward":scaled_reward_minutes(90),"description":"Speel samen 90 min vandaag"})
        # 3) unique — target 3 games
        chs.append({"type":"unique_games","target":3,"reward":scaled_reward_minutes(36),"description":"Speel 3 verschillende games vandaag"})
        # 4) specific featured game — 30 min
        if pick:
            chs.append({"type":"playtime_single_game","target":30,"reward":scaled_reward_minutes(30),"game":pick,"description":f"Speel 30 min in {short(pick,40)} vandaag"})
        else:
            chs.append({"type":"playtime_total","target":60,"reward":scaled_reward_minutes(60),"description":"Speel 60 min in totaal vandaag"})
        await self.config.guild(guild).challenges_today.set(chs)
        await self.config.guild(guild).challenge_set_ts.set(utc_ts())

    # M06#4 LOOP (contribution tick + autoclaim)
    async def _challenge_loop(self):
        await self.bot.wait_until_ready()
        TICK = 60
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    await self._ensure_set(guild)
                    await self._tick_contribution(guild, delta=TICK)
                    await self._autoclaim(guild)
            except Exception as e:
                print(f"[Boozy Challenges] {e}")
            await asyncio.sleep(TICK)

    async def _tick_contribution(self, guild: discord.Guild, *, delta: int):
        # per voice channel met >=2 humans → elke member +delta together_secs
        for vc in guild.voice_channels:
            humans = [m for m in vc.members if not m.bot]
            if len(humans) >= 2:
                for m in humans:
                    async with self.config.user(m).all() as u:
                        if u.get("challenge_day") != day_key_utc():
                            u["challenge_day"] = day_key_utc()
                            u["together_secs"] = 0
                            u["together_game_secs"] = {}
                        u["together_secs"] = int(u.get("together_secs",0) + delta)
                # same-game contribution (if presence says playing same)
                sess = self._presence_sessions.get(guild.id, {})
                game_counts: Dict[str, int] = {}
                for m in humans:
                    st = sess.get(m.id) or {}
                    gname = norm_game(st.get("game"))
                    if gname:
                        game_counts[gname] = game_counts.get(gname, 0) + 1
                for gname, cnt in game_counts.items():
                    if cnt >= 2:
                        for m in humans:
                            st = (sess.get(m.id) or {})
                            if norm_game(st.get("game")) == gname:
                                async with self.config.user(m).all() as u:
                                    tg = u.get("together_game_secs", {}) or {}
                                    tg[gname] = int(tg.get(gname,0) + delta)
                                    u["together_game_secs"] = tg

    async def _autoclaim(self, guild: discord.Guild):
        g = await self.config.guild(guild).all()
        chs = g.get("challenges_today") or []
        changed = False
        for ch in chs:
            t, target, reward = ch["type"], int(ch["target"]), int(ch["reward"])
            game = norm_game(ch.get("game"))
            for m in guild.members:
                if m.bot:
                    continue
                uid = str(m.id)
                if uid in ch.get("claimed_users", []):
                    continue
                u = await self.config.user(m).all()
                if u.get("challenge_day") != day_key_utc():
                    continue
                ok = False
                if t == "playtime_single":
                    per = u.get("challenge_per_game", {}) or {}
                    best = max([int(x) for x in per.values()], default=0) // 60
                    ok = best >= target
                elif t == "community_total":
                    ok = (int(u.get("together_secs",0)) // 60) >= target
                elif t == "unique_games":
                    ok = len(set(u.get("challenge_unique_games", []) or [])) >= target
                elif t == "playtime_single_game":
                    per = u.get("challenge_per_game", {}) or {}
                    ok = (int(per.get(game,0)) // 60) >= target
                elif t == "playtime_total":
                    ok = (int(u.get("challenge_total_secs",0)) // 60) >= target
                if ok:
                    newv = await self.add_booz(guild, m, reward, reason=f"Challenge: {ch['description']}")
                    ch.setdefault("claimed_users", []).append(uid)
                    changed = True
                    try:
                        await m.send(f"🏅 Challenge behaald: {ch['description']} → +{reward} Boo'z (saldo {newv})")
                    except Exception:
                        pass
        if changed:
            await self.config.guild(guild).challenges_today.set(chs)

    # M06#5 COMMANDS
    @commands.command(name="boozydailychallenges")
    async def boozydailychallenges(self, ctx: commands.Context):
        await self._ensure_set(ctx.guild)
        chs = await self.config.guild(ctx.guild).challenges_today()
        u = await self.config.user(ctx.author).all()
        total = int(u.get("challenge_total_secs",0)) // 60
        per = u.get("challenge_per_game", {}) or {}
        best_mins = max([int(x) for x in per.values()], default=0) // 60
        uniq = len(set(u.get("challenge_unique_games", []) or []))
        together = int(u.get("together_secs",0)) // 60
        tg = u.get("together_game_secs", {}) or {}
        lines = ["🔒 **Jouw challenges vandaag**"]
        for ch in chs:
            t, target, reward = ch["type"], int(ch["target"]), int(ch["reward"])
            claimed = (str(ctx.author.id) in ch.get("claimed_users", []))
            if t == "playtime_single":
                prog = f"{best_mins}/{target} min (beste sessie)"
            elif t == "community_total":
                prog = f"{together}/{target} min samen"
            elif t == "unique_games":
                prog = f"{uniq}/{target} games"
            elif t == "playtime_single_game":
                gname = ch.get("game")
                mins = int(per.get(gname or "",0)) // 60
                prog = f"{mins}/{target} min in {short(gname or 'deze game',30)}"
            else:
                prog = f"{total}/{target} min totaal"
            lines.append(f"• {'✅' if claimed else '▫️'} {ch['description']} — +{reward} — {prog}")
        try:
            await ctx.author.send("\n".join(lines))
            await ctx.send("✅ Check je DM’s voor jouw challenges.")
        except Exception:
            await ctx.send("❌ Ik kan je geen DM sturen.")
        await self._autoclaim(ctx.guild)

    @commands.command(name="boozychallenges")
    async def boozychallenges(self, ctx: commands.Context):
        await self.boozydailychallenges(ctx)

    @commands.command(name="refreshchallenges")
    @commands.has_permissions(administrator=True)
    async def refreshchallenges(self, ctx
