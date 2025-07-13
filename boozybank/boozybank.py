# BoozyBank with BoozyQuiz integration
# Redbot Cog
# by ChatGPT & dOCTAWAALd 🍻👻

import discord
from redbot.core import commands, Config, checks
import datetime
import asyncio
import aiohttp
import re

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
            "last_quiz": None
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
        now = datetime.datetime.utcnow().timestamp()
        last = await self.config.user(message.author).last_chat()
        if now - last >= 300:
            await self.config.user(message.author).booz.set(
                (await self.config.user(message.author).booz()) + 1
            )
            await self.config.user(message.author).last_chat.set(now)

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

    @commands.command()
    async def boozyquiz(self, ctx, thema: str = "algemeen", moeilijkheid: str = "medium"):
        """Start een quizvraag. Voorbeeld: !boozyquiz cocktails easy"""
        if self.quiz_active:
            return await ctx.send("Er is al een quiz bezig!")
        voice = ctx.author.voice
        if not voice or not voice.channel:
            return await ctx.send("Je moet in een voicekanaal zitten met minstens 3 gebruikers!")
        members = [m for m in voice.channel.members if not m.bot]
        if len(members) < 3:
            return await ctx.send("Minstens 3 gebruikers in voice vereist voor de quiz!")

        await self.start_quiz(ctx.channel, members, thema, moeilijkheid)

    async def start_quiz(self, channel, players, thema, moeilijkheid):
        self.quiz_active = True
        try:
            vraag, antwoord = await self.generate_quiz(thema, moeilijkheid)
            await channel.send(f"🎮 **BoozyQuiz™ Tijd!** Thema: *{thema}* | Moeilijkheid: *{moeilijkheid}*\n**Vraag:** {vraag}")

            def check(m):
                return (
                    m.channel == channel
                    and m.author in players
                    and not m.author.bot
                    and antwoord.lower() in m.content.lower()
                )

            try:
                msg = await self.bot.wait_for("message", check=check, timeout=30.0)
                reward = {"easy": 5, "medium": 10, "hard": 20}.get(moeilijkheid, 10)
                await self.config.user(msg.author).booz.set(
                    (await self.config.user(msg.author).booz()) + reward
                )
                await channel.send(f"🎉 Correct, {msg.author.mention}! Je wint **{reward} Boo'z**.")
            except asyncio.TimeoutError:
                await channel.send("🤦 Niemand wist het... volgende keer beter.")
        finally:
            self.quiz_active = False

    async def generate_quiz(self, thema, moeilijkheid):
        prompt = f"""
Je bent BoozyBoi, een dronken quizmaster. Stel één quizvraag over het onderwerp '{thema}' met moeilijkheid '{moeilijkheid}'. Geef enkel het antwoord apart op de tweede regel.
Voorbeeld:
Vraag: Wat zit er in een mojito?
Antwoord: munt
"""
        async with aiohttp.ClientSession() as session:
            headers = {"Authorization": f"Bearer {self.api_key}"}
            json_data = {
                "model": "gpt-4o",
                "messages": [{"role": "user", "content": prompt}],
                "temperature": 0.7
            }
            async with session.post("https://api.openai.com/v1/chat/completions", headers=headers, json=json_data) as resp:
                data = await resp.json()
                raw = data["choices"][0]["message"]["content"]
                match = re.findall(r"Vraag:(.*?)\nAntwoord:(.*)", raw, re.DOTALL)
                if match:
                    vraag, antwoord = match[0]
                    return vraag.strip(), antwoord.strip()
                return "Wat is 1+1?", "2"

    async def voice_reward_loop(self):
        await self.bot.wait_until_ready()
        self.api_key = (await self.bot.get_shared_api_tokens("openai")).get("api_key")
        while not self.bot.is_closed():
            for guild in self.bot.guilds:
                for vc in guild.voice_channels:
                    members = [m for m in vc.members if not m.bot]
                    if len(members) >= 3:
                        now = datetime.datetime.utcnow().timestamp()
                        dropstamp = await self.config.guild(guild).last_quiz()
                        drop_reset = self.get_today_4am_utc().timestamp()
                        if not dropstamp or dropstamp < drop_reset:
                            gaming = any(any(a.type == discord.ActivityType.playing for a in m.activities) for m in members)
                            if not gaming:
                                await self.config.guild(guild).last_quiz.set(now)
                                channel = vc.guild.system_channel or vc.guild.text_channels[0]
                                await self.start_quiz(channel, members, "algemeen", "medium")
            await asyncio.sleep(60)

    def get_today_4am_utc(self):
        now = datetime.datetime.utcnow()
        reset = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now.hour < 4:
            reset -= datetime.timedelta(days=1)
        return reset
