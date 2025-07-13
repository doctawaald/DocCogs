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

    @commands.command()
    async def booz(self, ctx):
        """Check je saldo aan Boo'z."""
        amount = await self.config.user(ctx.author).booz()
        await ctx.send(f"💰 {ctx.author.mention}, je hebt **{amount} Boo'z**.")

    @commands.command()
    async def give(self, ctx, member: discord.Member, amount: int):
        """Geef iemand Boo'z."""
        if amount <= 0:
            return await ctx.send("Je kunt geen negatieve hoeveelheden geven.")
        sender_bal = await self.config.user(ctx.author).booz()
        if sender_bal < amount:
            return await ctx.send("Niet genoeg Boo'z op je rekening, zuiplap.")

        await self.config.user(ctx.author).booz.set(sender_bal - amount)
        receiver_bal = await self.config.user(member).booz()
        await self.config.user(member).booz.set(receiver_bal + amount)
        await ctx.send(f"💸 {ctx.author.mention} gaf **{amount} Boo'z** aan {member.mention}.")

    @commands.Cog.listener()
    async def on_message(self, message):
        if message.author.bot or not message.guild:
            return
        excluded = await self.config.guild(message.guild).excluded_channels()
        if message.channel.id in excluded:
            return
        now = datetime.datetime.utcnow().timestamp()
        last = await self.config.user(message.author).last_chat()
        if now - last >= 300:
            await self.config.user(message.author).booz.set(
                (await self.config.user(message.author).booz()) + 1
            )
            await self.config.user(message.author).last_chat.set(now)

    @commands.command()
    async def setquizchannel(self, ctx, channel: discord.TextChannel):
        """Stel het kanaal in waar BoozyBoi quizzen mag starten."""
        await self.config.guild(ctx.guild).quiz_channel.set(channel.id)
        await ctx.send(f"Quizkanaal ingesteld op {channel.mention}.")

    @commands.command()
    async def excludechannel(self, ctx, channel: discord.TextChannel):
        """Voeg een kanaal toe aan de uitsluitingslijst voor rewards."""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if channel.id not in excluded:
            excluded.append(channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
        await ctx.send(f"Kanaal {channel.mention} uitgesloten van rewards.")

    @commands.command()
    async def shop(self, ctx):
        """Bekijk de shop met items."""
        shop = await self.config.guild(ctx.guild).shop()
        msg = "**🏩 BoozyShop™**\n"
        for key, item in shop.items():
            msg += f"`{key}` – {item['price']} Boo'z\n"
        await ctx.send(msg)

    @commands.command()
    async def redeem(self, ctx, item: str):
        """Koop iets uit de shop."""
        shop = await self.config.guild(ctx.guild).shop()
        if item not in shop:
            return await ctx.send("Dat item bestaat niet in de shop.")
        price = shop[item]["price"]
        role_id = shop[item]["role_id"]
        bal = await self.config.user(ctx.author).booz()
        if bal < price:
            return await ctx.send("Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(bal - price)

        if role_id:
            role = ctx.guild.get_role(role_id)
            if role:
                await ctx.author.add_roles(role)
                return await ctx.send(f"{ctx.author.mention} kocht **{item}** en kreeg de rol **{role.name}**!")

        await ctx.send(f"{ctx.author.mention} kocht **{item}** voor {price} Boo'z!")

    @commands.command()
    async def boozyleader(self, ctx):
        """Top 10 Boo'z gebruikers."""
        data = await self.config.all_users()
        sorted_data = sorted(data.items(), key=lambda x: x[1]["booz"], reverse=True)[:10]
        msg = "**🥇 Boozy Top 10**\n"
        for i, (uid, entry) in enumerate(sorted_data, 1):
            member = ctx.guild.get_member(int(uid))
            if member:
                msg += f"{i}. {member.display_name} – {entry['booz']} Boo'z\n"
        await ctx.send(msg)

    def get_today_4am_utc(self):
        now = datetime.datetime.utcnow()
        reset = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now.hour < 4:
            reset -= datetime.timedelta(days=1)
        return reset

    @commands.command()
    async def boozyquiz(self, ctx, thema: str = "algemeen", moeilijkheid: str = "medium"):
        """Start handmatig of automatisch een quiz."""
        if self.quiz_active:
            return await ctx.send("Even wachten, er is al een quiz bezig...")

        quiz_channel_id = await self.config.guild(ctx.guild).quiz_channel()
        is_auto = ctx.channel.id == quiz_channel_id and ctx.invoked_with == "boozyquiz"

        if is_auto:
            msg = await ctx.send(f"📣 Klaar voor een quiz over *{thema}*?\nTyp iets om te beginnen!")
            try:
                check = lambda m: m.channel == ctx.channel and not m.author.bot
                await self.bot.wait_for("message", timeout=30.0, check=check)
            except asyncio.TimeoutError:
                return await ctx.send("Niemand reageerde... de quiz is afgeblazen. 😢")

        await self.start_quiz(ctx, ctx.channel, thema, moeilijkheid)

    async def start_quiz(self, ctx, channel, thema, moeilijkheid):
        self.quiz_active = True
        async with channel.typing():
            await channel.send(f"🤔 BoozyBoi denkt na over *{thema}*...")
            vraag, antwoord = await self.generate_quiz(thema, moeilijkheid)

        await channel.send(f"📢 **Vraag:** {vraag}\n*Antwoord in de chat!* Je hebt 15 seconden...")

        def check(m):
            return m.channel == channel and not m.author.bot and is_correct(m.content, antwoord)

        try:
            msg = await self.bot.wait_for("message", timeout=15.0, check=check)
            await channel.send(f"✅ {msg.author.mention} had het juiste antwoord!")
            if str(msg.author.id) != "489127123446005780":
                booz = await self.config.user(msg.author).booz()
                await self.config.user(msg.author).booz.set(booz + 5)
        except asyncio.TimeoutError:
            await channel.send(f"❌ Tijd is om! Het juiste antwoord was: **{antwoord}**")
        self.quiz_active = False

    async def generate_quiz(self, thema, moeilijkheid):
        if not self.api_key:
            return "Wat is 1+1?", "2"

        prompt = f"Genereer een quizvraag in het thema '{thema}' met moeilijkheid '{moeilijkheid}'.\nFormat:\nVraag: ...\nAntwoord: ..."
        headers = {"Authorization": f"Bearer {self.api_key}"}
        json = {
            "model": "gpt-4o-mini",
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 200,
            "temperature": 0.7
        }
        async with aiohttp.ClientSession() as session:
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=json) as r:
                data = await r.json()

        content = data["choices"][0]["message"]["content"]
        vraag = re.findall(r"Vraag:(.*)", content)
        antwoord = re.findall(r"Antwoord:(.*)", content)
        return vraag[0].strip() if vraag else "Onbekende vraag", antwoord[0].strip() if antwoord else "?"


async def setup(bot):
    await bot.add_cog(BoozyBank(bot))
