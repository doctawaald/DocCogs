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

    def get_today_4am_utc(self):
        now = datetime.datetime.utcnow()
        if now.hour < 4:
            now = now - datetime.timedelta(days=1)
        return now.replace(hour=4, minute=0, second=0, microsecond=0)

    async def fetch_question(self, thema, moeilijkheid):
        async with aiohttp.ClientSession() as session:
            prompt = f"Geef me een quizvraag over het thema '{thema}' met moeilijkheid '{moeilijkheid}'. Geef enkel de vraag op de eerste regel en het antwoord op de tweede."
            headers = {"Authorization": f"Bearer {self.api_key}"}
            json_data = {
                "model": "gpt-4o-mini",
                "messages": [
                    {"role": "user", "content": prompt}
                ]
            }
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=json_data) as resp:
                data = await resp.json()
                content = data["choices"][0]["message"]["content"]
                match = re.findall(r"Vraag:(.*?)\\nAntwoord:(.*)", content, re.DOTALL)
                if match:
                    vraag, antwoord = match[0]
                else:
                    parts = content.split("\n")
                    vraag = parts[0] if parts else "Wat is 1+1?"
                    antwoord = parts[1] if len(parts) > 1 else "2"
                return vraag.strip(), antwoord.strip()

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
                vraag, antwoord = await self.fetch_question(thema, moeilijkheid)

            await ctx.send(f"❓**{vraag}** (15s)\n*Antwoord in de chat!*")

            def antwoord_check(m):
                return m.channel == ctx.channel and not m.author.bot

            try:
                msg = await self.bot.wait_for("message", check=antwoord_check, timeout=15.0)
                if is_correct(msg.content, antwoord):
                    await ctx.send(f"✅ Correct, {msg.author.mention}! Dat verdient 5 Boo'z.")
                    saldo = await self.config.user(msg.author).booz()
                    await self.config.user(msg.author).booz.set(saldo + 5)
                else:
                    await ctx.send(f"❌ Nope. Het juiste antwoord was: **{antwoord}**")
            except asyncio.TimeoutError:
                await ctx.send(f"⌛ Niemand heeft geantwoord. Het juiste antwoord was: **{antwoord}**")
        finally:
            self.quiz_active = False

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

    @commands.command()
    @commands.has_permissions(manage_guild=True)
    async def setquizchannel(self, ctx):
        """Stel het huidige kanaal in als quizkanaal."""
        await self.config.guild(ctx.guild).quiz_channel.set(ctx.channel.id)
        await ctx.send(f"✅ Quizkanaal ingesteld op {ctx.channel.mention}.")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def excludechannel(self, ctx):
        """Sluit dit kanaal uit van rewards."""
        current = await self.config.guild(ctx.guild).excluded_channels()
        if ctx.channel.id not in current:
            current.append(ctx.channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(current)
            await ctx.send("🚫 Dit kanaal wordt nu genegeerd voor rewards.")
        else:
            await ctx.send("⚠️ Dit kanaal stond al op de uitsluitlijst.")

    @commands.command()
    @commands.has_permissions(manage_channels=True)
    async def includechannel(self, ctx):
        """Verwijder dit kanaal uit de uitsluitlijst."""
        current = await self.config.guild(ctx.guild).excluded_channels()
        if ctx.channel.id in current:
            current.remove(ctx.channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(current)
            await ctx.send("✅ Dit kanaal doet weer mee met rewards.")
        else:
            await ctx.send("ℹ️ Dit kanaal stond niet op de uitsluitlijst.")
