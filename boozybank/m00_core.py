# ============================
# m00_core.py
# ============================
from __future__ import annotations
import asyncio, time
import discord
from redbot.core import commands, Config
from .m01_utils import (
    COIN, DAILY_RESET_UTC_HOUR, day_key_utc, utc_ts, cutoff_ts_at_hour_utc,
)
from .m02_economy import EconomyMixin
from .m03_settings import SettingsMixin
from .m04_shop import ShopMixin
from .m05_quiz import QuizMixin
from .m06_challenges import ChallengesMixin
from .m07_randomdrop import RandomDropMixin

class BoozyBank(SettingsMixin, EconomyMixin, ShopMixin, QuizMixin, ChallengesMixin, RandomDropMixin, commands.Cog):
    """BoozyBank™ — economy, shop, quiz, challenges, random drop, rewards"""

    # M00#1 INIT
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB00Z0001, force_registration=True)

        default_guild = {
            # channels & toggles
            "announce_channel": None,
            "quiz_channel": None,
            "global_testmode": False,
            "excluded_channels": [],
            "afk_excluded": True,
            "self_mute_excluded": False,

            # LLM
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,

            # rewards
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,

            # quiz
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,
            "quiz_reward_amount": 50,
            "quiz_daily_limit": 5,
            "quiz_reward_reset_hour": DAILY_RESET_UTC_HOUR,
            "quiz_diff_mult": {"easy": 1.0, "medium": 1.25, "hard": 1.5},

            # random drop
            "random_drop_amount": 10,
            "random_drop_done_day": None,
            "min_vc_humans": 3,
        }
        default_user = {
            "booz": 0,
            # quiz win-limit
            "quiz_day": None,
            "quiz_wins_today": 0,
            # challenges clocks
            "challenge_day": None,
            "challenge_total_secs": 0,
            "challenge_unique_games": [],
            "challenge_per_game": {},
            "together_secs": 0,
            "together_game_secs": {},
        }
        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)

        # cooldown state
        self._chat_last = {}
        self._voice_last = {}

        # tasks
        self._voice_task = self.bot.loop.create_task(self._voice_reward_loop())

    # M00#2 UNLOAD
    def cog_unload(self):
        for t in (getattr(self, "_voice_task", None),):
            try:
                t.cancel()
            except Exception:
                pass
