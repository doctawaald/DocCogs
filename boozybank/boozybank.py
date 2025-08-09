# BoozyBank with BoozyQuiz integration
# Redbot Cog
# by ChatGPT 5 & dOCTAWAALd 🍻👻

import asyncio
import datetime
import json
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import aiohttp
import discord
from redbot.core import Config, checks, commands

TEST_USER_ID = 489127123446005780  # jouw test-id: mag quiz starten solo, maar krijgt geen reward

# -----------------------------
# Helpers
# -----------------------------

def clamp(n: int, low: int, high: int) -> int:
    return max(low, min(high, n))

@dataclass
class MCQ:
    question: str
    options: List[str]  # exactly 4
    answer_letter: str  # "A"/"B"/"C"/"D"

LETTERS = ["A", "B", "C", "D"]

def letter_index(letter: str) -> int:
    return {"A": 0, "B": 1, "C": 2, "D": 3}[letter.upper()]

# -----------------------------
# Fallback vraagbank (als LLM faalt)
# -----------------------------
FALLBACK_BANK: Dict[str, List[MCQ]] = {
    "games": [
        MCQ("Welke studio maakte *The Witcher 3*?", ["CD Projekt Red", "Ubisoft", "Bethesda", "Bioware"], "A"),
        MCQ("Welke console kreeg *Halo* groot?", ["PlayStation 2", "Xbox", "GameCube", "Dreamcast"], "B"),
        MCQ("Wat is de naam van de prinses in *The Legend of Zelda*?", ["Zelda", "Peach", "Samus", "Daisy"], "A"),
    ],
    "alcohol": [
        MCQ("Welke drank is de basis van een klassieke Margarita?", ["Rum", "Wodka", "Tequila", "Gin"], "C"),
        MCQ("Welke cocktail bevat munt, limoen en rum?", ["Mojito", "Negroni", "Old Fashioned", "Margarita"], "A"),
        MCQ("Wat is de basis van een Gin & Tonic?", ["Gin en soda", "Gin en tonic", "Vodka en tonic", "Rum en tonic"], "B"),
    ],
    "films": [
        MCQ("Wie regisseerde *Inception*?", ["Christopher Nolan", "Steven Spielberg", "Ridley Scott", "Denis Villeneuve"], "A"),
        MCQ("In welke film zegt men 'May the Force be with you'?", ["Star Trek", "Star Wars", "Dune", "Avatar"], "B"),
        MCQ("Welke film won Best Picture in 1994?", ["Forrest Gump", "Pulp Fiction", "The Shawshank Redemption", "Braveheart"], "A"),
    ],
    "boardgames": [
        MCQ("Hoeveel velden heeft een schaakbord?", ["64", "81", "72", "100"], "A"),
        MCQ("Welke resource bestaat *niet* in Catan?", ["Wol", "Goud", "Hout", "Klei"], "B"),
        MCQ("In Ticket to Ride verzamel je…", ["Treinkaarten", "Schepen", "Vliegtuigen", "Auto’s"], "A"),
    ],
    "algemeen": [
        MCQ("Welk element heeft het symbool 'O'?", ["Zuurstof", "Goud", "Zilver", "Ijzer"], "A"),
        MCQ("Welke planeet staat het dichtst bij de zon?", ["Aarde", "Mars", "Mercurius", "Venus"], "C"),
        MCQ("Hoeveel is 3 × 3?", ["6", "8", "9", "12"], "C"),
    ],
}

DIFF_REWARD = {"easy": 5, "makkelijk": 5, "medium": 10, "hard": 20}

def normalize_theme(thema: str) -> str:
    t = thema.lower().strip()
    mapping = {
        "board games": "boardgames",
        "board-game": "boardgames",
        "boardgames": "boardgames",
        "games": "games",
        "alcohol": "alcohol",
        "films": "films",
        "movies": "films",
        "algemeen": "algemeen",
        "general": "algemeen",
    }
    return mapping.get(t, t)

# -----------------------------
# Cog
# -----------------------------
class BoozyBank(commands.Cog):
    """BoozyBank™ — Verdien Boo'z, quiz en koop dingen. Geen pay-to-win, iedereen gelijk."""

    def __init__(self, bot):
        self.bot = bot
        self.config = Config.get_conf(self, identifier=69421, force_registration=True)

        default_user = {"booz": 0, "last_chat": 0, "last_voice": 0}
        default_guild = {
            "shop": {
                "soundboard_access": {"price": 100, "role_id": None},
                "color_role": {"price": 50, "role_id": None},
                "boozy_quote": {"price": 25, "role_id": None},
            },
            "last_drop": 0.0,
            "last_quiz": 0.0,
            "excluded_channels": [],   # text channel IDs (no rewards)
            "quiz_channel": None,      # text channel ID
        }

        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        self.quiz_active: bool = False
        self._recent_questions: List[str] = []
        self._api_key: Optional[str] = None
        self._auto_task = self.bot.loop.create_task(self._voice_loop())

        # themapool voor auto quizzes
        self.thema_pool = ["games", "alcohol", "films", "boardgames", "algemeen"]

    def cog_unload(self):
        self._auto_task.cancel()

    # -----------------------------
    # Utils
    # -----------------------------
    async def _get_api_key(self) -> Optional[str]:
        if self._api_key:
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    def _reset_cutoff(self) -> float:
        """Timestamp van laatste reset (04:00 UTC vandaag)."""
        now = datetime.datetime.utcnow()
        reset = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now < reset:
            reset -= datetime.timedelta(days=1)
        return reset.timestamp()

    def _record_recent(self, q: str) -> None:
        self._recent_questions.append(q)
        if len(self._recent_questions) > 12:
            self._recent_questions.pop(0)

    def _is_recent(self, q: str) -> bool:
        return q in self._recent_questions

    # -----------------------------
    # Chat reward (simpele anti-spam: 5 min)
    # -----------------------------
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        excluded = await self.config.guild(message.guild).excluded_channels()
        if message.channel.id in excluded:
            return
        now = datetime.datetime.utcnow().timestamp()
        last = await self.config.user(message.author).last_chat()
        if now - last >= 300:
            bal = await self.config.user(message.author).booz()
            await self.config.user(message.author).booz.set(bal + 1)
            await self.config.user(message.author).last_chat.set(now)

    # -----------------------------
    # Voice monitor: random drop + auto quiz invite (max 1 per nacht)
    # -----------------------------
    async def _voice_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    # vind VC met meeste humans
                    busiest: Optional[discord.VoiceChannel] = None
                    count_humans = 0
                    for vc in guild.voice_channels:
                        humans = [m for m in vc.members if not m.bot]
                        if len(humans) > count_humans:
                            busiest, count_humans = vc, len(humans)
                    if not busiest or count_humans < 3:
                        continue

                    # 1 random drop per nacht
                    now_ts = datetime.datetime.utcnow().timestamp()
                    reset = self._reset_cutoff()
                    last_drop = await self.config.guild(guild).last_drop()
                    if not last_drop or last_drop < reset:
                        lucky = random.choice([m for m in busiest.members if not m.bot])
                        bal = await self.config.user(lucky).booz()
                        await self.config.user(lucky).booz.set(bal + 10)
                        await self.config.guild(guild).last_drop.set(now_ts)
                        txt = guild.system_channel or next((c for c in guild.text_channels if c.permissions_for(guild.me).send_messages), None)
                        if txt:
                            await txt.send(f"🎉 Random drop! {lucky.mention} ontvangt **10 Boo'z**.")

                    # Auto quiz (max 1 per nacht)
                    last_quiz = await self.config.guild(guild).last_quiz()
                    if not last_quiz or last_quiz < reset:
                        quiz_channel_id = await self.config.guild(guild).quiz_channel()
                        channel: Optional[discord.TextChannel] = guild.get_channel(quiz_channel_id) if quiz_channel_id else None
                        if not channel:
                            continue
                        # nodig uit en wacht op iemand
                        thema = random.choice(self.thema_pool)
                        await channel.send(f"📣 **BoozyQuiz™** zin in een snelle quiz over *{thema}*? Typ iets binnen 30s om te starten!")
                        def check(m: discord.Message) -> bool:
                            return m.channel == channel and not m.author.bot
                        try:
                            await self.bot.wait_for("message", timeout=30, check=check)
                        except asyncio.TimeoutError:
                            pass
                        else:
                            # start quiz
                            await self.config.guild(guild).last_quiz.set(now_ts)
                            await self._start_quiz(channel, thema=thema, moeilijkheid="medium", is_test=False)
            except Exception as e:
                print(f"[BoozyBank voice loop] {e}")
            await asyncio.sleep(60)

    # -----------------------------
    # LLM + fallback quizgeneratie (multiple choice, JSON)
    # -----------------------------
    async def _llm_question(self, thema: str, moeilijkheid: str) -> Optional[MCQ]:
        api_key = await self._get_api_key()
        if not api_key:
            return None

        prompt = (
            "Maak één multiple-choice quizvraag als JSON. "
            "Velden: question (string), options (array van exact 4 korte opties), answer (letter A/B/C/D)\n"
            f"Thema: {thema}\nMoeilijkheid: {moeilijkheid}\n"
            "Regels:\n- Korte, duidelijke vraag\n- Opties moeten plausibel zijn\n- Geef *alleen* JSON terug"
        )

        try:
            async with aiohttp.ClientSession() as sess:
                payload = {
                    "model": "gpt-4o-mini",
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.7,
                }
                headers = {"Authorization": f"Bearer {api_key}"}
                async with sess.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=30) as r:
                    data = await r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            # haal JSON-blok uit triple-backticks of plain
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if not m:
                return None
            obj = json.loads(m.group())
            q = obj.get("question", "").strip()
            options = obj.get("options", [])
            ans = obj.get("answer", "").strip().upper()
            if not q or len(options) != 4 or ans not in LETTERS:
                return None
            return MCQ(q, [str(o).strip() for o in options], ans)
        except Exception:
            return None

    def _fallback_question(self, thema: str) -> MCQ:
        t = normalize_theme(thema)
        bank = FALLBACK_BANK.get(t) or FALLBACK_BANK["algemeen"]
        mcq = random.choice(bank)
        return mcq

    async def _generate_mcq(self, thema: str, moeilijkheid: str) -> MCQ:
        # probeer LLM, anders fallback
        mcq = await self._llm_question(thema, moeilijkheid)
        if not mcq:
            mcq = self._fallback_question(thema)
        # simple de-dup
        tries = 0
        while self._is_recent(mcq.question) and tries < 5:
            mcq = self._fallback_question(thema)
            tries += 1
        self._record_recent(mcq.question)
        return mcq

    # -----------------------------
    # Publieke commands
    # -----------------------------
    @commands.command()
    async def booz(self, ctx: commands.Context):
        """Bekijk je saldo (Boo'z)."""
        bal = await self.config.user(ctx.author).booz()
        await ctx.send(f"💰 {ctx.author.mention}, je hebt **{bal} Boo'z**.")

    @commands.command()
    async def give(self, ctx: commands.Context, member: discord.Member, amount: int):
        """Geef Boo'z aan iemand."""
        if member.bot or amount <= 0:
            return await ctx.send("❌ Ongeldige input.")
        your = await self.config.user(ctx.author).booz()
        if your < amount:
            return await ctx.send("❌ Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(your - amount)
        other = await self.config.user(member).booz()
        await self.config.user(member).booz.set(other + amount)
        await ctx.send(f"💸 {ctx.author.mention} gaf **{amount} Boo'z** aan {member.mention}.")

    @commands.command()
    async def shop(self, ctx: commands.Context):
        """Bekijk de BoozyShop™."""
        shop = await self.config.guild(ctx.guild).shop()
        lines = [f"`{k}` — {v['price']} Boo'z" for k, v in shop.items()]
        await ctx.send("🏪 **BoozyShop™**\n" + ("\n".join(lines) if lines else "_Leeg_"))

    @commands.command()
    async def redeem(self, ctx: commands.Context, item: str):
        """Koop een item uit de shop: !redeem soundboard_access"""
        shop = await self.config.guild(ctx.guild).shop()
        key = item.lower().strip()
        if key not in shop:
            return await ctx.send("❌ Dat item bestaat niet.")
        price = int(shop[key]["price"])
        bal = await self.config.user(ctx.author).booz()
        if bal < price:
            return await ctx.send("❌ Niet genoeg Boo'z.")
        await self.config.user(ctx.author).booz.set(bal - price)
        role_id = shop[key].get("role_id")
        if role_id:
            role = ctx.guild.get_role(int(role_id))
            if role:
                await ctx.author.add_roles(role, reason="BoozyShop aankoop")
                return await ctx.send(f"✅ Gekocht: **{key}** — rol **{role.name}** toegevoegd.")
        await ctx.send(f"✅ Gekocht: **{key}** voor {price} Boo'z.")

    @commands.command()
    async def boozyleader(self, ctx: commands.Context):
        """Top 10 Boo'z bezitters in deze server."""
        allu = await self.config.all_users()
        top = sorted(allu.items(), key=lambda kv: kv[1]["booz"], reverse=True)[:10]
        lines = []
        for i, (uid, data) in enumerate(top, 1):
            m = ctx.guild.get_member(int(uid))
            if m:
                lines.append(f"{i}. **{m.display_name}** — {data['booz']} Boo'z")
        await ctx.send("🥇 **Boozy Top 10**\n" + ("\n".join(lines) if lines else "_Nog geen data_"))

    # Admin: kanalen
    @commands.command()
    @checks.admin()
    async def setquizchannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Stel quizkanaal in (default: dit kanaal)."""
        ch = channel or ctx.channel
        await self.config.guild(ctx.guild).quiz_channel.set(ch.id)
        await ctx.send(f"✅ Quizkanaal ingesteld op {ch.mention}")

    @commands.command()
    @checks.admin()
    async def excludechannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Sluit kanaal uit van chat/quiz rewards (default: dit kanaal)."""
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id not in exc:
                exc.append(ch.id)
        await ctx.send(f"🚫 {ch.mention} uitgesloten van rewards.")

    @commands.command()
    @checks.admin()
    async def includechannel(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None):
        """Haal kanaal uit de uitsluitlijst (default: dit kanaal)."""
        ch = channel or ctx.channel
        async with self.config.guild(ctx.guild).excluded_channels() as exc:
            if ch.id in exc:
                exc.remove(ch.id)
        await ctx.send(f"✅ {ch.mention} doet weer mee voor rewards.")

    # -----------------------------
    # Quiz commands
    # -----------------------------
    @commands.command()
    async def boozyquiz(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "medium"):
        """
        Start een BoozyQuiz™. Vereist 3+ humans in je voice-kanaal,
        behalve voor TEST_USER_ID (mag testen, maar krijgt geen reward).
        """
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")

        # voice check
        allow_test = ctx.author.id == TEST_USER_ID
        vc = ctx.author.voice.channel if ctx.author.voice else None
        humans = [m for m in (vc.members if vc else []) if not m.bot] if vc else []
        if not allow_test and len(humans) < 3:
            return await ctx.send("🔇 Je moet met minstens **3** gebruikers in een voice-kanaal zitten om te quizzen.")

        # uitgesloten kanaal check
        excluded = await self.config.guild(ctx.guild).excluded_channels()
        if ctx.channel.id in excluded:
            return await ctx.send("🚫 Dit kanaal is uitgesloten van quiz-beloningen.")

        # start
        is_test = allow_test
        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid, is_test=is_test)

    # -----------------------------
    # Kern quiz flow
    # -----------------------------
    async def _start_quiz(self, channel: discord.TextChannel, thema: str, moeilijkheid: str, is_test: bool):
        """Genereer vraag, toon MC, wacht op antwoord en beloon."""
        thema = normalize_theme(thema)
        self.quiz_active = True
        try:
            async with channel.typing():
                mcq = await self._generate_mcq(thema, moeilijkheid)

            opties_str = "\n".join([f"{LETTERS[i]}. {mcq.options[i]}" for i in range(4)])
            await channel.send(f"❓ **{mcq.question}**\n*(antwoord met A/B/C/D — 20s)*\n{opjes_str if (opjes_str := opties_str) else opties_str}")

            def check(m: discord.Message) -> bool:
                return (
                    m.channel == channel
                    and not m.author.bot
                    and m.content.upper().strip() in LETTERS
                )

            try:
                msg = await self.bot.wait_for("message", timeout=20, check=check)
            except asyncio.TimeoutError:
                correct_text = mcq.options[letter_index(mcq.answer_letter)]
                return await channel.send(f"⌛ Tijd voorbij. Antwoord: **{mcq.answer_letter}** — {correct_text}")

            if msg.content.upper().strip() == mcq.answer_letter.upper():
                # reward?
                reward = DIFF_REWARD.get(moeilijkheid.lower(), 10)
                if is_test or msg.author.id == TEST_USER_ID:
                    reward = 0
                excluded = await self.config.guild(channel.guild).excluded_channels()
                if channel.id in excluded:
                    reward = 0

                if reward > 0:
                    bal = await self.config.user(msg.author).booz()
                    await self.config.user(msg.author).booz.set(bal + reward)
                await channel.send(f"✅ Correct, {msg.author.mention}! Je wint **{reward} Boo'z**.")
            else:
                correct_text = mcq.options[letter_index(mcq.answer_letter)]
                await channel.send(f"❌ Nope. Antwoord was **{mcq.answer_letter}** — {correct_text}")

        finally:
            self.quiz_active = False
