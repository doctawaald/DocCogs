# m00_core.py
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

class BoozyBank(
    SettingsMixin,
    EconomyMixin,
    ShopMixin,
    QuizMixin,
    ChallengesMixin,
    RandomDropMixin,
    commands.Cog,
):
    """BoozyBank™ — economy, shop, quiz, challenges, random drop, rewards"""

    # M00#1 INIT
    def __init__(self, bot):
        self.bot = bot
        # FIX: geldig hex getal (geen 'Z')
        self.config = Config.get_conf(self, identifier=0xB00D0001, force_registration=True)

        # Guild defaults (uitgebreid met challenge-keys)
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

            # challenges (ontbrak eerder → toegevoegd)
            "challenge_reset_hour": DAILY_RESET_UTC_HOUR,
            "challenge_featured_list": [],
            "challenges_today": [],
            "challenge_set_ts": 0.0,
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

        # background tasks (andere mixins starten hun eigen taken)
        self._voice_task = self.bot.loop.create_task(self._voice_reward_loop())

    # M00#2 UNLOAD (ruim alles op, ook tasks uit mixins)
    def cog_unload(self):
        tasks = [
            getattr(self, "_voice_task", None),
            getattr(self, "_challenge_task", None),  # ChallengesMixin
            getattr(self, "_drop_task", None),       # RandomDropMixin
        ]
        for t in tasks:
            try:
                t and t.cancel()
            except Exception:
                pass

    # M00#3 HELPERS
    async def _get_announce_channel(self, guild: discord.Guild):
        ch_id = await self.config.guild(guild).announce_channel()
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        return guild.system_channel or next(
            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
            None,
        )

    # M00#4 CHAT REWARD
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        g = await self.config.guild(message.guild).all()
        if g.get("global_testmode", False):
            return
        if message.channel.id in (g.get("excluded_channels") or []):
            return
        now = time.time()
        key = (message.guild.id, message.author.id)
        last = self._chat_last.get(key, 0.0)
        cd = int(g.get("chat_reward_cooldown_sec", 300))
        if now - last >= cd:
            amt = int(g.get("chat_reward_amount", 1))
            cur = await self.config.user(message.author).booz()
            await self.config.user(message.author).booz.set(int(cur) + amt)
            self._chat_last[key] = now

    # M00#5 VOICE REWARD LOOP
    async def _voice_reward_loop(self):
        await self.bot.wait_until_ready()
        TICK = 15
        while not self.bot.is_closed():
            try:
                for guild in list(self.bot.guilds):
                    g = await self.config.guild(guild).all()
                    if g.get("global_testmode", False):
                        continue
                    amt = int(g.get("voice_reward_amount", 1))
                    itv = max(1, int(g.get("voice_reward_interval_sec", 300)))
                    afk_ignore = bool(g.get("afk_excluded", True))
                    self_mute_ignore = bool(g.get("self_mute_excluded", False))
                    afk_id = guild.afk_channel.id if (guild.afk_channel and afk_ignore) else None
                    now = time.time()
                    for vc in guild.voice_channels:
                        if afk_id and vc.id == afk_id:
                            continue
                        for m in vc.members:
                            if m.bot:
                                continue
                            if self_mute_ignore and (m.voice.self_mute or m.voice.self_deaf):
                                continue
                            key = (guild.id, m.id)
                            last = self._voice_last.get(key, 0.0)
                            if now - last >= itv:
                                cur = await self.config.user(m).booz()
                                await self.config.user(m).booz.set(int(cur) + amt)
                                self._voice_last[key] = now
            except Exception as e:
                print(f"[BoozyBank VoiceReward] {e}")
            await asyncio.sleep(TICK)

    # M00#6 HEALTH
    @commands.command()
    async def boozyhealth(self, ctx: commands.Context):
        g = await self.config.guild(ctx.guild).all()
        t_voice = getattr(self, "_voice_task", None)
        t_chal  = getattr(self, "_challenge_task", None)
        t_drop  = getattr(self, "_drop_task", None)
        lines = [
            "🩺 **Boozy health**",
            f"• VoiceReward: {'running' if (t_voice and not t_voice.done()) else 'stopped'}",
            f"• ChallengesLoop: {'running' if (t_chal and not t_chal.done()) else 'stopped'}",
            f"• RandomDropLoop: {'running' if (t_drop and not t_drop.done()) else 'stopped'}",
            f"• Testmode: {'aan' if g.get('global_testmode', False) else 'uit'}",
            f"• LLM: {g.get('llm_model','gpt-5-nano')} (timeout {g.get('llm_timeout',45)}s)",
            f"• Random drop vandaag: {'ja' if (g.get('random_drop_done_day') == day_key_utc()) else 'nee'}",
        ]
        await ctx.send("\n".join(lines))
