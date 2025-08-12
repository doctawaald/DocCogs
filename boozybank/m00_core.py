# [00] CORE — bootstrap + defaults + mixin wiring

from redbot.core import Config, commands

from .m01_utils import FALLBACK_BANK  # noqa: F401 (force early import)
from .m05_quiz import QuizMixin
from .m02_economy import EconomyMixin  # <-- NIEUW

class BoozyBank(QuizMixin, EconomyMixin, commands.Cog):
    """BoozyBank™ — Verdien Boo'z, quiz en koop dingen. Geen pay-to-win, iedereen gelijk."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69421, force_registration=True)

        default_user = {
            "booz": 0,
            "quiz_rewards_today": 0,
            "quiz_reward_reset_ts": 0.0,
        }
        default_guild = {
            "asked_questions": [],
            "quiz_channel": None,
            "excluded_channels": [],
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,
            "test_mode": False,
            "debug_quiz": False,
            "quiz_reward_amount": 50,
            "quiz_daily_limit": 5,
            "quiz_reward_reset_hour": 4,
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,
        }
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        self.quiz_active: bool = False
        self.quiz_cancelled: bool = False
        self._recent_questions: list[str] = []
        self._api_key: str | None = None

    def cog_unload(self):
        pass
