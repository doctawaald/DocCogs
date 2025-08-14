# M00 --- CORE ---------------------------------------------------------------
# BoozyBank Cog: config, defaults, alle mixins koppelen, loops starten
# ---------------------------------------------------------------------------

# M00#1 IMPORTS
from __future__ import annotations
from typing import Dict, Optional, List
import asyncio
from redbot.core import commands, Config

# Mixins
from .m03_settings import SettingsMixin
from .m02_economy import EconomyMixin
from .m05_quiz import QuizMixin
from .m06_challenges import ChallengesMixin

# Optioneel (mag ontbreken)
try:
    from .m04_shop import ShopMixin  # type: ignore
except Exception:  # pragma: no cover
    class ShopMixin:  # no-op
        pass

# Utils
from .m01_utils import utc_ts, day_key_utc


# M00#2 COG
class BoozyBank(SettingsMixin, EconomyMixin, ShopMixin, QuizMixin, ChallengesMixin, commands.Cog):
    """BoozyBank™ — economie, quiz, challenges, random drops."""

    # M00#2.1 INIT
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB007B00E, force_registration=True)

        # M00#2.2 DEFAULTS
        default_guild = {
            # Kanalen & toggles
            "quiz_channel": None,
            "announce_channel": None,
            "excluded_channels": [],
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,
            "min_vc_humans": 3,
            "auto_quiz_enabled": True,
            "afk_excluded": True,
            "self_mute_excluded": False,
            "debug_quiz": False,
            "test_mode": False,            # legacy
            "global_testmode": False,      # alle rewards uit

            # Rewards / timing
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,
            "random_drop_done_day": None,  # M00 random drop dagflag
            "quiz_reward_amount": 50,
            "quiz_reward_reset_hour": 4,
            "quiz_daily_limit": 5,

            # LLM
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,

            # Shop
            "shop": {},  # {key: {"price": int, "role_id": int|None}}

            # Challenges / Featured
            "challenge_featured_mode": "auto",   # auto | manual
            "challenge_featured_count": 2,
            "challenge_featured_list": [],
            "challenge_featured_week": {},
            "challenge_featured_today": [],
            "challenge_featured_cache_day": None,

            # Challenge voortgang (historische som-klokken)
            "challenge_day": None,
            "challenge_server_total_secs": 0,
            "challenge_samegame_clock": {},

            # Server-concurrency klokken
            "server_any_secs": 0,
            "server_together_secs": 0,
            "samegame_any_secs": {},
            "samegame_together_secs": {},

            # Challenge gedrag
            "challenge_auto_enabled": True,
            "challenge_daily_count": 4,
            "challenge_reset_hour": 4,
            "challenge_reward_min": 20,
            "challenge_reward_max": 60,
            "challenges_today": [],
            "challenge_set_ts": 0.0,
        }

        default_user = {
            "booz": 0,

            # challenge voortgang (presence)
            "challenge_day": None,
            "challenge_total_secs": 0,
            "challenge_unique_games": [],
            "challenge_per_game": {},

            # contribution (voice-based samen)
            "together_secs": 0,            # ≥2 mensen in voice
            "together_game_secs": {},      # {game: seconds}
        }

        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)

        # M00#2.3 STATE
        self._api_key: Optional[str] = None
        # presence sessions: {guild_id: {user_id: {"game":str,"start":ts}}}
        self._presence_sessions: Dict[int, Dict[int, dict]] = {}

        # M00#2.4 TASKS
        self._challenge_task = self.bot.loop.create_task(self._challenge_loop())  # m06
        self._random_drop_task = self.bot.loop.create_task(self._random_drop_loop())  # m00

    # M00#2.5 UNLOAD
    def cog_unload(self):
        for task in (getattr(self, "_challenge_task", None), getattr(self, "_random_drop_task", None)):
            try:
                task.cancel()
            except Exception:
                pass

    # M00#3 RANDOM DROP LOOP
    async def _random_drop_loop(self):
        await self.bot.wait_until_ready()
        # Check elke 5 minuten of we een drop kunnen doen (max 1× per dag)
        CHECK_SECS = 300
        while not self.bot.is_closed():
            try:
                for guild in list(self.bot.guilds):
                    await self._maybe_random_drop(guild)
            except Exception as e:
                print(f"[BoozyBank RandomDrop] loop error: {e}")
            await asyncio.sleep(CHECK_SECS)

    async def _maybe_random_drop(self, guild):
        g = await self.config.guild(guild).all()
        drop_day = g.get("random_drop_done_day")
        today = day_key_utc()
        # reset dagflag vanzelf als dag verandert
        if drop_day != today:
            await self.config.guild(guild).random_drop_done_day.set(None)
            drop_day = None

        if drop_day:  # vandaag al geweest
            return

        # Voorwaarde: min aantal mensen in eender welk VC
        min_humans = int(g.get("min_vc_humans", 3))
        candidates: List[int] = []
        for vc in guild.voice_channels:
            members = [m for m in vc.members if not m.bot]
            if len(members) >= min_humans:
                candidates.extend([m.id for m in members])

        if not candidates:
            return

        # Kans om te triggeren (1/4 per check ≈ gemiddeld 20 min)
        import random
        if random.random() < 0.25:
            amount = int(g.get("random_drop_amount", 10))
            if amount <= 0:
                await self.config.guild(guild).random_drop_done_day.set(today)
                return
            # Testmodus geen uitbetaling
            testmode = bool(g.get("global_testmode", False))
            winners = list({*candidates})  # uniek
            if winners:
                await self.config.guild(guild).random_drop_done_day.set(today)
                # Uitbetalen + bericht
                text_lines = []
                for uid in winners:
                    member = guild.get_member(uid)
                    if not member or member.bot:
                        continue
                    if testmode:
                        try:
                            await member.send(f"🧪 Testmodus: random drop **geen** Boo'z.")
                        except Exception:
                            pass
                    else:
                        cur = await self.config.user(member).booz()
                        await self.config.user(member).booz.set(int(cur) + amount)
                        try:
                            await member.send(f"🍀 Random Drop! Je kreeg **+{amount}** Boo'z.")
                        except Exception:
                            pass
                    text_lines.append(member.mention)
                # Announce in announce-channel
                ch = await self._get_announce_channel(guild)
                if ch and text_lines:
                    await ch.send(f"🎁 Random Drop! Proficiat: {', '.join(text_lines)}")
