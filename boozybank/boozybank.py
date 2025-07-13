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

    # BALANCE
    @commands.command()
    async def booz(self, ctx):
        """Check je saldo aan Boo'z."""
        amount = await self.config.user(ctx.author).booz()
        await ctx.send(f"💰 {ctx.author.mention}, je hebt **{amount} Boo'z**.")

    # GIVE
    @commands.command()
    async def give(self, ctx, member: discord.Member, amount: int):
        """Geef iemand Boo'z."""
        if amount <= 0:
            return await ctx.send("Je kunt geen negatieve hoeveelheden geven.")
        bal = await self.config.user(ctx.author).booz()
        if bal < amount:
            return await ctx.send("Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(bal - amount)
        other_bal = await self.config.user(member).booz()
        await self.config.user(member).booz.set(other_bal + amount)
        await ctx.send(f"💸 {ctx.author.mention} gaf **{amount} Boo'z** aan {member.mention}.")

    # CHAT REWARD
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
            await self.config.user(message.author).booz.set((await self.config.user(message.author).booz()) + 1)
            await self.config.user(message.author).last_chat.set(now)

    # SHOP EXCLUDE/INCLUDE
    @commands.command()
    async def excludechannel(self, ctx, channel: discord.TextChannel):
        """Sluit kanaal uit van chat-beloningen."""
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if channel.id not in excluded:
            excluded.append(channel.id)
            await self.config.guild(ctx.guild).excluded_channels.set(excluded)
        await ctx.send(f"Kanaal {channel.mention} is nu uitgesloten.")

    @commands.command()
    async def setquizchannel(self, ctx, channel: discord.TextChannel):
        """Stel kanaal in waar automatisch quizzes mogen starten."""
        await self.config.guild(ctx.guild).quiz_channel.set(channel.id)
        await ctx.send(f"Quizkanaal ingesteld op {channel.mention}.")

    @commands.command()
    async def shop(self, ctx):
        """Laat shopitems zien."""
        shop = await self.config.guild(ctx.guild).shop()
        msg = "**🏩 BoozyShop™**\n"
        for k, item in shop.items():
            msg += f"`{k}` – {item['price']} Boo'z\n"
        await ctx.send(msg)

    @commands.command()
    async def redeem(self, ctx, item: str):
        """Koop item uit shop."""
        shop = await self.config.guild(ctx.guild).shop()
        if item not in shop:
            return await ctx.send("Geen item met die naam.")
        bal = await self.config.user(ctx.author).booz()
        price = shop[item]['price']
        if bal < price:
            return await ctx.send("Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(bal - price)
        rid = shop[item]['role_id']
        if rid:
            role = ctx.guild.get_role(rid)
            if role:
                await ctx.author.add_roles(role)
                return await ctx.send(f"{ctx.author.mention} kocht **{item}** en kreeg rol {role.name}.")
        await ctx.send(f"{ctx.author.mention} kocht **{item}** voor {price} Boo'z.")

    @commands.command()
    async def boozyleader(self, ctx):
        """Top 10 Boo'z gebruikers."""
        data = await self.config.all_users()
        top = sorted(data.items(), key=lambda x: x[1]['booz'], reverse=True)[:10]
        msg = "**🥇 Boozy Top 10**\n"
        for i, (uid, d) in enumerate(top,1):
            m = ctx.guild.get_member(int(uid))
            if m:
                msg += f"{i}. {m.display_name} – {d['booz']} Boo'z\n"
        await ctx.send(msg)

    # QUIZ COMMAND
    @commands.command()
    async def boozyquiz(self, ctx, thema: str = "algemeen", moeilijkheid: str = "medium"):
        """Start handmatig of automatisch een quiz."
        if self.quiz_active:
            return await ctx.send("Even wachten, er is al een quiz bezig.")
        quiz_id = await self.config.guild(ctx.guild).quiz_channel()
        auto = ctx.channel.id == quiz_id
        if auto:
            invite = await ctx.send(f"❓ Klaar voor een quiz over *{thema}*? Typ iets om te starten...")
            try:
                await self.bot.wait_for('message', check=lambda m: m.channel==ctx.channel and not m.author.bot, timeout=30)
            except asyncio.TimeoutError:
                return await ctx.send("Geen reactie, quiz afgelast.")
        await self._do_quiz(ctx.channel, thema, moeilijkheid)

    async def _do_quiz(self, channel, thema, moeilijkheid):
        self.quiz_active = True
        # generate unique
        recent = getattr(self,'_recent_q',[])
        for _ in range(5):
            vraag, ans = await self.generate_quiz(thema, moeilijkheid)
            if vraag not in recent: break
        recent.append(vraag)
        if len(recent)>10: recent.pop(0)
        self._recent_q = recent
        # typing and question
        async with channel.typing():
            await channel.send(f"🤔 BoozyBoi denkt na over *{thema}*...")
            await asyncio.sleep(1)
        await channel.send(f"❔ **Vraag:** {vraag}\nAntwoord in chat, 15s!")
        def check(m): return m.channel==channel and not m.author.bot and is_correct(m.content,ans)
        try:
            m = await self.bot.wait_for('message',check=check,timeout=15)
            await channel.send(f"✅ {m.author.mention} heeft het goed!")
            if m.author.id!=489127123446005780:
                b = await self.config.user(m.author).booz(); await self.config.user(m.author).booz.set(b+10)
        except asyncio.TimeoutError:
            await channel.send(f"❌ Tijd voorbij! Antwoord: **{ans}**")
        self.quiz_active=False

    async def generate_quiz(self, thema, moeilijkheid):
        if not self.api_key: return "Wat is 1+1?","2"
        prompt = f"Genereer quizvraag over '{thema}' ({moeilijkheid}).\nFormat:\nVraag: ...\nAntwoord: ..."
        hdr = {"Authorization":f"Bearer {self.api_key}"}
        data = {"model":"gpt-4o","messages":[{"role":"user","content":prompt}],"temperature":0.7}
        async with aiohttp.ClientSession() as s:
            r = await s.post('https://api.openai.com/v1/chat/completions',headers=hdr,json=data)
            res = await r.json()
        txt = res['choices'][0]['message']['content']
        q = re.search(r"Vraag:(.*)",txt); a = re.search(r"Antwoord:(.*)",txt)
        return q.group(1).strip() if q else "Onbekende vraag", a.group(1).strip() if a else "?"

    # VOICE REWARD & AUTO TRIGGERS
    async def voice_reward_loop(self):
        await self.bot.wait_until_ready()
        self.api_key = (await self.bot.get_shared_api_tokens('openai')).get('api_key')
        while True:
            for g in self.bot.guilds:
                for vc in g.voice_channels:
                    mem = [m for m in vc.members if not m.bot]
                    if len(mem)>=3:
                        now = datetime.datetime.utcnow().timestamp()
                        ld = await self.config.guild(g).last_drop(); lq=await self.config.guild(g).last_quiz()
                        reset=self.get_today_4am_utc().timestamp()
                        if (not ld or ld<reset):
                            await self.config.guild(g).last_drop.set(now)
                            for m in mem: await self.config.user(m).booz.set((await self.config.user(m).booz())+5)
                            c=g.system_channel or g.text_channels[0]
                            await c.send("🎉 Random drop! Iedereen krijgt 5 Boo'z!")
                        if (not lq or lq<reset):
                            # check gaming
                            if not any(any(a.type==discord.ActivityType.playing for a in m.activities) for m in mem):
                                await self.config.guild(g).last_quiz.set(now)
                                qc = await self.config.guild(g).quiz_channel()
                                ch = g.get_channel(qc) or (g.system_channel or g.text_channels[0])
                                await self.boozyquiz.callback(self, types.SimpleNamespace(channel=ch), 'algemeen','medium')
            await asyncio.sleep(60)

    def get_today_4am_utc(self):
        now=datetime.datetime.utcnow(); r=now.replace(hour=4,minute=0,second=0,microsecond=0)
        if now.hour<4: r-=datetime.timedelta(days=1)
        return r

async def setup(bot):
    await bot.add_cog(BoozyBank(bot))
