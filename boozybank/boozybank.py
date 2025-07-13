# BoozyBank with BoozyQuiz integration
# Redbot Cog
# by ChatGPT & dOCTAWAALd 🍻👻

import discord
from redbot.core import commands, Config, checks
from difflib import SequenceMatcher
from random import randint
import datetime
import asyncio
import aiohttp
import re


def is_correct(user_input, correct_answer):
    ratio = SequenceMatcher(None, user_input.lower(), correct_answer.lower()).ratio()
    return correct_answer.lower() in user_input.lower() or ratio > 0.8


class BoozyBank(commands.Cog):
    """BoozyBank™ - Verdien Boo'z, koop chaos en quiz je kapot."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69421, force_registration=True)
        default_user = {"booz": 0, "last_chat": 0, "last_voice": 0}
        default_guild = {
            "shop": {
                "soundboard_access": {"price": 100, "role_id": None},
                "color_role": {"price": 50, "role_id": None},
                "boozy_quote": {"price": 25, "role_id": None}
            },
            "last_drop": None,
            "last_quiz": None,
            "excluded_channels": [],
            "quiz_channel": None
        }

        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        self.voice_check_task = self.bot.loop.create_task(self.voice_reward_loop())
        self.quiz_active = False
        self.api_key = None

    def cog_unload(self):
        self.voice_check_task.cancel()

    async def voice_reward_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            now = datetime.datetime.utcnow()
            for guild in self.bot.guilds:
                try:
                    voice_channels = [vc for vc in guild.voice_channels if vc.members and not any(m.bot for m in vc.members)]
                    if not voice_channels:
                        continue
                    channel = max(voice_channels, key=lambda c: len([m for m in c.members if not m.bot]))
                    users = [m for m in channel.members if not m.bot]
                    if not users:
                        continue
                    if any(str(u.id) == "489127123446005780" for u in users):
                        continue

                    for user in users:
                        last = await self.config.user(user).last_voice()
                        if (now.timestamp() - last) > 300:
                            await self.config.user(user).last_voice.set(now.timestamp())
                            booz = await self.config.user(user).booz()
                            await self.config.user(user).booz.set(booz + 1)

                    last_drop = await self.config.guild(guild).last_drop()
                    last_quiz = await self.config.guild(guild).last_quiz()
                    reset_time = self.get_today_4am_utc().timestamp()

                    if (not last_drop or last_drop < reset_time) and len(users) > 2:
                        await self.config.guild(guild).last_drop.set(now.timestamp())
                        lucky = users[randint(0, len(users)-1)]
                        booz = await self.config.user(lucky).booz()
                        await self.config.user(lucky).booz.set(booz + 10)
                        quiz_chan_id = await self.config.guild(guild).quiz_channel()
                        if quiz_chan_id:
                            quiz_chan = guild.get_channel(quiz_chan_id)
                            if (not last_quiz or last_quiz < reset_time):
                                await self.config.guild(guild).last_quiz.set(now.timestamp())
                                ctx = await self.bot.get_context(await quiz_chan.send("🎲 Tijd voor een BoozyQuiz!"))
                                await self.boozyquiz(ctx, auto=True)

                except Exception as e:
                    print(f"[BoozyBank VC loop error] {e}")
            await asyncio.sleep(60)

    @commands.command()
    async def booz(self, ctx):
        """Bekijk je saldo."""
        saldo = await self.config.user(ctx.author).booz()
        await ctx.send(f"💰 {ctx.author.display_name}, je hebt **{saldo} Boo'z**.")

    @commands.command()
    async def shop(self, ctx):
        """Toon beschikbare items in de shop."""
        shop = await self.config.guild(ctx.guild).shop()
        desc = "\n".join([f"**{item}** - {info['price']} Boo'z" for item, info in shop.items()])
        await ctx.send(f"🛒 **Shop:**\n{desc}")

    @commands.command()
    async def redeem(self, ctx, item: str):
        """Koop iets uit de shop."""
        shop = await self.config.guild(ctx.guild).shop()
        item = item.lower()
        if item not in shop:
            return await ctx.send("❌ Item niet gevonden in de shop.")

        price = shop[item]["price"]
        saldo = await self.config.user(ctx.author).booz()
        if saldo < price:
            return await ctx.send("❌ Je hebt niet genoeg Boo'z.")

        await self.config.user(ctx.author).booz.set(saldo - price)
        await ctx.send(f"✅ Je hebt **{item}** gekocht voor {price} Boo'z!")

    async def boozyquiz(self, ctx, thema: str = "algemeen", moeilijkheid: str = "medium", auto: bool = False):
        if self.quiz_active:
            return await ctx.send("Er loopt al een quiz, even geduld...")
        self.quiz_active = True

        if auto:
            await ctx.send(f"🤔 BoozyBoi denkt na over een quiz over **{thema}**...")
            await asyncio.sleep(2)
            await ctx.send(f"📢 Klaar voor een quiz over **{thema}**? Type iets om te starten!")

            def check(m):
                return m.channel == ctx.channel and not m.author.bot

            try:
                await self.bot.wait_for("message", check=check, timeout=60)
            except asyncio.TimeoutError:
                await ctx.send("Niemand reageerde... Geen quiz vandaag 😔")
                self.quiz_active = False
                return

        question, answer = await self.generate_quiz_question(thema, moeilijkheid)
        async with ctx.typing():
            await asyncio.sleep(1.5)
        await ctx.send(f"**Vraag:** {question}\nAntwoord binnen 20 seconden!")

        def check(m):
            return m.channel == ctx.channel and not m.author.bot

        try:
            msg = await self.bot.wait_for("message", check=check, timeout=20)
            if is_correct(msg.content, answer):
                await ctx.send(f"✅ Correct, {msg.author.mention}! Je wint 5 Boo'z.")
                booz = await self.config.user(msg.author).booz()
                await self.config.user(msg.author).booz.set(booz + 5)
            else:
                await ctx.send(f"❌ Nope, het juiste antwoord was: **{answer}**")
        except asyncio.TimeoutError:
            await ctx.send(f"⏱️ Tijd om! Het juiste antwoord was: **{answer}**")

        self.quiz_active = False

    async def generate_quiz_question(self, thema, moeilijkheid):
        if not self.api_key:
            return "Wat is 1+1?", "2"

        prompt = f"Geef één multiple choice quizvraag over het onderwerp '{thema}' met moeilijkheid '{moeilijkheid}'. Geef enkel de vraagtekst en het correcte antwoord op aparte regels."
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
        data = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}]
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=data) as resp:
                res = await resp.json()
                output = res["choices"][0]["message"]["content"]
                match = re.findall(r"Vraag:(.*?)\nAntwoord:(.*)", output, re.DOTALL)
                if match:
                    return match[0][0].strip(), match[0][1].strip()
                return "Wat is 1+1?", "2"

    def get_today_4am_utc(self):
        now = datetime.datetime.utcnow()
        reset = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now.hour < 4:
            reset -= datetime.timedelta(days=1)
        return reset


async def setup(bot):
    await bot.add_cog(BoozyBank(bot))
