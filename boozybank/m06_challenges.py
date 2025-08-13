# M06 --- CHALLENGES --------------------------------------------------------
# 4/dag, precies 1 game-challenge (als featured beschikbaar), geen duplicate
# categorieën, rewards 20..60, presence tracking, auto-claim,
# DM-uitvoer & DM-beloning, announce voor community, featured-fix.
# ---------------------------------------------------------------------------

# M06#1 IMPORTS & CONSTANTS
from __future__ import annotations
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

GENERIC_TYPES = ("playtime_single","playtime_total","unique_games","community_total")
GAME_TYPES    = ("playtime_single_game","community_game_total")

DEFAULT_TARGETS = {
    "playtime_single": 45,
    "playtime_total": 120,
    "unique_games": 3,
    "community_total": 90,
    "playtime_single_game": 30,
    "community_game_total": 120,
}

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
    return ["mon","tue","wed","thu","fri","sat","sun"][datetime.datetime.utcnow().weekday()]

def _short_game(name: Optional[str]) -> str:
    n = (name or "").strip()
    return n if len(n) <= 40 else (n[:37] + "…")

def _norm_game(name: str) -> str:
    return (name or "").strip()

def _clamp_reward(x: int) -> int:
    # TODO (volgende update): afronden naar veelvoud van 5
    return max(20, min(60, int(x)))

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


# M06#2 MIXIN
class ChallengesMixin:
    """Presence-based challenges & featured games."""

    # ---------------- PRESENCE TRACKING ------------------------------------
    # M06#2.1 presence updates
    @commands.Cog.listener()
    async def on_presence_update(self, before: discord.Member, after: discord.Member):
        if after.bot or not after.guild:
            return

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

        if prev_game and start:
            elapsed = max(0, now - start)
            await self._accumulate_playtime(after.guild, after, prev_game, elapsed)

        if cur_game:
            ustate["game"] = cur_game
            ustate["start"] = now
        else:
            ustate["game"] = None
            ustate["start"] = None

        await self._challenge_autoclaim_tick(after.guild)

    # M06#2.2 playtime accumulation
    async def _accumulate_playtime(self, guild: discord.Guild, member: discord.Member, game: str, seconds: float):
        day = _day_key_utc()
        async with self.config.user(member).all() as u:
            if u.get("challenge_day") != day:
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

        async with self.config.guild(guild).all() as g:
            if g.get("challenge_day") != day:
                g["challenge_day"] = day
                g["challenge_server_total_secs"] = 0
                g["challenge_samegame_clock"] = {}
            g["challenge_server_total_secs"] = int(g.get("challenge_server_total_secs", 0) + int(seconds))
            sg = g.get("challenge_samegame_clock", {}) or {}
            sg[game] = int(sg.get(game, 0) + int(seconds))
            g["challenge_samegame_clock"] = sg

    # ---------------- FEATURED TODAY ---------------------------------------
    # M06#2.3 featured selectie (met fix: altijd ≥1 als pool niet leeg)
    async def _featured_today(self, guild: discord.Guild) -> List[str]:
        g = await self.config.guild(guild).all()
        mode = (g.get("challenge_featured_mode") or "auto").lower()
        day = _day_key_utc()

        if g.get("challenge_featured_cache_day") == day:
            cached = g.get("challenge_featured_today") or []
            if cached:
                return cached

        today_list: List[str] = []
        if mode == "manual":
            wk = _weekday_key_utc()
            today_list = [_norm_game(x) for x in (g.get("challenge_featured_week", {}).get(wk) or []) if _norm_game(x)]
        else:
            base = [_norm_game(x) for x in (g.get("challenge_featured_list") or []) if _norm_game(x)]
            cnt = int(g.get("challenge_featured_count", 2))
            if base:
                rnd = random.Random(day + str(guild.id))
                rnd.shuffle(base)
                pick = max(1, min(cnt if cnt > 0 else 1, len(base)))
                today_list = base[:pick]

        if not today_list:
            base = [_norm_game(x) for x in (g.get("challenge_featured_list") or []) if _norm_game(x)]
            if base:
                today_list = [base[0]]

        await self.config.guild(guild).challenge_featured_today.set(today_list)
        await self.config.guild(guild).challenge_featured_cache_day.set(day)
        return today_list

    # ---------------- LLM GENERATION ---------------------------------------
    # M06#2.4 API key cache
    async def _get_api_key(self) -> Optional[str]:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    # M06#2.5 LLM vragen
    async def _llm_generate_challenges(
        self, guild: discord.Guild, *, count: int, model: str, timeout: int, require_one_game: bool
    ) -> List[dict]:
        api_key = await self._get_api_key()
        if not api_key:
            return []

        featured = await self._featured_today(guild)
        featured_str = ", ".join(f"'{x}'" for x in featured) if featured else ""

        prompt = (
            "Genereer {count} Discord challenges in JSON (alleen JSON). "
            "Elke challenge: "
            "{type: one of ['playtime_single','playtime_total','unique_games','community_total','playtime_single_game','community_game_total'], "
            " target: integer (minutes for playtime/community, count for unique_games), "
            " reward: integer Boo'z (20..60), "
            " description: korte NL achievement-achtige zin (max 120 tekens), "
            " game?: string (vereist voor *_game types en MOET in featured lijst zitten). } "
            "Regels: maak PRECIES 1 challenge met *_game (alleen als featured lijst niet leeg is) en alle overige challenges zonder *_game; "
            "herhaal geen types. "
            f"Featured today: [{featured_str}]. "
            "Focus op lichte, haalbare doelen."
        ).replace("{count}", str(count))

        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as sess:
                payload = {"model": model, "messages": [{"role": "user", "content": prompt}]}
                async with sess.post(
                    "https://api.openai.com/v1/chat/completions",
                    json=payload,
                    headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                ) as r:
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
            raw = json.loads(m.group(0))
            if not isinstance(raw, list):
                return []
        except Exception:
            return []

        featured_set = set(featured)
        seen_types = set()
        out: List[dict] = []
        game_taken = False

        for ch in raw:
            t = str(ch.get("type", ""))
            if t not in set(GENERIC_TYPES) | set(GAME_TYPES):
                continue

            if t in GENERIC_TYPES and t in seen_types:
                continue
            if t in GAME_TYPES and game_taken:
                continue

            target = int(ch.get("target", DEFAULT_TARGETS.get(t, 30)))
            reward = _clamp_reward(int(ch.get("reward", 30)))
            game = _norm_game(ch.get("game", "")) if "game" in ch else ""

            if t in GAME_TYPES:
                if not featured or not game or game not in featured_set:
                    continue

            desc = _nice_desc(t, target, game)
            item = {"type": t, "target": target, "reward": reward, "description": desc}
            if game:
                item["game"] = game
            out.append(item)

            if t in GENERIC_TYPES:
                seen_types.add(t)
            if t in GAME_TYPES:
                game_taken = True

        return out[:count]

    # ---------------- FALLBACKS --------------------------------------------
    # M06#2.6 fallback generics & game
    def _fallback_generic_pool(self) -> List[dict]:
        return [
            {"type": "playtime_single", "target": DEFAULT_TARGETS["playtime_single"]},
            {"type": "playtime_total",  "target": DEFAULT_TARGETS["playtime_total"]},
            {"type": "unique_games",    "target": DEFAULT_TARGETS["unique_games"]},
            {"type": "community_total", "target": DEFAULT_TARGETS["community_total"]},
        ]

    def _fallback_game_for(self, game: str) -> dict:
        return {"type": "playtime_single_game", "target": DEFAULT_TARGETS["playtime_single_game"], "game": game}

    def _decorate(self, items: List[dict]) -> List[dict]:
        rnd = random.Random(_day_key_utc())
        out = []
        for ch in items:
            t = ch["type"]
            target = int(ch.get("target", DEFAULT_TARGETS.get(t, 30)))
            reward = _clamp_reward(int(ch.get("reward", rnd.randint(20, 60))))
            game = ch.get("game")
            item = {"type": t, "target": target, "reward": reward, "description": _nice_desc(t, target, game)}
            if game:
                item["game"] = _norm_game(game)
            out.append(item)
        return out

    # ---------------- SET OPBOUW -------------------------------------------
    # M06#2.7 set bouwen (4/dag, 1 game indien mogelijk, geen dubbele types)
    async def _ensure_challenge_set(self, guild: discord.Guild) -> None:
        g = await self.config.guild(guild).all()
        reset_hour = int(g.get("challenge_reset_hour", 4))
        cutoff = _cutoff_ts_at_hour_utc(reset_hour)
        current_set_ts = float(g.get("challenge_set_ts", 0.0))
        desired_count = 4

        existing = g.get("challenges_today") or []
        if current_set_ts >= cutoff and len(existing) == desired_count:
            return

        featured_today = await self._featured_today(guild)
        have_featured = bool(featured_today)

        model = g.get("llm_model", "gpt-5-nano")
        timeout = int(g.get("llm_timeout", 45))
        llm = await self._llm_generate_challenges(
            guild, count=desired_count, model=model, timeout=timeout, require_one_game=have_featured
        )

        rnd = random.Random(_day_key_utc() + str(guild.id))
        seen_types = set()
        chosen: List[dict] = []
        game_taken = any(x["type"] in GAME_TYPES for x in llm)

        # Neem bruikbare uit LLM met dedup
        for ch in llm:
            t = ch["type"]
            if t in GENERIC_TYPES:
                if t in seen_types:
                    continue
                seen_types.add(t)
                chosen.append(ch)
            elif t in GAME_TYPES and not any(x["type"] in GAME_TYPES for x in chosen):
                chosen.append(ch)
                game_taken = True

        # Forceer precies 1 game als mogelijk
        if have_featured and not game_taken:
            chosen.append(self._fallback_game_for(rnd.choice(featured_today)))
            game_taken = True

        # Vul generics aan zonder duplicaten
        pool = self._fallback_generic_pool()
        rnd.shuffle(pool)
        for ch in pool:
            if len(chosen) >= desired_count:
                break
            if ch["type"] in seen_types:
                continue
            seen_types.add(ch["type"])
            chosen.append(ch)

        chosen = chosen[:desired_count]
        final = []
        now = _utc_ts()
        for i, ch in enumerate(self._decorate(chosen), start=1):
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

    # ---------------- AUTO-CLAIM -------------------------------------------
    # M06#2.8 auto-claim loop
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

            # community types -> announce in kanaal, geen DM
            if ctype == "community_total":
                if ch.get("claimed_done"):
                    continue
                mins = server_total_secs // 60
                if mins >= target:
                    ch["claimed_done"] = True
                    changed = True
                    await self._announce(guild, f"🎯 Community challenge gehaald: **{ch['description']}**")
                continue

            if ctype == "community_game_total":
                if ch.get("claimed_done"):
                    continue
                mins = int(same_clock.get(game, 0)) // 60
                if mins >= target:
                    ch["claimed_done"] = True
                    changed = True
                    pretty = _short_game(game) or "deze game"
                    await self._announce(guild, f"🎯 Community (game) gehaald: **{pretty}**")

            # per-user
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
                        await self._reward_user_dm(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "unique_games":
                    if len(set(u.get("challenge_unique_games", []) or [])) >= target:
                        await self._reward_user_dm(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "playtime_single":
                    per = u.get("challenge_per_game", {}) or {}
                    best = max([int(x) for x in per.values()], default=0)
                    if best // 60 >= target:
                        await self._reward_user_dm(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "playtime_single_game":
                    per = u.get("challenge_per_game", {}) or {}
                    secs = int(per.get(game, 0))
                    if secs // 60 >= target:
                        pretty = _short_game(game) or "deze game"
                        await self._reward_user_dm(m, reward, reason=f"Speel {target} min in {pretty} vandaag")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

        if changed:
            await self.config.guild(guild).challenges_today.set(chs)

    # M06#2.9 reward via DM (respecteert globale testmodus)
    async def _reward_user_dm(self, member: discord.Member, amount: int, *, reason: str):
        g = await self.config.guild(member.guild).all()
        if g.get("global_testmode", False):
            try:
                await member.send(f"🧪 Testmodus: **geen** Boo'z toegekend voor: {reason}")
            except Exception:
                pass
            return

        bal = await self.config.user(member).booz()
        await self.config.user(member).booz.set(int(bal) + int(amount))
        try:
            await member.send(f"🏅 Je voltooide een challenge: **{reason}** → +{amount} Boo'z")
        except Exception:
            pass

    # M06#2.10 announce helper
    async def _get_announce_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        ch_id = await self.config.guild(guild).announce_channel()
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        return guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    async def _announce(self, guild: discord.Guild, text: str):
        try:
            ch = await self._get_announce_channel(guild)
            if ch:
                await ch.send(text)
        except Exception:
            pass

    # ---------------- COMMANDS ---------------------------------------------
    # M06#2.11 Challenges tonen (DM + korte samenvatting in kanaal kan optioneel; nu DM only)
    @commands.command(name="boozychallenges")
    async def boozychallenges(self, ctx: commands.Context):
        """Stuur je challenges van vandaag via DM (fallback: huidig kanaal)."""
        await self._ensure_challenge_set(ctx.guild)
        g = await self.config.guild(ctx.guild).all()
        chs = await self.config.guild(ctx.guild).challenges_today() or []
        featured = await self._featured_today(ctx.guild)

        u = await self.config.user(ctx.author).all()
        total = int(u.get("challenge_total_secs", 0)) // 60
        per = u.get("challenge_per_game", {}) or {}
        best_game, best = "-", 0
        for name, secs in per.items():
            if int(secs) > best:
                best = int(secs)
                best_game = name
        best_mins = best // 60
        uniq = len(set(u.get("challenge_unique_games", []) or []))

        lines = [
            f"🎯 **Challenges vandaag** (auto-claim: {'aan' if g.get('challenge_auto_enabled', True) else 'uit'})",
            f"🕹️ Featured: {', '.join(map(_short_game, featured)) if featured else '_geen ingesteld_'}"
        ]
        if not chs:
            lines.append("_Nog geen challenges — admin kan `!refreshchallenges` doen._")
        for ch in chs:
            t, target, reward = ch["type"], int(ch["target"]), int(ch["reward"])
            game = ch.get("game")
            claimed = (str(ctx.author.id) in ch.get("claimed_users", [])) or (t.startswith("community") and ch.get("claimed_done"))
            if t == "playtime_single":
                prog = f"{best_mins}/{target} min (beste game: {_short_game(best_game)})"
            elif t == "playtime_total":
                prog = f"{total}/{target} min"
            elif t == "unique_games":
                prog = f"{uniq}/{target} games"
            elif t == "playtime_single_game":
                mins = int(per.get(game, 0)) // 60
                prog = f"{mins}/{target} min in {_short_game(game)}"
            elif t == "community_game_total":
                mins = int(g.get('challenge_samegame_clock', {}).get(game, 0)) // 60
                prog = f"server: {mins}/{target} min in {_short_game(game)}"
            else:  # community_total
                mins = int(g.get('challenge_server_total_secs', 0)) // 60
                prog = f"server: {mins}/{target} min"
            lines.append(f"• {'✅' if claimed else '▫️'} **{ch['description']}** — 🎁 {reward} — {prog}")

        text = "\n".join(lines)
        try:
            await ctx.author.send(text)
        except Exception:
            await ctx.send(text)

        await self._challenge_autoclaim_tick(ctx.guild)

    # M06#2.12 (Admin) refresh set
    @commands.command(name="refreshchallenges")
    @commands.has_permissions(administrator=True)
    async def refreshchallenges(self, ctx: commands.Context):
        """(Admin) Her-genereer de challenge set (4 per dag, exact 1 game indien mogelijk)."""
        await self.config.guild(ctx.guild).challenge_set_ts.set(0.0)
        await self.config.guild(ctx.guild).challenges_today.set([])
        await self._ensure_challenge_set(ctx.guild)
        await ctx.send("🔁 Challenges opnieuw gegenereerd voor vandaag.")
        await self._challenge_autoclaim_tick(ctx.guild)

    # Legacy alias
    @commands.command(name="regenchallenges")
    @commands.has_permissions(administrator=True)
    async def regenchallenges(self, ctx: commands.Context):
        """Alias van !refreshchallenges (admin)."""
        await self.refreshchallenges(ctx)

    # ---------------- BACKGROUND LOOP --------------------------------------
    # M06#2.13 loop
    async def _challenge_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
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
                    await self._challenge_autoclaim_tick(guild)
            except Exception as e:
                print(f"[BoozyBank Challenges] loop error: {e}")
            await asyncio.sleep(120)
