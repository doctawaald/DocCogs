# M00 --- CORE ---------------------------------------------------------------
# BoozyBank Cog: config, defaults, ALLE mixins koppelen, loops + events
# ---------------------------------------------------------------------------

# M00#1 IMPORTS
from __future__ import annotations
from typing import Dict, Optional, Tuple, List
import asyncio
import time
import discord
from redbot.core import commands, Config

# Mixins
from .m03_settings import SettingsMixin
from .m02_economy import EconomyMixin
from .m04_shop import ShopMixin
from .m05_quiz import QuizMixin
from .m06_challenges import ChallengesMixin

# Utils
from .m01_utils import utc_ts, day_key_utc

COIN = "🪙"


# M00#2 COG
class BoozyBank(SettingsMixin, EconomyMixin, ShopMixin, QuizMixin, ChallengesMixin, commands.Cog):
    """BoozyBank™ — economie, shop, quiz, challenges, random drops."""

    # M00#2.1 INIT
    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=0xB007B00E, force_registration=True)

        # M00#2.2 DEFAULTS (GUILD)
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
            "global_testmode": False,      # alle rewards uit

            # Rewards / timing
            "chat_reward_amount": 1,
            "chat_reward_cooldown_sec": 300,
            "voice_reward_amount": 1,
            "voice_reward_interval_sec": 300,
            "random_drop_amount": 10,
            "random_drop_done_day": None,

            # Quiz rewards/limit
            "quiz_reward_amount": 50,
            "quiz_reward_reset_hour": 4,
            "quiz_daily_limit": 5,

            # LLM
            "llm_model": "gpt-5-nano",
            "llm_timeout": 45,

            # Shop
            "shop": {},  # {key: {"price": int, "role_id": int|None, "label": str}}

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

            # Server-concurrency (diagnostiek)
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

        # M00#2.3 DEFAULTS (USER)
        default_user = {
            "booz": 0,

            # quiz limit
            "quiz_day": None,
            "quiz_wins_today": 0,

            # challenges (presence)
            "challenge_day": None,
            "challenge_total_secs": 0,
            "challenge_unique_games": [],
            "challenge_per_game": {},

            # contribution (voice-based samen)
            "together_secs": 0,
            "together_game_secs": {},
        }

        self.config.register_guild(**default_guild)
        self.config.register_user(**default_user)

        # M00#2.4 STATE
        self._api_key: Optional[str] = None
        # presence sessions: {guild_id: {user_id: {"game":str,"start":ts}}}
        self._presence_sessions: Dict[int, Dict[int, dict]] = {}

        # Chat reward cooldowns: {(guild_id, user_id): last_ts}
        self._chat_last: Dict[Tuple[int, int], float] = {}
        # Voice reward last-paid: {(guild_id, user_id): last_ts}
        self._voice_last: Dict[Tuple[int, int], float] = {}

        # M00#2.5 TASKS
        self._challenge_task = self.bot.loop.create_task(self._challenge_loop())    # uit m06
        self._random_drop_task = self.bot.loop.create_task(self._random_drop_loop())
        self._voice_reward_task = self.bot.loop.create_task(self._voice_reward_loop())

    # M00#2.6 UNLOAD
    def cog_unload(self):
        for task in (getattr(self, "_challenge_task", None),
                     getattr(self, "_random_drop_task", None),
                     getattr(self, "_voice_reward_task", None)):
            try:
                task.cancel()
            except Exception:
                pass

    # M00#3 HELPERS (announce)
    async def _get_announce_channel(self, guild: discord.Guild) -> Optional[discord.TextChannel]:
        ch_id = await self.config.guild(guild).announce_channel()
        if ch_id:
            ch = guild.get_channel(ch_id)
            if isinstance(ch, discord.TextChannel):
                return ch
        return guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)

    # M00#4 RANDOM DROP LOOP
    async def _random_drop_loop(self):
        await self.bot.wait_until_ready()
        CHECK_SECS = 300  # elke 5 min
        while not self.bot.is_closed():
            try:
                for guild in list(self.bot.guilds):
                    await self._maybe_random_drop(guild)
            except Exception as e:
                print(f"[BoozyBank RandomDrop] loop error: {e}")
            await asyncio.sleep(CHECK_SECS)

    async def _maybe_random_drop(self, guild: discord.Guild):
        g = await self.config.guild(guild).all()
        drop_day = g.get("random_drop_done_day")
        today = day_key_utc()
        if drop_day != today:
            await self.config.guild(guild).random_drop_done_day.set(None)
            drop_day = None
        if drop_day:
            return

        min_humans = int(g.get("min_vc_humans", 3))
        candidates: List[int] = []
        for vc in guild.voice_channels:
            members = [m for m in vc.members if not m.bot]
            if len(members) >= min_humans:
                candidates.extend([m.id for m in members])
        if not candidates:
            return

        import random
        if random.random() < 0.25:
            amount = int(g.get("random_drop_amount", 10))
            await self.config.guild(guild).random_drop_done_day.set(today)
            if amount <= 0:
                return
            test = bool(g.get("global_testmode", False))
            winners = list({*candidates})
            announce_list = []
            for uid in winners:
                member = guild.get_member(uid)
                if not member or member.bot:
                    continue
                if test:
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
                announce_list.append(member.mention)
            ch = await self._get_announce_channel(guild)
            if ch and announce_list:
                await ch.send(f"🎁 Random Drop! {', '.join(announce_list)}")

    # M00#5 VOICE REWARD LOOP
    async def _voice_reward_loop(self):
        await self.bot.wait_until_ready()
        TICK = 15  # check elke 15s
        while not self.bot.is_closed():
            try:
                now = time.time()
                for guild in list(self.bot.guilds):
                    g = await self.config.guild(guild).all()
                    if g.get("global_testmode", False):
                        continue
                    amount = int(g.get("voice_reward_amount", 1))
                    itv = max(1, int(g.get("voice_reward_interval_sec", 300)))
                    afk_ignore = bool(g.get("afk_excluded", True))
                    self_mute_ignore = bool(g.get("self_mute_excluded", False))
                    afk_id = guild.afk_channel.id if (guild.afk_channel and afk_ignore) else None

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
                                await self.config.user(m).booz.set(int(cur) + amount)
                                self._voice_last[key] = now
            except Exception as e:
                print(f"[BoozyBank VoiceReward] loop error: {e}")
            await asyncio.sleep(TICK)

    # M00#6 CHAT REWARD LISTENER
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if not message.guild or message.author.bot:
            return
        g = await self.config.guild(message.guild).all()
        if g.get("global_testmode", False):
            return
        if message.channel.id in (g.get("excluded_channels") or []):
            return
        cd = max(0, int(g.get("chat_reward_cooldown_sec", 300)))
        amount = int(g.get("chat_reward_amount", 1))
        key = (message.guild.id, message.author.id)
        now = time.time()
        last = self._chat_last.get(key, 0.0)
        if now - last >= cd:
            cur = await self.config.user(message.author).booz()
            await self.config.user(message.author).booz.set(int(cur) + amount)
            self._chat_last[key] = now

    # M00#7 HEALTH CHECK (ook beschikbaar via settings mixin)
    @commands.command()
    async def boozyhealth(self, ctx: commands.Context):
        g = await self.config.guild(ctx.guild).all()
        def alive(t): return (t is not None) and (not t.done()) and (not t.cancelled())
        t1 = getattr(self, "_challenge_task", None)
        t2 = getattr(self, "_random_drop_task", None)
        t3 = getattr(self, "_voice_reward_task", None)
        lines = [
            "🩺 **Boozy health**",
            f"• Challenge-loop: {'running' if alive(t1) else 'stopped'}",
            f"• RandomDrop-loop: {'running' if alive(t2) else 'stopped'}",
            f"• VoiceReward-loop: {'running' if alive(t3) else 'stopped'}",
            f"• Testmodus: {'aan' if g.get('global_testmode', False) else 'uit'}",
            f"• Featured cache dag: {g.get('challenge_featured_cache_day') or '_none_'}",
            f"• Featured vandaag: {', '.join(g.get('challenge_featured_today') or []) or '_none_'}",
            f"• Random drop vandaag: {'ja' if (g.get('random_drop_done_day') == day_key_utc()) else 'nee'}",
        ]
        try:
            tokens = await self.bot.get_shared_api_tokens("openai")
            has_api = bool(tokens.get("api_key"))
            lines.append(f"• OpenAI API key: {'gevonden' if has_api else 'niet gezet'}")
            lines.append(f"• LLM model: {g.get('llm_model','gpt-5-nano')} / timeout {g.get('llm_timeout',45)}s")
        except Exception:
            pass
        await ctx.send("\n".join(lines))
