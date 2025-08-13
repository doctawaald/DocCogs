# M06 --- CHALLENGES --------------------------------------------------------
# 4/dag: Personal + Group + Game-bound + Unique, geen duplicaten
# Rewards 20..50 (veelvoud van 5), presence tracking, auto-claim,
# DM voor persoonlijke dingen, announce voor community,
# featured-fix, kanaal-samenvatting, en CONTRIBUTION-mode voor group.
# ---------------------------------------------------------------------------

# M06#1 IMPORTS & CONSTANTS
from __future__ import annotations
import asyncio
import datetime
import json
import random
import re
from typing import Dict, List, Optional, Tuple, Set

import aiohttp
import discord
from aiohttp import ClientTimeout
from redbot.core import commands

COIN = "🪙"

GENERIC_TYPES = ("playtime_single", "playtime_total", "unique_games", "community_total")
GAME_TYPES = ("playtime_single_game", "community_game_total")

DEFAULT_TARGETS = {
    "playtime_single": 45,          # min in 1 game (personal)
    "playtime_total": 120,          # min totaal (personal)
    "unique_games": 3,              # aantal games (personal)
    "community_total": 90,          # min server-totaal (group)
    "playtime_single_game": 30,     # min in specifieke game (personal, game-bound)
    "community_game_total": 120,    # min server in specifieke game (group, game-bound)
}

# ---------- TIME HELPERS
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
    return ["mon", "tue", "wed", "thu", "fri", "sat", "sun"][datetime.datetime.utcnow().weekday()]

# ---------- STR HELPERS
def _short_game(name: Optional[str]) -> str:
    n = (name or "").strip()
    return n if len(n) <= 40 else (n[:37] + "…")

def _norm_game(name: str) -> str:
    return (name or "").strip()

# ---------- REWARD SCALING
def _round5(x: int) -> int:
    return int(5 * round(x / 5))

def _clamp_reward(x: int) -> int:
    return max(20, min(50, _round5(int(x))))  # max 50, veelvouden van 5

def _scaled_reward_minutes(mins: int) -> int:
    """
    Slaat redelijk tussenpunten:
      ~30m → 20, ~60m → 35, ~120m → 50
    Lineaire interpolatie tussen 30..120.
    """
    if mins <= 30:
        return 20
    if mins >= 120:
        return 50
    r = 20 + (mins - 30) * (50 - 20) / (120 - 30)
    return _clamp_reward(int(r))

def _scaled_reward_for_type(ctype: str, target: int) -> int:
    if ctype in ("playtime_single", "playtime_total", "community_total",
                 "playtime_single_game", "community_game_total"):
        return _scaled_reward_minutes(target)
    if ctype == "unique_games":
        return _scaled_reward_minutes(target * 12)  # ~12m per game
    return 20

# ---------- TEXT HELPERS
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


# M06#2 MIXIN ---------------------------------------------------------------
class ChallengesMixin:
    """Presence-based challenges & featured games (met contribution)."""

    # ---------------- PRESENCE TRACKING ------------------------------------
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

        # presence-tijd accumuleren (individueel)
        if prev_game and start:
            elapsed = max(0, now - start)
            await self._accumulate_playtime(after.guild, after, prev_game, elapsed)

        # update huidige game
        if cur_game:
            ustate["game"] = cur_game
            ustate["start"] = now
        else:
            ustate["game"] = None
            ustate["start"] = None

        # Claim-check
        await self._challenge_autoclaim_tick(after.guild)

    async def _accumulate_playtime(self, guild: discord.Guild, member: discord.Member, game: str, seconds: float):
        day = _day_key_utc()
        # user
        async with self.config.user(member).all() as u:
            if u.get("challenge_day") != day:
                u["challenge_day"] = day
                u["challenge_total_secs"] = 0
                u["challenge_unique_games"] = []
                u["challenge_per_game"] = {}
                u["together_secs"] = 0
                u["together_game_secs"] = {}
            u["challenge_total_secs"] = int(u.get("challenge_total_secs", 0) + int(seconds))
            per = u.get("challenge_per_game", {}) or {}
            per[game] = int(per.get(game, 0) + int(seconds))
            u["challenge_per_game"] = per
            uniq = set(u.get("challenge_unique_games", []) or [])
            uniq.add(game)
            u["challenge_unique_games"] = list(uniq)

        # guild (oude som-klokken laten we staan voor compat)
        async with self.config.guild(guild).all() as g:
            if g.get("challenge_day") != day:
                g["challenge_day"] = day
                g["challenge_server_total_secs"] = 0
                g["challenge_samegame_clock"] = {}
                g["server_any_secs"] = 0
                g["server_together_secs"] = 0
                g["samegame_any_secs"] = {}
                g["samegame_together_secs"] = {}
            g["challenge_server_total_secs"] = int(g.get("challenge_server_total_secs", 0) + int(seconds))
            sg = g.get("challenge_samegame_clock", {}) or {}
            sg[game] = int(sg.get(game, 0) + int(seconds))
            g["challenge_samegame_clock"] = sg

    # ---------------- FEATURED TODAY ---------------------------------------
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

    # ---------------- OPENAI (optioneel) -----------------------------------
    async def _get_api_key(self) -> Optional[str]:
        if getattr(self, "_api_key", None):
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    async def _llm_generate_challenges(
        self, guild: discord.Guild, *, count: int, model: str, timeout: int
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
            " reward: integer Boo'z (20..50), "
            " description: korte NL achievement-achtige zin (max 120 tekens), "
            " game?: string (vereist voor *_game types en MOET in featured lijst zitten). } "
            "Regels: maak GEEN dubbele types. "
            f"Featured today: [{featured_str}]. "
            "Focus op lichte, haalbare doelen."
        ).replace("{count}", str(count))

        try:
            async with aiohttp.ClientSession(timeout=ClientTimeout(total=timeout)) as sess:
                payload = {"model": (await self.config.guild(guild).llm_model()), "messages": [{"role": "user", "content": prompt}]}
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

        out: List[dict] = []
        seen_types = set()
        featured_set = set(featured)

        for ch in raw:
            t = str(ch.get("type", ""))
            if t not in set(GENERIC_TYPES) | set(GAME_TYPES):
                continue
            if t in seen_types:
                continue

            target = int(ch.get("target", DEFAULT_TARGETS.get(t, 30)))
            reward = _scaled_reward_for_type(t, target)

            game = ""
            if t in GAME_TYPES:
                game = _norm_game(ch.get("game", ""))
                if not game or game not in featured_set:
                    continue

            item = {"type": t, "target": target, "reward": reward, "description": _nice_desc(t, target, game)}
            if game:
                item["game"] = game
            out.append(item)
            seen_types.add(t)

        return out

    # ---------------- FALLBACKS & DECORATE ---------------------------------
    def _fallback_generic_pool(self) -> List[dict]:
        return [
            {"type": "playtime_single", "target": DEFAULT_TARGETS["playtime_single"]},
            {"type": "playtime_total", "target": DEFAULT_TARGETS["playtime_total"]},
            {"type": "unique_games", "target": DEFAULT_TARGETS["unique_games"]},
            {"type": "community_total", "target": DEFAULT_TARGETS["community_total"]},
        ]

    def _fallback_game_for(self, game: str) -> dict:
        return {"type": "playtime_single_game", "target": DEFAULT_TARGETS["playtime_single_game"], "game": game}

    def _decorate(self, items: List[dict]) -> List[dict]:
        out = []
        for ch in items:
            t = ch["type"]
            target = int(ch.get("target", DEFAULT_TARGETS.get(t, 30)))
            reward = _scaled_reward_for_type(t, target)
            game = ch.get("game")
            item = {"type": t, "target": target, "reward": reward, "description": _nice_desc(t, target, game)}
            if game:
                item["game"] = _norm_game(game)
            out.append(item)
        return out

    # ---------------- SET OPBOUW (4 vaste categorieën) ---------------------
    def _personal_type_for_today(self) -> str:
        day_num = int(datetime.datetime.utcnow().strftime("%Y%m%d"))
        return "playtime_single" if (day_num % 2 == 0) else "playtime_total"

    async def _ensure_challenge_set(self, guild: discord.Guild) -> None:
        g = await self.config.guild(guild).all()
        reset_hour = int(g.get("challenge_reset_hour", 4))
        cutoff = _cutoff_ts_at_hour_utc(reset_hour)
        current_set_ts = float(g.get("challenge_set_ts", 0.0))

        existing = g.get("challenges_today") or []
        if current_set_ts >= cutoff and len(existing) == 4:
            return

        featured_today = await self._featured_today(guild)
        have_featured = bool(featured_today)

        # 1) Personal
        personal_t = self._personal_type_for_today()
        personal = {"type": personal_t, "target": DEFAULT_TARGETS[personal_t]}

        # 2) Group (algemeen, voice-based contribution)
        group = {"type": "community_total", "target": DEFAULT_TARGETS["community_total"]}

        # 3) Game-bound (voorkeur personal single_game)
        gamepick = None
        if have_featured:
            rnd = random.Random(_day_key_utc() + str(guild.id))
            gamepick = rnd.choice(list(featured_today))
        if gamepick:
            game_bound = {"type": "playtime_single_game", "target": DEFAULT_TARGETS["playtime_single_game"], "game": gamepick}
        else:
            # geen featured → kies alternatieve personal
            alt = "playtime_total" if personal_t == "playtime_single" else "playtime_single"
            game_bound = {"type": alt, "target": DEFAULT_TARGETS[alt]}

        # 4) Unieke games
        unique = {"type": "unique_games", "target": DEFAULT_TARGETS["unique_games"]}

        chosen = [personal, group, game_bound, unique]
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
                "claimed_done": False,  # voor community laten staan maar niet doorslaggevend in contribution
            }
            if "game" in ch:
                item["game"] = _norm_game(ch["game"])
            final.append(item)

        await self.config.guild(guild).challenges_today.set(final)
        await self.config.guild(guild).challenge_set_ts.set(now)

    # ---------------- CONTRIBUTION TICK (VOICE) -----------------------------
    async def _together_tick(self, guild: discord.Guild, delta: int = 60):
        """
        Elke tick:
          - per voice-kanaal: als ≥2 mensen (geen bots) → elke aanwezige +delta naar user.together_secs
          - per game (guild-breed): als ≥2 mensen dezelfde game spelen (ongeacht kanaal) → +delta naar user.together_game_secs[game]
          - server-klokken voor diagnostiek/announce worden ook gevuld
        """
        day = _day_key_utc()

        # 1) voice-kanalen scannen
        channels_human_members: Dict[int, List[discord.Member]] = {}
        human_in_any_voice: Set[int] = set()

        for vc in guild.voice_channels:
            members = [m for m in vc.members if not m.bot]
            if len(members) >= 1:
                for m in members:
                    human_in_any_voice.add(m.id)
            if len(members) >= 2:
                channels_human_members[vc.id] = members

        # 2) per game (ongeacht kanaal) – op basis van presence_sessions
        sess = self._presence_sessions.get(guild.id, {}) or {}
        game_to_users: Dict[str, List[int]] = {}
        for uid, state in sess.items():
            # alleen mensen die ook in voice zitten tellen mee voor game-together
            if uid not in human_in_any_voice:
                continue
            game = _norm_game(state.get("game") or "")
            if not game:
                continue
            if uid is None:
                continue
            game_to_users.setdefault(game, []).append(uid)

        # 3) server-klokken (any/together)
        any_plus = 1 if len(human_in_any_voice) >= 1 else 0
        together_plus = 1 if sum(1 for lst in channels_human_members.values() if len(lst) >= 2) >= 1 else 0

        async with self.config.guild(guild).all() as g:
            if g.get("challenge_day") != day:
                g["challenge_day"] = day
                g["server_any_secs"] = 0
                g["server_together_secs"] = 0
                g["samegame_any_secs"] = {}
                g["samegame_together_secs"] = {}
            if any_plus:
                g["server_any_secs"] = int(g.get("server_any_secs", 0)) + delta
            if together_plus:
                g["server_together_secs"] = int(g.get("server_together_secs", 0)) + delta

            # per game klokken
            s_any = g.get("samegame_any_secs", {}) or {}
            s_tog = g.get("samegame_together_secs", {}) or {}

            for game, uids in game_to_users.items():
                if len(uids) >= 1:
                    s_any[game] = int(s_any.get(game, 0)) + delta
                if len(uids) >= 2:
                    s_tog[game] = int(s_tog.get(game, 0)) + delta

            g["samegame_any_secs"] = s_any
            g["samegame_together_secs"] = s_tog

        # 4) user-contribution updaten
        # voice-kanalen met ≥2 → iedereen +delta naar together_secs
        for members in channels_human_members.values():
            for m in members:
                async with self.config.user(m).all() as u:
                    if u.get("challenge_day") != day:
                        u["challenge_day"] = day
                        u["challenge_total_secs"] = 0
                        u["challenge_unique_games"] = []
                        u["challenge_per_game"] = {}
                        u["together_secs"] = 0
                        u["together_game_secs"] = {}
                    u["together_secs"] = int(u.get("together_secs", 0)) + delta

        # game-bound together: iedereen die die game speelt en in voice zit (≥2) +delta
        for game, uids in game_to_users.items():
            if len(uids) < 2:
                continue
            for uid in uids:
                member = guild.get_member(uid)
                if not member:
                    continue
                async with self.config.user(member).all() as u:
                    if u.get("challenge_day") != day:
                        u["challenge_day"] = day
                        u["challenge_total_secs"] = 0
                        u["challenge_unique_games"] = []
                        u["challenge_per_game"] = {}
                        u["together_secs"] = 0
                        u["together_game_secs"] = {}
                    tg = u.get("together_game_secs", {}) or {}
                    tg[game] = int(tg.get(game, 0)) + delta
                    u["together_game_secs"] = tg

    # ---------------- AUTO-CLAIM (incl. contribution) ----------------------
    async def _challenge_autoclaim_tick(self, guild: discord.Guild):
        g = await self.config.guild(guild).all()
        if not bool(g.get("challenge_auto_enabled", True)):
            return

        await self._ensure_challenge_set(guild)
        chs = await self.config.guild(guild).challenges_today() or []
        changed = False

        # oude server-som-klokken laten we met rust; contribution checkt per user:

        for ch in chs:
            ctype = ch["type"]
            target = int(ch["target"])
            reward = int(ch["reward"])
            game = _norm_game(ch.get("game", ""))

            # Community (contribution): per gebruiker zodra zijn persoonlijke teller target haalt
            if ctype in ("community_total", "community_game_total"):
                for m in guild.members:
                    if m.bot:
                        continue
                    uid = str(m.id)
                    if uid in ch.get("claimed_users", []):
                        continue
                    u = await self.config.user(m).all()
                    if u.get("challenge_day") != _day_key_utc():
                        continue

                    if ctype == "community_total":
                        mins = int(u.get("together_secs", 0)) // 60
                        if mins >= target:
                            await self._reward_user_dm(m, reward, reason=f"{ch['description']}")
                            ch.setdefault("claimed_users", []).append(uid)
                            changed = True

                    elif ctype == "community_game_total":
                        tg = u.get("together_game_secs", {}) or {}
                        mins = int(tg.get(game, 0)) // 60
                        if mins >= target:
                            pretty = _short_game(game) or "deze game"
                            await self._reward_user_dm(m, reward, reason=f"Speel samen {target} min in {pretty} vandaag")
                            ch.setdefault("claimed_users", []).append(uid)
                            changed = True

                # claimed_done niet gebruikt in contribution, laten staan voor compat
                continue

            # Per-user (personal)
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
                    best_secs = max([int(x) for x in per.values()], default=0)
                    if best_secs // 60 >= target:
                        await self._reward_user_dm(m, reward, reason=f"{ch['description']}")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

                elif ctype == "playtime_single_game":
                    per = u.get("challenge_per_game", {}) or {}
                    secs = int(per.get(game, 0))
                    if secs // 60 >= target:
                        await self._reward_user_dm(m, reward, reason=f"Speel {target} min in {_short_game(game) or 'deze game'} vandaag")
                        ch.setdefault("claimed_users", []).append(uid)
                        changed = True

        if changed:
            await self.config.guild(guild).challenges_today.set(chs)

    # ---------------- REWARD / ANNOUNCE HELPERS ----------------------------
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
    @commands.command(name="boozydailychallenges")
    async def boozydailychallenges(self, ctx: commands.Context):
        """
        Korte samenvatting in dit kanaal (zonder persoonlijke voortgang),
        en persoonlijke voortgang via DM.
        """
        await self._ensure_challenge_set(ctx.guild)

        # Publieke samenvatting
        chs = await self.config.guild(ctx.guild).challenges_today() or []
        featured = await self._featured_today(ctx.guild)

        pub_lines = [
            f"🎯 **Challenges vandaag** (auto-claim: {'aan' if (await self.config.guild(ctx.guild).challenge_auto_enabled()) else 'uit'})",
            f"🕹️ Featured: {', '.join(map(_short_game, featured)) if featured else '_geen ingesteld_'}"
        ]
        if not chs:
            pub_lines.append("_Nog geen challenges — admin kan `!refreshchallenges` doen._")
        for ch in chs:
            label = ch["description"]
            pub_lines.append(f"• **{label}** — {COIN} {ch['reward']}")

        await ctx.send("\n".join(pub_lines))

        # Persoonlijke DM
        g = await self.config.guild(ctx.guild).all()
        u = await self.config.user(ctx.author).all()
        total = int(u.get("challenge_total_secs", 0)) // 60
        per = u.get("challenge_per_game", {}) or {}
        best_game = None
        best_secs = 0
        for name, secs in per.items():
            if int(secs) > best_secs:
                best_secs = int(secs)
                best_game = name
        best_mins = best_secs // 60
        uniq = len(set(u.get("challenge_unique_games", []) or []))
        together = int(u.get("together_secs", 0)) // 60
        tg = u.get("together_game_secs", {}) or {}

        dm_lines = [f"🔒 **Jouw voortgang vandaag**"]
        for ch in chs:
            t, target, reward = ch["type"], int(ch["target"]), int(ch["reward"])
            game = ch.get("game")
            claimed = (str(ctx.author.id) in ch.get("claimed_users", [])) or (t.startswith("community") and str(ctx.author.id) in ch.get("claimed_users", []))

            if t == "playtime_single":
                prog = f"{best_mins}/{target} min"
                if best_game:
                    prog += f" (beste: {_short_game(best_game)})"
            elif t == "playtime_total":
                prog = f"{total}/{target} min"
            elif t == "unique_games":
                prog = f"{uniq}/{target} games"
            elif t == "playtime_single_game":
                mins = int(per.get(game or "", 0)) // 60
                prog = f"{mins}/{target} min in {_short_game(game) if game else 'deze game'}"
            elif t == "community_game_total":
                mins = int(tg.get(game or "", 0)) // 60
                prog = f"{mins}/{target} min samen in {_short_game(game) if game else 'deze game'}"
            else:  # community_total
                prog = f"{together}/{target} min samen"

            dm_lines.append(f"• {'✅' if claimed else '▫️'} {ch['description']} — {COIN} {reward} — {prog}")

        try:
            await ctx.author.send("\n".join(dm_lines))
        except Exception:
            pass

        await self._challenge_autoclaim_tick(ctx.guild)

    @commands.command(name="boozychallenges")
    async def boozychallenges(self, ctx: commands.Context):
        """Alias: zelfde gedrag als !boozydailychallenges."""
        await self.boozydailychallenges(ctx)

    @commands.command(name="refreshchallenges")
    @commands.has_permissions(administrator=True)
    async def refreshchallenges(self, ctx: commands.Context):
        """(Admin) Set opnieuw genereren (4 per dag, vast profiel)."""
        await self.config.guild(ctx.guild).challenge_set_ts.set(0.0)
        await self.config.guild(ctx.guild).challenges_today.set([])
        await self._ensure_challenge_set(ctx.guild)
        await ctx.send("🔁 Challenges opnieuw gegenereerd voor vandaag.")
        await self._challenge_autoclaim_tick(ctx.guild)

    @commands.command(name="regenchallenges")
    @commands.has_permissions(administrator=True)
    async def regenchallenges(self, ctx: commands.Context):
        """Alias van !refreshchallenges."""
        await self.refreshchallenges(ctx)

    # ---------------- BACKGROUND LOOP --------------------------------------
    async def _challenge_loop(self):
        await self.bot.wait_until_ready()
        TICK = 60  # 60s resolutie voor 'samen'-tijd
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    now = _utc_ts()
                    # presence per 60s bijwerken (individuele speeltijd)
                    sess = self._presence_sessions.get(guild.id, {})
                    for uid, state in list(sess.items()):
                        game = state.get("game")
                        start = state.get("start")
                        member = guild.get_member(int(uid)) if uid else None
                        if not member or member.bot:
                            continue
                        if game and start and (now - start) >= TICK:
                            await self._accumulate_playtime(guild, member, game, TICK)
                            state["start"] = now
                    # contribution tick op basis van voice
                    await self._together_tick(guild, delta=TICK)
                    # auto-claim check
                    await self._challenge_autoclaim_tick(guild)
            except Exception as e:
                print(f"[BoozyBank Challenges] loop error: {e}")
            await asyncio.sleep(TICK)
