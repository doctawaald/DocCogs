# [06] CHALLENGES — 5 per dag, exact 1 game-challenge (indien mogelijk),
# rewards 20..60, presence tracking, auto-claim, announce channel, nette beschrijvingen,
# + !boozychallenges + !refreshchallenges (+ alias !regenchallenges)

import asyncio
import datetime
import json
import random
import re
from typing import Dict, List, Optional

import aiohttp
import discord
from aiohttp import ClientTimeout
from redbot.core import commands


# --------- kleine helpers ---------
def _utc_ts() -> float:
    return datetime.datetime.utcnow().timestamp()

def _day_key_utc() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def _cutoff_ts_at_hour_utc(hour: int) -> float:
    now = datetime.datetime.utcnow()
    tgt = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if now < tgt:
        tgt -= datetime.timedelta(days=1)
    return tgt.timestamp()

def _weekday_key_utc() -> str:
    # mon..sun
    idx = datetime.datetime.utcnow().weekday()  # 0=Mon
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][idx]

def _short_game(name: Optional[str]) -> str:
    n = (name or "").strip()
    return n if len(n) <= 40 else (n[:37] + "…")

def _norm_game(name: str) -> str:
    return (name or "").strip()

def _nice_desc(ctype: str, target: int, game: str | None = None) -> str:
    game = _norm_game(game or "")
    if ctype == "playtime_total":
        return f"Speel in totaal {target} min vandaag"
    if ctype == "playtime_single":
        return f"Speel {target} min in één game vandaag"
    if ctype == "unique_games":
        return f"Speel {target} verschillende games vandaag"
    if ctype == "playtime_single_game":
        g = game or "deze game"
        return f"Speel {target} min in {g} vandaag"
    if ctype == "community_total":
        return f"Speel samen {target} min vandaag"
    if ctype == "community_game_total":
        g = game or "deze game"
        return f"Speel samen {target} min in {g} vandaag"
    return "Voltooi de uitdaging van vandaag"


class ChallengesMixin:
    """
    Challenge types:
      - playtime_single         (X min in één willekeurige game — NIET featured-gebonden)
      - playtime_total          (X min totaal, alle games — NIET featured-gebonden)
      - unique_games            (X verschillende games — NIET featured-gebonden)
      - playtime_single_game    (X min in *specifieke* game — FEATURED)
      - community_total         (server-breed X min totaal — NIET featured-gebonden)
      - community_game_total    (server-breed X min in *specifieke* game — FEATURED)
    """

    # ------------------ Presence tracking ------------------
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or not after.guild:
            return

        # vind "playing" activiteit
        cur_game = None
        if after.activities:
            for act in after.activities:
                if getattr(act, "type", None) and str(act.type).lower().endswith("playing"):
                    cur_game = getattr(act, "name", None)
                    break

        uid = after.id
        gid = after.guild.id
        now = _utc_ts()

        sess = self._presence_sessions.setdefault(gid, {})
        ustate = sess.get(uid)
        if ustate is None:
            ustate = {"game": None, "start": None}
            sess[uid] = ustate

        prev_game = ustate["game"]
        start = ustate["start"]

        # sluit vorige sessie af
        if prev_game and start:
            elapsed = max(0, now - start)
            await self._accumulate_playtime(after.guild, after, prev_game, elapsed)

        # start nieuwe/clear
        if cur_game:
            ustate["game"] = cur_game
            ustate["start"] = now
        else:
            ustate["game"] = None
            ustate["start"] = None

        # snelle auto-claim
        await self._challenge_autoclaim_tick(after.guild)

    async def _accumulate_playtime(self, guild: discord.Guild, member: discord.Member, game: str, seconds: float):
        day = _day_key_utc()
        # User-level
        async with self.config.user(member).all() as u:
            d = u.get("challenge_day", day)
            if d != day:
                u["challenge_day"] = day
                u["challenge_total_secs"] = 0
                u["challenge_unique_games"] = []
                u["challenge_per_game"] = {}
            u["challenge_total_secs"] = int(u.get("challenge_total_secs", 0) + int(seconds))
            per = u.get("challenge_per_game", {}) or {}
            per[game] = int(per.get(game, 0) + int(seconds))
            u["challenge_per_game"] = per
            uniq = set(u.get("challenge_unique_games", []) or [])
            uniq.add(game)
            u["challenge_unique_games"] = list(uniq)

        # Guild-level (server totals)
        async with self.config.guild(guild).all() as g:
            d = g.get("challenge_day", day)
            if d != day:
                g["challenge_day"] = day
                g["challenge_server_total_secs"] = 0
                g["challenge_samegame_clock"] = {}
            g["challenge_server_total_secs"] = int(g.get("challenge_server_total_secs", 0) + int(seconds))
            sg = g.get("challenge_samegame_clock", {}) or {}
            sg[game] = int(sg.get(game, 0) + int(seconds))
            g["challenge_samegame_clock"] = sg

    # ------------------ Featured games logica ------------------
    async def _featured_today(self, guild: discord.Guild) -> List[str]:
        g = await self.config.guild(guild).all()
        mode = (g.get("challenge_featured_mode") or "auto").lower()
        day = _day_key_utc()

        # cache geldig?
        if g.get("challenge_featured_cache_day") == day:
            return g.get("challenge_featured_today") or []

        today_list: List[str] = []
        if mode == "manual":
            week = g.get("challenge_featured_week", {}) or {}
            wk = _weekday_key_utc()
            today_list = [_norm_game(x) for x in (week.get(wk) or [])]
        else:
            base = [_norm_game(x) for x in (g.get("challenge_featured_list") or []) if _norm_game(x)]
            cnt = int(g.get("challenge_featured_count", 2))
            if base:
                # deterministisch random per dag/server
                rnd = random.Random(day + str(guild.id))
                rnd.shuffle(base)
                today_list = base[:max(1, min(cnt, len(base)))]

        await self.config.guild(guild).challenge_featured_today.set(today_list)
        await self.config.guild(guild).challenge_featured_cache_day.set(day)
        return today_list

    # ------------------ LLM generatie ------------------
    async def _get_api_key(self) -> Optional[str]:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    async def _llm_generate_challenges(
        self, guild: discord.Guild, *, count: int, model: str, timeout: int, require_one_game: bool
    ) -> List[dict]:
        """
        Verwacht JSON-array van challenges:
        [{type, target, reward, description, game?}]
        type in:
          'playtime_single','playtime_total','unique_games','community_total',
          'playtime_single_game','community_game_total'
        Voor *_game types MOET 'game' aanwezig zijn en behoren tot 'featured today'.
        """
        api_key = await self._get_api_key()
        if not api_key:
            return []

        featured = await self._featured_today(guild)
        featured_str = ", ".join(f"'{x}'" for x in featured) if featured else ""

        # Reward-range expliciet 20..60 met precies 1 game challenge als het kan
        prompt = (
            "Genereer {count} Discord challenges in JSON (alleen JSON). "
            "Elke challenge: "
            "{type: one of ['playtime_single','playtime_total','unique_games','community_total','playtime_single_game','community_game_total'], "
            " target: integer (minutes for playtime/community, count for unique_games), "
            " reward: integer Boo'z (20..60), "
            " description: korte NL achievement-achtige zin (max 120 tekens), "
            " game?: string (vereist voor *_game types en MOET in featured lijst zitten). } "
            "Regels: maak PRECIES 1 challenge met *_game (alleen als featured lijst niet leeg is) en de overige {rest} challenges zonder *_game. "
            f"Featured today: [{featured_str}]. "
            "Focus op lichte, haalbare doelen voor kleine communities."
        ).replace("{count}", str(count)).replace("{rest}", str(max(0, count-1)))

        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as sess:
                payload = {
                    "model": model,
                    "messages": [{"role": "user", "content": prompt}],
                }
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                    },
                ) as r:
                    status = r.status
                    data = await r.json()
        except Exception as e:
            print(f"[BoozyBank] CHALL LLM network error: {e}")
            return []

        if status != 200:
            print(f"[BoozyBank] CHALL LLM HTTP {status}: {data}")
            return []

        content = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        m = re.search(r"\[\s*\{.*\}\s*\]", content, re.DOTALL)
        if not m:
            return []
        try:
            featured_set = set(featured)
            arr = json.loads(m.group(0))
            if not isinstance(arr, list):
                return []
            out = []
            for ch in arr:
                t = str(ch.get("type", ""))
                if t not in {
                    "playtime_single", "playtime_total", "unique_games", "community_total",
                    "playtime_single_game", "community_game_total"
                }:
                    continue
                target = int(ch.get("target", 0))
                reward = max(20, min(60, int(ch.get("reward", 20))))  # clamp 20..60
                game = _norm_game(ch.get("game", "")) if "game" in ch else ""
                if target <= 0:
                    continue
                if t.endswith("_game"):
                    if not featured or not game or game not in featured_set:
                        # ongeldig game-item
                        continue
                # beschrijving altijd netjes maken
                desc = _nice_desc(t, target, game)
                item = {"type": t, "target": target, "reward": reward, "description": desc}
                if game:
                    item["game"] = game
                out.append(item)

            # post-constraint: precies 1 *_game (als featured bestaat)
            game_items = [x for x in out if x["type"].endswith("_game")]
            non_game_items = [x for x in out if not x["type"].endswith("_game")]

            if featured and require_one_game:
                # we willen exact 1 game
                if len(game_items) == 0:
                    # later vullen via fallback
                    pass
                elif len(game_items) > 1:
                    # hou er 1, rest naar non_game (verwijderen en straks aanvullen)
                    game_items = game_items[:1]
            else:
                # geen featured of we willen geen game challenge
                game_items = []

            combined = game_items + non_game_items
            return combined[:count]
        except Exception:
            return []
        return []

    # ------------------ Fallback bouwers ------------------
    def _fallback_generic(self) -> List[dict]:
        # generieke simpele doelen; descriptions via _nice_desc
        return [
            {"type": "playtime_total", "target": 60},
            {"type": "unique_games",   "target": 3},
            {"type": "playtime_single","target": 30},
            {"type": "community_total","target": 180},
            {"type": "playtime_total", "target": 90},
            {"type": "unique_games",   "target": 4},
        ]

    def _fallback_game_for(self, game: str) -> dict:
        # 30 min specifieke game
        return {"type": "playtime_single_game", "target": 30, "game": game}

    def _decorate_rewards_and_desc(self, items: List[dict]) -> List[dict]:
        rnd = random.Random(_day_key_utc())
        out = []
        for ch in items:
            t = ch["type"]
            target = int(ch["target"])
            game = ch.get("game")
            reward = int(ch.get("reward", rnd.randint(20, 60)))
            reward = max(20, min(60, reward))
            desc = _nice_desc(t, target, game)
            item = {"type": t, "target": target, "reward": reward, "description": desc}
            if game:
                item["game"] = _norm_game(game)
            out.append(item)
        return out

    # ------------------ Challenge set beheer ------------------
    async def _ensure_challenge_set(self, guild: discord.Guild) -> None:
        """
        Forceer precies 5 challenges, waarvan exact 1 game-challenge als featured today beschikbaar is.
        """
        g = await self.config.guild(guild).all()
        reset_hour = int(g.get("challenge_reset_hour", 4))
        cutoff = _cutoff_ts_at_hour_utc(reset_hour)
        current_set_ts = float(g.get("challenge_set_ts", 0.0))
        desired_count = 5  # expliciet gevraagd

        # al een set en nog geldig?
        existing = g.get("challenges_today") or []
        if current_set_ts >= cutoff and len(existing) == desired_count:
            return

        featured_today = await self._featured_today(guild)
        have_featured = bool(featured_today)

        # LLM poging met constraint
        model = g.get("llm_model", "gpt-5-nano")
        timeout = int(g.get("llm_timeout", 45))
        llm = await self._llm_generate_challenges(
            guild, count=desired_count, model=model, timeout=timeout, require_one_game=have_featured
        )

        # splits resultaat
        game_items = [x for x in llm if x["type"].endswith("_game")]
        non_game_items = [x for x in llm if not x["type"].endswith("_game")]

        rnd = random.Random(_day_key_utc() + str(guild.id))

        # Garandeer exact 1 game item als we featured hebben
        ensured_game: List[dict] = []
        if have_featured:
            if len(game_items) >= 1:
                ensured_game = [game_items[0]]
            else:
                # maak fallback game
                game = rnd.choice(featured_today)
                ensured_game = [self._fallback_game_for(game)]
        else:
            # geen featured -> 0 game items
            ensured_game = []

        # Vul generics aan tot 5
        needed_generics = desired_count - len(ensured_game)
        gen_pool = non_game_items.copy()
        if len(gen_pool) < needed_generics:
            # aanvullen met fallback generics
            fb = self._fallback_generic()
            rnd.shuffle(fb)
            gen_pool.extend(fb)
        gen_pool = gen_pool[:needed_generics]

        # combineer en decoreer
        newset_raw = ensured_game + gen_pool
        newset = self._decorate_rewards_and_desc(newset_raw)

        # id's + init fields
        now = _utc_ts()
        final = []
        for i, ch in enumerate(newset, start=1):
            item = {
                "id": f"{_day_key_utc()}-{i}",
                "type": ch["type"],
                "target": int(ch["target"]),
                "reward": int(ch["reward"]),
                "description": ch["description"],
                "claimed_users": [],
                "claimed_done": False,
            }
            if "game" in ch:
                item["game"] = _norm_game(ch["game"])
            final.append(item)

        await self.config.guild(guild).challenges_today.set(final)
        await self.config.guild(guild).challenge_set_ts.set(now)

    # ------------------ Auto-claim ------------------
    async def _challenge_autoclaim_tick(self, guild: discord.Guild):
        g = await self.config.guild(guild).all()
        if not bool(g.get("challenge_auto_enabled", True)):
            return

        await self._ensure_challenge_set(guild)
        chs = await self.config.guild(guild).challenges_today() or []
        changed = False

        server_total_secs = int(g.get("challenge_server_total_secs", 0))
        same_clock = g.get("challenge_samegame_clock", {}) or {}

        for ch in chs:
            ctype = ch["type"]
            target = int(ch["target"])
            reward = int(ch["reward"])
            game = _norm_game(ch.get("game", ""))

            # community types
            if ctype == "community_total":
                if ch.get("claimed_done"):
                    continue
                mins = server_total_secs // 60
                if mins >= target:
                    ch["claimed_done"] = True
                    changed = True
                    await self._announce(guild, f"🎯 Community challenge gehaald: **{ch['description']}** — mooi bezig!")
                continue

            if ctype == "community_game_total":
                if ch.get("claimed_done"):
                    continue
                mins = int(same_clock.get(game, 0)) // 60
                if mins >= target:
                    ch["claimed_done"] = True
                    changed = True
                    pretty = _short_game(game) or "deze game"
                    await self._announce(guild, f"🎯 Community challenge gehaald (game): **{pretty}** — nice!")

            # per-user challenges
            for m in guild.members:
                if m.bot:
                    continue
                uid = str(m.id)
                if uid in ch.get("claimed_users", []):
                    continue
                u = await self.config.user(m).all()
                if u.get("challenge_day") != _day_key_utc():
                    continue

                if ctype == "playtime_total":
                    if int(u.get("challenge_total_secs", 0)) // 60 >= target:
                        await self._reward_user(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "unique_games":
                    uniq = set(u.get("challenge_unique_games", []) or [])
                    if len(uniq) >= target:
                        await self._reward_user(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "playtime_single":
                    per = u.get("challenge_per_game", {}) or {}
                    best = 0
                    for secs in per.values():
                        if secs > best:
                            best = int(secs)
                    if best // 60 >= target:
                        await self._reward_user(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "playtime_single_game":
                    per = u.get("challenge_per_game", {}) or {}
                    secs = int(per.get(game, 0))
                    if secs // 60 >= target:
                        pretty = _short_game(game) or "deze game"
                        await self._reward_user(m, reward, reason=f"Speel {target} min in {pretty} vandaag")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

        if changed:
            await self.config.guild(guild).challenges_today.set(chs)

    async def _reward_user(self, member: discord.Member, amount: int, *, reason: str):
        bal = await self.config.user(member).booz()
        await self.config.user(member).booz.set(int(bal) + int(amount))
        try:
            ch = await self._get_announce_channel(member.guild)
            if ch and ch.permissions_for(member.guild.me).send_messages:
                await ch.send(f"🏅 {member.mention} voltooide een challenge: **{reason}** → +{amount} Boo'z")
        except Exception:
            pass

    async def _get_announce_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        ch_id = await self.config.guild(guild).announce_channel()
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        # fallback
        return guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    async def _announce(self, guild: discord.Guild, text: str):
        try:
            ch = await self._get_announce_channel(guild)
            if ch:
                await ch.send(text)
        except Exception:
            pass

    # ------------------ Commands ------------------
    @commands.command(name="boozychallenges")
    async def boozychallenges(self, ctx: commands.Context):
        """Toon de challenges van vandaag, je voortgang en de 'featured games' van vandaag."""
        await self._ensure_challenge_set(ctx.guild)
        g = await self.config.guild(ctx.guild).all()
        chs = await self.config.guild(ctx.guild).challenges_today() or []
        featured = await self._featured_today(ctx.guild)

        u = await self.config.user(ctx.author).all()
        total = int(u.get("challenge_total_secs", 0)) // 60
        per = u.get("challenge_per_game", {}) or {}
        best = 0
        best_game = "-"
        for name, secs in per.items():
            if secs > best:
                best = int(secs)
                best_game = name
        best_mins = best // 60
        uniq = len(set(u.get("challenge_unique_games", []) or []))

        lines = [
            f"🎯 **Challenges vandaag** (auto-claim: {'aan' if g.get('challenge_auto_enabled', True) else 'uit'})",
            f"🎮 Featured: {', '.join(map(_short_game, featured)) if featured else '_geen ingesteld_'}"
        ]
        if not chs:
            lines.append("_Nog geen challenges — admin kan `!refreshchallenges` doen._")
        for ch in chs:
            ctype = ch["type"]
            target = int(ch["target"])
            reward = int(ch["reward"])
            game = ch.get("game")
            claimed = (str(ctx.author.id) in ch.get("claimed_users", [])) or (ctype.startswith("community") and ch.get("claimed_done"))
            if ctype == "playtime_single":
                prog = f"{best_mins}/{target} min (beste game: {_short_game(best_game)})"
            elif ctype == "playtime_total":
                prog = f"{total}/{target} min"
            elif ctype == "unique_games":
                prog = f"{uniq}/{target} games"
            elif ctype == "playtime_single_game":
                mins = int(per.get(game, 0)) // 60
                prog = f"{mins}/{target} min in {_short_game(game)}"
            elif ctype == "community_game_total":
                mins = int(g.get('challenge_samegame_clock', {}).get(game, 0)) // 60
                prog = f"server: {mins}/{target} min in {_short_game(game)}"
            else:  # community_total
                mins = int(g.get('challenge_server_total_secs', 0)) // 60
                prog = f"server: {mins}/{target} min"
            lines.append(f"• {'✅' if claimed else '▫️'} **{ch['description']}** — 🎁 {reward} — {prog}")

        await ctx.send("\n".join(lines))
        await self._challenge_autoclaim_tick(ctx.guild)

    @commands.command(name="refreshchallenges")
    @commands.has_permissions(administrator=True)
    async def refreshchallenges(self, ctx: commands.Context):
        """(Admin) Verwijder en regenereer de challenges van vandaag (5 per dag, 1 game)."""
        await self.config.guild(ctx.guild).challenge_set_ts.set(0.0)
        await self.config.guild(ctx.guild).challenges_today.set([])
        await self._ensure_challenge_set(ctx.guild)
        await ctx.send("🔁 Challenges opnieuw gegenereerd voor vandaag.")
        await self._challenge_autoclaim_tick(ctx.guild)

    # legacy alias, handig tijdens testen
    @commands.command(name="regenchallenges")
    @commands.has_permissions(administrator=True)
    async def regenchallenges(self, ctx: commands.Context):
        """Alias van !refreshchallenges (admin)."""
        await self.refreshchallenges(ctx)

    # -------------- Background loop --------------
    async def _challenge_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    # presence sessies die lopen: elke 2 min tick
                    now = _utc_ts()
                    sess = self._presence_sessions.get(guild.id, {})
                    for uid, state in list(sess.items()):
                        game = state.get("game")
                        start = state.get("start")
                        if game and start and (now - start) >= 120:
                            member = guild.get_member(int(uid))
                            if member:
                                await self._accumulate_playtime(guild, member, game, 120)
                                state["start"] = now
                    # auto-claim check
                    await self._challenge_autoclaim_tick(guild)
            except Exception as e:
                print(f"[BoozyBank Challenges] loop error: {e}")
            await asyncio.sleep(120)
