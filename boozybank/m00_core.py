# [00] CORE — bootstrap + defaults + mixin wiring (robust)
# Laadt alle mixins als ze bestaan; anders vallen we terug op no-op mixins.
# Default LLM-model: gpt-5-nano

from redbot.core import Config, commands

# ---- Try to import mixins; fall back to no-op classes if missing ----
try:
    from .m01_utils import FALLBACK_BANK  # noqa: F401
except Exception:  # pragma: no cover
    FALLBACK_BANK = None  # alleen om import-orde te forceren

try:
    from .m02_economy import EconomyMixin
except Exception:  # pragma: no cover
    class EconomyMixin:  # no-op
        pass

try:
    from .m03_settings import SettingsMixin
except Exception:  # pragma: no cover
    class SettingsMixin:  # no-op
        pass

try:
    from .m04_rewards import RewardsMixin
except Exception:  # pragma: no cover
    class RewardsMixin:  # no-op
        async def _voice_loop(self):  # wordt defensief gecheckt
            return

try:
    from .m05_quiz import QuizMixin
except Exception:  # pragma: no cover
    class QuizMixin:  # no-op
        pass

try:
    from .m06_doctor import DoctorMixin
except Exception:  # pragma: no cover
    class DoctorMixin:  # no-op
        pass


class BoozyBank(RewardsMixin, QuizMixin, EconomyMixin, SettingsMixin, DoctorMixin, commands.Cog):
    """BoozyBank™ — Verdien Boo'z, quiz en koop dingen. Geen pay-to-win, iedereen gelijk."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69421, force_registration=True)

        # ---- Defaults (user) ----
        default_user = {
            "booz": 0,
            "last_chat": 0,                 # voor chat reward cooldown
            "last_voice": 0,                # voor voice interval
            "quiz_rewards_today": 0,        # daily limit teller
            "quiz_reward_reset_ts": 0.0,    # laatste reset timestamp
        }

        # ---- Defaults (guild) ----
        default_guild = {
            # Shop (optioneel gebruikt)
            "shop": {
                "soundboard_access": {"price": 100, "role_id": None},
                "color_role": {"price": 50, "role_id": None},
                "boozy_quote": {"price": 25, "role_id": None},
            },

            # State
            "asked_questions": [],          # anti-dup canon history
            "last_drop": 0.0,               # random drop dag-guard
            "last_quiz": 0.0,               # auto-quiz dag-guard

            # Kanalen & cleanup
            "excluded_channels": [],
            "quiz_channel": None,
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,

            "min_vc_humans": 3,
            "auto_quiz_enabled": True,
            "afk_excluded": True,
            "self_mute_excluded": False,

            # Toggles
            "test_mode": False,
            "debug_quiz": False,

            # Rewards & timings
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,

            "quiz_reward_amount": 50,       # eindreward
            "quiz_reward_reset_hour": 4,    # UTC
            "quiz_daily_limit": 5,

            # LLM
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,
        }

        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        # ---- Runtime state ----
        self.quiz_active: bool = False
        self.quiz_cancelled: bool = False
        self._recent_questions: list[str] = []
        self._api_key: str | None = None
        self.thema_pool = ["games", "alcohol", "films", "board games", "algemeen", "electronics"]

        # ---- Background loop (alleen als RewardsMixin die heeft) ----
        self._auto_task = None
        # Start alleen als de mixin een _voice_loop methode heeft (anders crasht het niet)
        if hasattr(self, "_voice_loop") and callable(getattr(self, "_voice_loop")):
            try:
                self._auto_task = self.bot.loop.create_task(self._voice_loop())
            except Exception:
                self._auto_task = None

    def cog_unload(self):
        # Background task netjes stoppen
        try:
            if self._auto_task:
                self._auto_task.cancel()
        except Exception:
            pass
