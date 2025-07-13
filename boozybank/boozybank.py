# BoozyBank with BoozyQuiz integration
# Redbot Cog
# by ChatGPT & dOCTAWAALd 🍻👻

import discord
from redbot.core import commands, Config, checks
from difflib import SequenceMatcher
from random import randint, choice
import datetime
import asyncio
import aiohttp
import re
import json


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
        self.thema_pool = ["games", "alcohol", "films", "board games", "algemeen"]

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
                                thema = choice(self.thema_pool)
                                ctx = await self.bot.get_context(await quiz_chan.send("🎲 Tijd voor een BoozyQuiz!"))
                                await self.boozyquiz(ctx, thema=thema, auto=True)

                except Exception as e:
                    print(f"[BoozyBank VC loop error] {e}")
            await asyncio.sleep(60)

    def get_today_4am_utc(self):
        now = datetime.datetime.utcnow()
        if now.hour < 4:
            now = now - datetime.timedelta(days=1)
        return now.replace(hour=4, minute=0, second=0, microsecond=0)

    async def fetch_question(self, thema, moeilijkheid):
        async with aiohttp.ClientSession() as session:
            prompt = f"Geef een multiplechoice quizvraag over '{thema}' met moeilijkheid '{moeilijkheid}'. Geef het als JSON met de velden: 'question', 'options' (lijst van 4 strings), en 'answer' (de juiste optie A/B/C/D)."
            headers = {"Authorization": f"Bearer {self.api_key}"}
            json_data = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=json_data) as resp:
                data = await resp.json()
                try:
                    content = data["choices"][0]["message"]["content"]
                    parsed = re.search(r'{.*}', content, re.DOTALL)
                    if parsed:
                        parsed_json = json.loads(parsed.group())
                        return parsed_json["question"], parsed_json["options"], parsed_json["answer"]
                except Exception:
                    return "Wat is 1+1?", ["1", "2", "3", "4"], "B"

    @commands.command()
    async def boozyquiz(self, ctx, thema: str = "algemeen", moeilijkheid: str = "medium", auto: bool = False):
        """Start handmatig of automatisch een quiz."""
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig...")

        quiz_chan_id = await self.config.guild(ctx.guild).quiz_channel()
        if auto and ctx.channel.id != quiz_chan_id:
            return

        if auto:
            await ctx.send(f"🤔 BoozyBoi denkt na over een quiz over **{thema}**...")
            await asyncio.sleep(3)
            preview = await ctx.send(f"📣 Zin in een quiz over **{thema}**? Reageer met iets binnen 15s om te starten!")

            def check(m):
                return m.channel == ctx.channel and not m.author.bot

            try:
                await self.bot.wait_for("message", check=check, timeout=15.0)
            except asyncio.TimeoutError:
                return await ctx.send("⏹️ Geen interesse, quiz afgebroken.")

        self.quiz_active = True
        try:
            async with ctx.channel.typing():
                vraag, opties, correct = await self.fetch_question(thema, moeilijkheid)

            letters = ["A", "B", "C", "D"]
            opties_str = "\n".join([f"{letters[i]}. {opties[i]}" for i in range(4)])
            await ctx.send(f"❓**{vraag}** (antwoord met A/B/C/D - 15s)\n{opties_str}")

            def antwoord_check(m):
                return m.channel == ctx.channel and not m.author.bot and m.content.upper() in letters

            try:
                msg = await self.bot.wait_for("message", check=antwoord_check, timeout=15.0)
                if msg.content.upper() == correct.upper():
                    await ctx.send(f"✅ Correct, {msg.author.mention}! Dat verdient 5 Boo'z.")
                    saldo = await self.config.user(msg.author).booz()
                    await self.config.user(msg.author).booz.set(saldo + 5)
                else:
                    await ctx.send(f"❌ Nope. Het juiste antwoord was **{correct.upper()}**: {opties[letters.index(correct.upper())]}")
            except asyncio.TimeoutError:
                await ctx.send(f"⌛ Niemand heeft geantwoord. Het juiste antwoord was **{correct.upper()}**: {opties[letters.index(correct.upper())]}")
        finally:
            self.quiz_active = False

    @commands.command()
    async def bal(self, ctx):
        """Bekijk je Boo'z saldo."""
        saldo = await self.config.user(ctx.author).booz()
        await ctx.send(f"💰 {ctx.author.mention}, je hebt {saldo} Boo'z.")

    @commands.command()
    async def setquizchannel(self, ctx):
        """Stel dit kanaal in als quizkanaal."""
        await self.config.guild(ctx.guild).quiz_channel.set(ctx.channel.id)
        await ctx.send("✅ Quizkanaal ingesteld.")

    @commands.command()
    async def excludechannel(self, ctx):
        """Sluit dit kanaal uit van beloningen."""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if ctx.channel.id not in excluded:
            excluded.append(ctx.channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
            await ctx.send("❌ Dit kanaal is nu uitgesloten van beloningen.")

    @commands.command()
    async def includechannel(self, ctx):
        """Sta dit kanaal opnieuw toe voor beloningen."""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if ctx.channel.id in excluded:
            excluded.remove(ctx.channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
            await ctx.send("✅ Dit kanaal is opnieuw toegestaan voor beloningen.")
