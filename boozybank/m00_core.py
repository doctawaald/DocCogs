# M00 --- CORE ---------------------------------------------------------------
# BoozyBank Cog: basis-config, defaults, mixins koppelen, background loop start
# ---------------------------------------------------------------------------

# M00#1 IMPORTS
from __future__ import annotations
import asyncio
from typing import Dict
from redbot.core import commands, Config

# Mixins
from .m03_settings import SettingsMixin
from .m06_challenges import ChallengesMixin


# M00#2 COG
class BoozyBank(SettingsMixin, ChallengesMixin, commands.Cog):
    """BoozyBank™ — server-economie, quizzes & challenges."""

    # M00#2.1 INIT
    def __init__(self, bot):
        self.bot = bot

        # Config
        self.config = Config.get_conf(self, identifier=0xB007B00Z, force_registration=True)

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
            "test_mode": False,            # legacy test voor specifieke paden
            "global_testmode": False,      # NIEUW: globale testmodus (alle rewards uit)

            # Rewards / timing (chat/voice/random/quiz)
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,
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
            "challenge_featured_list": [],       # pool
            "challenge_featured_week": {},       # manual schema {mon:[..],...}
            "challenge_featured_today": [],
            "challenge_featured_cache_day": None,

            # Challenge voortgang (server-accu)
            "challenge_day": None,
            "challenge_server_total_secs": 0,
            "challenge_samegame_clock": {},

            # Challenge gedrag
            "challenge_auto_enabled": True,
            "challenge_daily_count": 4,          # houden we hier op 4, maar m06 forceert 4
            "challenge_reset_hour": 4,
            "challenge_reward_min": 20,
            "challenge_reward_max": 60,
            "challenges_today": [],
            "challenge_set_ts": 0.0,
        }

        default_user = {
            "booz": 0,
            # challenge voortgang
            "challenge_day": None,
            "challenge_total_secs": 0,
            "challenge_unique_games": [],
            "challenge_per_game": {},  # {game: seconds}
        }

        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)

        # M00#2.3 STATE
        self._api_key = None
        self._presence_sessions: Dict[int, Dict[int, dict]] = {}  # {guild_id: {user_id: {"game":str,"start":ts}}}

        # Background loops (alleen challenges nu)
        self._challenge_task = self.bot.loop.create_task(self._challenge_loop())

    # M00#2.4 UNLOAD
    def cog_unload(self):
        try:
            self._challenge_task.cancel()
        except Exception:
            pass
