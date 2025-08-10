# [00] CORE — bootstrap + defaults + mixin wiring

import asyncio
from redbot.core import Config, commands

from .m01_utils import FALLBACK_BANK  # noqa: F401 (force early import)
from .m04_rewards import RewardsMixin
from .m05_quiz import QuizMixin
from .m02_economy import EconomyMixin
from .m03_settings import SettingsMixin
from .m06_doctor import DoctorMixin

class BoozyBank(RewardsMixin, QuizMixin, EconomyMixin, SettingsMixin, DoctorMixin, commands.Cog):
    """BoozyBank™ — Verdien Boo'z, quiz en koop dingen. Geen pay-to-win, iedereen gelijk."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69421, force_registration=True)

        # [01] defaults
        default_user = {
            "booz": 0,
            "last_chat": 0,
            "last_voice": 0,
            "quiz_rewards_today": 0,
            "quiz_reward_reset_ts": 0.0,
        }
        default_guild = {
            # shop
            "shop": {
                "soundboard_access": {"price": 100, "role_id": None},
                "color_role": {"price": 50, "role_id": None},
                "boozy_quote": {"price": 25, "role_id": None},
            },
            # state
            "last_drop": 0.0,
            "last_quiz": 0.0,

            # kanalen/cleanup
            "excluded_channels": [],
            "quiz_channel": None,
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,

            # toggles
            "test_mode": False,
            "debug_quiz": False,  # toon generatie-stats bij start

            # anti-dup persist
            "asked_questions": [],

            # rewards/timings
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,
            "quiz_reward_amount": 50,
            "quiz_reward_reset_hour": 4,
            "quiz_daily_limit": 5,

            # LLM config
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,
        }
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        # [02] runtime
        self.quiz_active: bool = False
        self._recent_questions: list[str] = []
        self._api_key: str | None = None
        self.thema_pool = ["games", "alcohol", "films", "board games", "algemeen"]

        # [03] background loop (from RewardsMixin)
        self._auto_task = self.bot.loop.create_task(self._voice_loop())

    def cog_unload(self):
        self._auto_task.cancel()
