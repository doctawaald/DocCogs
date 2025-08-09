import asyncio
import datetime
import random
import discord
from redbot.core import commands
from .01_utils import cutoff_ts_at_hour_utc

class RewardsMixin:
    # ------ Chat rewards ------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        g = await self.config.guild(message.guild).all()
        if message.channel.id in g.get("excluded_channels", []):
            return
        now = datetime.datetime.utcnow().timestamp()
        last = await self.config.user(message.author).last_chat()
        cooldown = int(g.get("chat_reward_cooldown_sec", 300))
        amount = int(g.get("chat_reward_amount", 1))
        if cooldown > 0 and amount > 0 and (now - last) >= cooldown:
            bal = await self.config.user(message.author).booz()
            await self.config.user(message.author).booz.set(bal + amount)
            await self.config.user(message.author).last_chat.set(now)

    # ------ Voice loop: voice rewards + random drop + auto-quiz ------
    async def _voice_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    g = await self.config.guild(guild).all()

                    # Voice rewards: loop alle VC's
                    interval = int(g.get("voice_reward_interval_sec", 300))
                    v_amount = int(g.get("voice_reward_amount", 1))
                    now_ts = datetime.datetime.utcnow().timestamp()
                    for vc in guild.voice_channels:
                        humans = [m for m in vc.members if not m.bot]
                        if not humans:
                            continue
                        for user in humans:
                            last_v = await self.config.user(user).last_voice()
                            if interval > 0 and v_amount > 0 and (now_ts - last_v) >= interval:
                                await self.config.user(user).last_voice.set(now_ts)
                                bal = await self.config.user(user).booz()
                                await self.config.user(user).booz.set(bal + v_amount)

                    # Drukste VC bepalen voor de rest
                    busiest = None
                    humans_count = 0
                    for vc in guild.voice_channels:
                        humans = [m for m in vc.members if not m.bot]
                        if len(humans) > humans_count:
                            busiest, humans_count = vc, len(humans)

                    if not busiest or humans_count < 3:
                        continue

                    hour = int(g.get("quiz_reward_reset_hour", 4))
                    cutoff = cutoff_ts_at_hour_utc(hour)
                    now_ts = datetime.datetime.utcnow().timestamp()

                    # Random drop 1×/dag
                    last_drop = g.get("last_drop", 0.0)
                    if not last_drop or last_drop < cutoff:
                        lucky = random.choice([m for m in busiest.members if not m.bot])
                        drop_amt = int(g.get("random_drop_amount", 10))
                        if drop_amt > 0:
                            bal = await self.config.user(lucky).booz()
                            await self.config.user(lucky).booz.set(bal + drop_amt)
                        await self.config.guild(guild).last_drop.set(now_ts)
                        txt = guild.system_channel or next(
                            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                            None,
                        )
                        if txt and drop_amt > 0:
                            try:
                                await txt.send(f"🎉 Random drop! {lucky.mention} ontvangt **{drop_amt} Boo'z**.")
                            except Exception:
                                pass

                    # Auto-quiz 1×/dag (met opt-in bericht)
                    last_quiz = g.get("last_quiz", 0.0)
                    if not last_quiz or last_quiz < cutoff:
                        quiz_channel_id = g.get("quiz_channel")
                        channel = guild.get_channel(quiz_channel_id) if quiz_channel_id else None
                        if not channel:
                            continue
                        try:
                            thema = random.choice(getattr(self, "thema_pool", ["algemeen"]))
                            ask = await channel.send(
                                f"📣 **BoozyQuiz™** Zin in een quiz over *{thema}*? Reageer binnen **30s** om te starten!"
                            )
                        except Exception:
                            ask = None
                        def check(m: discord.Message) -> bool:
                            return m.channel == channel and not m.author.bot
                        try:
                            await self.bot.wait_for("message", timeout=30, check=check)
                        except asyncio.TimeoutError:
                            if ask:
                                try: await ask.delete()
                                except Exception: pass
                        else:
                            await self.config.guild(guild).last_quiz.set(now_ts)
                            await self._start_quiz(channel, thema=thema, moeilijkheid="hard", is_test=False, count=5, include_ask=ask)
            except Exception as e:
                print(f"[BoozyBank voice loop] {e}")
            await asyncio.sleep(60)
