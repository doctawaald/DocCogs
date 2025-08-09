import asyncio
from redbot.core import Config, commands

from .01_utils import FALLBACK_BANK  # ensures file is loaded early
from .04_rewards import RewardsMixin
from .05_quiz import QuizMixin
from .02_economy import EconomyMixin
from .03_settings import SettingsMixin

class BoozyBank(RewardsMixin, QuizMixin, EconomyMixin, SettingsMixin, commands.Cog):
    """BoozyBank™ — Verdien Boo'z, quiz en koop dingen. Geen pay-to-win, iedereen gelijk."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69421, force_registration=True)

        # ----- Defaults -----
        default_user = {
            "booz": 0,
            "last_chat": 0,                 # ts laatste chat reward
            "last_voice": 0,                # ts laatste voice reward
            "quiz_rewards_today": 0,        # aantal keer user vandaag eindreward kreeg
            "quiz_reward_reset_ts": 0.0,    # cutoff timestamp voor daily reset
        }
        default_guild = {
            # Shop voorbeeld
            "shop": {
                "soundboard_access": {"price": 100, "role_id": None},
                "color_role": {"price": 50, "role_id": None},
                "boozy_quote": {"price": 25, "role_id": None},
            },
            # State
            "last_drop": 0.0,
            "last_quiz": 0.0,

            # Kanalen/cleanup
            "excluded_channels": [],
            "quiz_channel": None,
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,

            # Testmodus
            "test_mode": False,

            # Anti-dup persist
            "asked_questions": [],  # laatste 50 vraagstrings

            # === Rewards & timings (instelbaar) ===
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,
            "quiz_reward_amount": 50,           # eindreward voor winnaar(s)
            "quiz_reward_reset_hour": 4,        # daily cutoff (UTC)
            "quiz_daily_limit": 5,              # max belonende quizzes per dag per user
        }
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        # ----- Runtime attrs (voor mixins) -----
        self.quiz_active: bool = False
        self._recent_questions: list[str] = []   # in-memory anti-dup (laatste 50)
        self._api_key: str | None = None
        self.thema_pool = ["games", "alcohol", "films", "board games", "algemeen"]

        # RewardsMixin definieert _voice_loop; start task hier
        self._auto_task = self.bot.loop.create_task(self._voice_loop())

    def cog_unload(self):
        self._auto_task.cancel()
