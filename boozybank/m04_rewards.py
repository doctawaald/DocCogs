# [04] REWARDS — chat/voice rewards + random drop + auto-quiz (met toggles)

import asyncio
import datetime
import random
import discord
from redbot.core import commands
from .m01_utils import cutoff_ts_at_hour_utc

class RewardsMixin:
    # -----------------------
    # Chat rewards (per user)
    # -----------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        # ignore bots / DMs
        if message.author.bot or not message.guild:
            return

        g = await self.config.guild(message.guild).all()

        # geen rewards in uitgesloten kanalen
        if message.channel.id in g.get("excluded_channels", []):
            return

        amount = int(g.get("chat_reward_amount", 1))
        cooldown = int(g.get("chat_reward_cooldown_sec", 300))
        if amount <= 0 or cooldown <= 0:
            return

        now = datetime.datetime.utcnow().timestamp()
        last = await self.config.user(message.author).last_chat()
        if (now - last) < cooldown:
            return

        # beloon
        bal = await self.config.user(message.author).booz()
        await self.config.user(message.author).booz.set(bal + amount)
        await self.config.user(message.author).last_chat.set(now)

    # -------------------------------------------------------
    # Voice rewards + random drop + (optioneel) auto-quizber.
    # Draait als background loop (gestart in m00_core).
    # -------------------------------------------------------
    async def _voice_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    g = await self.config.guild(guild).all()

                    afk_excl = bool(g.get("afk_excluded", True))
                    selfmute_excl = bool(g.get("self_mute_excluded", False))
                    min_humans = int(g.get("min_vc_humans", 3))
                    auto_quiz_enabled = bool(g.get("auto_quiz_enabled", True))

                    # ----------------
                    # Voice rewards
                    # ----------------
                    v_amount = int(g.get("voice_reward_amount", 1))
                    interval = int(g.get("voice_reward_interval_sec", 300))
                    if v_amount > 0 and interval > 0:
                        now_ts = datetime.datetime.utcnow().timestamp()
                        for vc in guild.voice_channels:
                            # AFK-kanaal uitsluiten indien ingesteld
                            if afk_excl and guild.afk_channel and vc.id == guild.afk_channel.id:
                                continue
                            humans = [m for m in vc.members if not m.bot]
                            if selfmute_excl:
                                humans = [
                                    m for m in humans
                                    if not (m.voice and (m.voice.self_mute or m.voice.self_deaf))
                                ]
                            if not humans:
                                continue
                            for user in humans:
                                last_v = await self.config.user(user).last_voice()
                                if (now_ts - last_v) >= interval:
                                    await self.config.user(user).last_voice.set(now_ts)
                                    bal = await self.config.user(user).booz()
                                    await self.config.user(user).booz.set(bal + v_amount)

                    # ----------------
                    # Busiest VC (met filters)
                    # ----------------
                    busiest = None
                    humans_count = 0
                    busiest_humans = []
                    for vc in guild.voice_channels:
                        if afk_excl and guild.afk_channel and vc.id == guild.afk_channel.id:
                            continue
                        humans = [m for m in vc.members if not m.bot]
                        if selfmute_excl:
                            humans = [
                                m for m in humans
                                if not (m.voice and (m.voice.self_mute or m.voice.self_deaf))
                            ]
                        if len(humans) > humans_count:
                            busiest, humans_count, busiest_humans = vc, len(humans), humans

                    # Geen drukke VC → niks doen
                    if not busiest or humans_count < min_humans:
                        continue

                    # Bereken daggrens (reset)
                    reset_hour = int(g.get("quiz_reward_reset_hour", 4))
                    cutoff = cutoff_ts_at_hour_utc(reset_hour)
                    now_ts = datetime.datetime.utcnow().timestamp()

                    # ----------------
                    # Random drop 1×/dag
                    # ----------------
                    last_drop = g.get("last_drop", 0.0)
                    if (not last_drop or last_drop < cutoff) and busiest_humans:
                        drop_amt = int(g.get("random_drop_amount", 10))
                        if drop_amt > 0:
                            lucky = random.choice(busiest_humans)
                            bal = await self.config.user(lucky).booz()
                            await self.config.user(lucky).booz.set(bal + drop_amt)
                            await self.config.guild(guild).last_drop.set(now_ts)

                            # probeer te melden in system channel of eerste tekstkanaal met send-permission
                            txt = guild.system_channel or next(
                                (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                                None,
                            )
                            if txt:
                                try:
                                    await txt.send(f"🎉 Random drop! {lucky.mention} ontvangt **{drop_amt} Boo'z**.")
                                except Exception:
                                    pass

                    # ----------------
                    # (Optioneel) auto-quiz 1×/dag
                    # ----------------
                    if not auto_quiz_enabled:
                        continue

                    last_quiz = g.get("last_quiz", 0.0)
                    if not last_quiz or last_quiz < cutoff:
                        quiz_channel_id = g.get("quiz_channel")
                        channel = guild.get_channel(quiz_channel_id) if quiz_channel_id else None
                        if not channel:
                            continue

                        # laat een uitnodiging vallen
                        ask = None
                        try:
                            ask = await channel.send(
                                "📣 **BoozyQuiz™** Zin in een quiz? "
                                "Reageer binnen **30s** (eender welk bericht) om te starten!"
                            )
                        except Exception:
                            ask = None

                        def check(m: discord.Message) -> bool:
                            return m.channel == channel and not m.author.bot

                        started = False
                        try:
                            await self.bot.wait_for("message", timeout=30, check=check)
                            started = True
                        except asyncio.TimeoutError:
                            started = False

                        # ruim het vraagbericht op (maakt niet uit of autoclean aan staat; dit is pre-quiz)
                        if ask:
                            try:
                                await ask.delete()
                            except Exception:
                                pass

                        if started:
                            await self.config.guild(guild).last_quiz.set(now_ts)
                            # Start een quiz; de quiz cleanup regelt de rest
                            try:
                                await self._start_quiz(
                                    channel=channel,
                                    thema="algemeen",
                                    moeilijkheid="easy",
                                    is_test=False,
                                    count=5,
                                    include_ask=None,      # ask is al verwijderd
                                    initial_msgs=None,     # geen extra initial
                                )
                            except Exception as e:
                                print(f"[BoozyBank voice loop] auto-quiz start error: {e}")

            except Exception as e:
                # zorg dat één fout de loop niet stopt
                print(f"[BoozyBank voice loop] {e}")

            # loop-tick
            await asyncio.sleep(60)
