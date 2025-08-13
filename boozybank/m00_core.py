# [00] CORE — bootstrap + defaults + mixin wiring + diag (incl. Featured Games + Challenges)

from typing import Dict
from redbot.core import Config, commands

from .m01_utils import FALLBACK_BANK  # noqa: F401 (force import order)
from .m02_economy import EconomyMixin
from .m03_settings import SettingsMixin
from .m04_rewards import RewardsMixin
from .m05_quiz import QuizMixin
from .m06_challenges import ChallengesMixin


class BoozyBank(RewardsMixin, QuizMixin, EconomyMixin, SettingsMixin, ChallengesMixin, commands.Cog):
    """BoozyBank™ — Verdien Boo'z, quiz en koop dingen. Geen pay-to-win, iedereen gelijk."""

    def __init__(self, bot):
        self.bot = bot
        print("[BoozyBank] __init__ starting...")

        self.config = Config.get_conf(self, identifier=69421, force_registration=True)

        # ---- Defaults (user) ----
        default_user = {
            "booz": 0,
            "last_chat": 0,
            "last_voice": 0,
            "quiz_rewards_today": 0,
            "quiz_reward_reset_ts": 0.0,
            # challenges (dag-tracking)
            "challenge_day": "",
            "challenge_total_secs": 0,
            "challenge_unique_games": [],
            "challenge_per_game": {},
        }

        # ---- Defaults (guild) ----
        default_guild = {
            # Shop (extern soundboard via rol)
            "shop": {
                "soundboard_access": {"price": 100, "role_id": None},
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

            # Toggles
            "test_mode": False,             # laat TEST_USER_ID bypassen (zonder rewards)
            "debug_quiz": False,
            "auto_quiz_enabled": True,
            "afk_excluded": True,
            "self_mute_excluded": False,

            # Minimum aantal humans in VC (voice rewards, random drop, quiz)
            "min_vc_humans": 3,

            # Rewards & timings
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,

            "quiz_reward_amount": 50,       # eindreward
            "quiz_daily_limit": 5,
            "quiz_reward_reset_hour": 4,    # UTC

            # LLM
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,

            # ---- Challenges: algemene ----
            "challenge_auto_enabled": True,
            "challenge_daily_count": 3,
            "challenge_reward_min": 25,
            "challenge_reward_max": 100,
            "challenge_reset_hour": 4,
            "challenge_set_ts": 0.0,
            "challenges_today": [],

            # ---- Challenges: featured games ----
            "challenge_featured_mode": "auto",      # 'auto' | 'manual'
            "challenge_featured_list": [],          # auto-pool
            "challenge_featured_count": 2,          # auto: per dag kiezen (1..3)
            "challenge_featured_week": {},          # manual: {"mon":["Fortnite","Rocket League"], ...}
            "challenge_featured_cache_day": "",
            "challenge_featured_today": [],

            # ---- Server-accu's (dag) ----
            "challenge_day": "",                    # yyyy-mm-dd
            "challenge_server_total_secs": 0,
            "challenge_samegame_clock": {},         # per game total seconds
        }

        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        # ---- Runtime state ----
        self.quiz_active: bool = False
        self.quiz_cancelled: bool = False
        self._recent_questions: list[str] = []
        self._api_key: str | None = None

        # Presence sessions for challenge tracking
        self._presence_sessions: Dict[int, Dict[int, dict]] = {}  # guild_id -> { user_id: {game, start} }

        # Background loops
        self._auto_task = None
        if hasattr(self, "_voice_loop") and callable(getattr(self, "_voice_loop")):
            try:
                self._auto_task = self.bot.loop.create_task(self._voice_loop())
                print("[BoozyBank] voice loop started")
            except Exception as e:
                print(f"[BoozyBank] voice loop could not start: {e}")

        self._challenge_task = None
        if hasattr(self, "_challenge_loop") and callable(getattr(self, "_challenge_loop")):
            try:
                self._challenge_task = self.bot.loop.create_task(self._challenge_loop())
                print("[BoozyBank] challenge loop started")
            except Exception as e:
                print(f"[BoozyBank] challenge loop could not start: {e}")

        print("[BoozyBank] __init__ complete")

    def cog_unload(self):
        try:
            if self._auto_task:
                self._auto_task.cancel()
        except Exception:
            pass
        try:
            if self._challenge_task:
                self._challenge_task.cancel()
        except Exception:
            pass
        print("[BoozyBank] cog_unload called")

    # simpele ping om te verifiëren dat commands registreren
    @commands.command()
    async def boozyping(self, ctx: commands.Context):
        """Ping om te checken of de cog geladen is."""
        await ctx.send("🏓 BoozyBank leeft!")

    # diagnose: toont of settings/keys werken (uitgebreid)
    @commands.command()
    async def boozydiag(self, ctx: commands.Context):
        """Toont enkele kerninstellingen en sanity-check."""
        g = await self.config.guild(ctx.guild).all()
        featured = g.get("challenge_featured_today") or []
        await ctx.send(
            "\n".join([
                "🔧 **BoozyDiag**",
                f"• quiz_channel: {g.get('quiz_channel')}",
                f"• chat: +{g.get('chat_reward_amount')}/{g.get('chat_reward_cooldown_sec')}s",
                f"• voice: +{g.get('voice_reward_amount')}/{g.get('voice_reward_interval_sec')}s",
                f"• random_drop: +{g.get('random_drop_amount')} per dag",
                f"• quiz: reward {g.get('quiz_reward_amount')} | limit {g.get('quiz_daily_limit')} | reset {g.get('quiz_reward_reset_hour')}:00 UTC",
                f"• min_vc_humans: {g.get('min_vc_humans')} | afk_excluded: {g.get('afk_excluded')} | self_mute_excluded: {g.get('self_mute_excluded')}",
                f"• auto_quiz_enabled: {g.get('auto_quiz_enabled')}",
                f"• LLM: {g.get('llm_model')} (timeout {g.get('llm_timeout')}s)",
                "• Challenges:",
                f"   - auto_claim: {g.get('challenge_auto_enabled', True)} | daily_count: {g.get('challenge_daily_count',3)} | reset: {g.get('challenge_reset_hour',4)}:00 UTC",
                f"   - reward_range: {g.get('challenge_reward_min',25)}..{g.get('challenge_reward_max',100)}",
                f"   - featured_mode: {g.get('challenge_featured_mode','auto')} | pick_count: {g.get('challenge_featured_count',2)}",
                f"   - featured_today: {', '.join(featured) if featured else '_geen_'}",
            ])
        )
