# BoozyBank with BoozyQuiz integration + Auto Cleanup
# Redbot Cog
# by ChatGPT 5 & dOCTAWAALd 🍻👻

import asyncio
import datetime
import json
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional

import aiohttp
import discord
from redbot.core import Config, checks, commands

TEST_USER_ID = 489127123446005780  # jouw test-id: mag solo testen, maar krijgt geen reward
LETTERS = ["A", "B", "C", "D"]

# ---------- Helpers ----------
@dataclass
class MCQ:
    question: str
    options: List[str]   # exactly 4, sanitized (geen labels)
    answer_letter: str   # "A"/"B"/"C"/"D"

def letter_index(letter: str) -> int:
    return {"A": 0, "B": 1, "C": 2, "D": 3}[letter.upper()]

OPTION_PREFIX_RE = re.compile(
    r"""^\s*(
        [A-Da-d] | \d{1,2}
    )\s*[\.\)\:\-]\s*""",
    re.VERBOSE,
)

def sanitize_option(text: str) -> str:
    t = str(text or "").strip()
    t = OPTION_PREFIX_RE.sub("", t)
    t = OPTION_PREFIX_RE.sub("", t)
    return t.strip()

def sanitize_options(opts: List[str]) -> List[str]:
    out = [sanitize_option(x) for x in (opts or [])]
    while len(out) < 4:
        out.append("—")
    return out[:4]

def normalize_theme(thema: str) -> str:
    t = (thema or "").lower().strip()
    mapping = {
        "board games": "boardgames", "board-game": "boardgames", "boardgames": "boardgames",
        "games": "games", "alcohol": "alcohol", "films": "films", "movies": "films",
        "algemeen": "algemeen", "general": "algemeen",
    }
    return mapping.get(t, t or "algemeen")

DIFF_REWARD = {"easy": 5, "makkelijk": 5, "medium": 10, "hard": 20}

# ---------- Fallback vraagbank ----------
FALLBACK_BANK: Dict[str, List[MCQ]] = {
    "games": [
        MCQ("Welke studio maakte *The Witcher 3*?", ["CD Projekt Red", "Ubisoft", "Bethesda", "Bioware"], "A"),
        MCQ("Welke console kreeg *Halo* groot?", ["PlayStation 2", "Xbox", "GameCube", "Dreamcast"], "B"),
        MCQ("Hoe heet de prinses in *The Legend of Zelda*?", ["Zelda", "Peach", "Samus", "Daisy"], "A"),
    ],
    "alcohol": [
        MCQ("Basisdrank van een klassieke Margarita?", ["Rum", "Wodka", "Tequila", "Gin"], "C"),
        MCQ("Cocktail met munt, limoen en rum?", ["Mojito", "Negroni", "Old Fashioned", "Margarita"], "A"),
        MCQ("Wat zit er in een Gin & Tonic?", ["Gin en soda", "Gin en tonic", "Vodka en tonic", "Rum en tonic"], "B"),
    ],
    "films": [
        MCQ("Wie regisseerde *Inception*?", ["Christopher Nolan", "Steven Spielberg", "Ridley Scott", "Denis Villeneuve"], "A"),
        MCQ("Uit welke serie komt 'May the Force be with you'?", ["Star Trek", "Star Wars", "Dune", "Avatar"], "B"),
        MCQ("Welke film won Best Picture in 1994?", ["Forrest Gump", "Pulp Fiction", "The Shawshank Redemption", "Braveheart"], "A"),
    ],
    "boardgames": [
        MCQ("Hoeveel velden heeft een schaakbord?", ["64", "81", "72", "100"], "A"),
        MCQ("Welke resource bestaat niet in *Catan*?", ["Wol", "Goud", "Hout", "Klei"], "B"),
        MCQ("In Ticket to Ride verzamel je…", ["Treinkaarten", "Schepen", "Vliegtuigen", "Auto’s"], "A"),
    ],
    "algemeen": [
        MCQ("Symbool van zuurstof?", ["O", "Au", "Ag", "Fe"], "A"),
        MCQ("Dichtst bij de zon?", ["Aarde", "Mars", "Mercurius", "Venus"], "C"),
        MCQ("3 × 3 = ?", ["6", "8", "9", "12"], "C"),
    ],
}

# ---------- Cog ----------
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
            "excluded_channels": [],
            "quiz_channel": None,
            "quiz_autoclean": True,     # <-- nieuw
            "quiz_clean_delay": 5       # seconden
        }
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        self.quiz_active = False
        self._recent_questions: List[str] = []
        self._api_key: Optional[str] = None
        self._auto_task = self.bot.loop.create_task(self._voice_loop())
        self.thema_pool = ["games", "alcohol", "films", "boardgames", "algemeen"]

    def cog_unload(self):
        self._auto_task.cancel()

    # ---------- Utils ----------
    async def _get_api_key(self) -> Optional[str]:
        if self._api_key:
            return self._api_key
        tokens = await self.bot.get_shared_api_tokens("openai")
        self._api_key = tokens.get("api_key")
        return self._api_key

    def _reset_cutoff(self) -> float:
        now = datetime.datetime.utcnow()
        reset = now.replace(hour=4, minute=0, second=0, microsecond=0)
        if now < reset:
            reset -= datetime.timedelta(days=1)
        return reset.timestamp()

    def _record_recent(self, q: str) -> None:
        self._recent_questions.append(q)
        if len(self._recent_questions) > 12:
            self._recent_questions.pop(0)

    # ---------- Chat reward ----------
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

    # ---------- Voice loop ----------
    async def _voice_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    busiest = None
                    humans_count = 0
                    for vc in guild.voice_channels:
                        humans = [m for m in vc.members if not m.bot]
                        if len(humans) > humans_count:
                            busiest, humans_count = vc, len(humans)
                    if not busiest or humans_count < 3:
                        continue

                    now_ts = datetime.datetime.utcnow().timestamp()
                    reset = self._reset_cutoff()

                    # random drop 1× per nacht
                    last_drop = await self.config.guild(guild).last_drop()
                    if not last_drop or last_drop < reset:
                        lucky = random.choice([m for m in busiest.members if not m.bot])
                        bal = await self.config.user(lucky).booz()
                        await self.config.user(lucky).booz.set(bal + 10)
                        await self.config.guild(guild).last_drop.set(now_ts)
                        txt = guild.system_channel or next(
                            (c for c in guild.text_channels if c.permissions_for(guild.me).send_messages),
                            None,
                        )
                        if txt:
                            await txt.send(f"🎉 Random drop! {lucky.mention} ontvangt **10 Boo'z**.")

                    # auto quiz 1× per nacht
                    last_quiz = await self.config.guild(guild).last_quiz()
                    if not last_quiz or last_quiz < reset:
                        quiz_channel_id = await self.config.guild(guild).quiz_channel()
                        channel = guild.get_channel(quiz_channel_id) if quiz_channel_id else None
                        if not channel:
                            continue
                        thema = random.choice(self.thema_pool)
                        await channel.send(f"📣 **BoozyQuiz™** zin in een snelle quiz over *{thema}*? Typ iets binnen 30s om te starten!")
                        def check(m: discord.Message) -> bool:
                            return m.channel == channel and not m.author.bot
                        try:
                            await self.bot.wait_for("message", timeout=30, check=check)
                        except asyncio.TimeoutError:
                            pass
                        else:
                            await self.config.guild(guild).last_quiz.set(now_ts)
                            await self._start_quiz(channel, thema=thema, moeilijkheid="medium", is_test=False)
            except Exception as e:
                print(f"[BoozyBank voice loop] {e}")
            await asyncio.sleep(60)

    # ---------- Quiz generatie ----------
    async def _llm_question(self, thema: str, moeilijkheid: str) -> Optional[MCQ]:
        api_key = await self._get_api_key()
        if not api_key:
            return None

        prompt = (
            "Maak één multiple-choice quizvraag als JSON. "
            "Velden: question (string), options (array van exact 4 korte opties), answer (letter A/B/C/D). "
            "Lever *alleen JSON* zonder extra tekst.\n"
            f"Thema: {thema}\nMoeilijkheid: {moeilijkheid}\n"
            "- Opties mogen geen labels zoals 'A.' of '1)' bevatten.\n"
            "- Houd het kort."
        )

        try:
            async with aiohttp.ClientSession() as sess:
                payload = {"model": "gpt-4o-mini", "messages": [{"role": "user", "content": prompt}], "temperature": 0.7}
                headers = {"Authorization": f"Bearer {api_key}"}
                async with sess.post("https://api.openai.com/v1/chat/completions", json=payload, headers=headers, timeout=30) as r:
                    data = await r.json()
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            m = re.search(r"\{.*\}", content, re.DOTALL)
            if not m:
                return None
            obj = json.loads(m.group())
            q = str(obj.get("question", "")).strip()
            options = sanitize_options(obj.get("options", []))
            ans = str(obj.get("answer", "")).strip().upper()
            if not q or len(options) != 4 or ans not in LETTERS:
                return None
            return MCQ(q, options, ans)
        except Exception:
            return None

    def _fallback_question(self, thema: str) -> MCQ:
        t = normalize_theme(thema)
        bank = FALLBACK_BANK.get(t) or FALLBACK_BANK["algemeen"]
        mcq = random.choice(bank)
        return MCQ(mcq.question, sanitize_options(mcq.options), mcq.answer_letter)

    async def _generate_mcq(self, thema: str, moeilijkheid: str) -> MCQ:
        mcq = await self._llm_question(thema, moeilijkheid)
        if not mcq:
            mcq = self._fallback_question(thema)
        tries = 0
        while mcq.question in self._recent_questions and tries < 5:
            mcq = self._fallback_question(thema)
            tries += 1
        self._record_recent(mcq.question)
        return mcq

    # ---------- Basis commands ----------
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

    # ---------- Kanaal/clean settings ----------
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

    @commands.command()
    async def boozysettings(self, ctx: commands.Context):
        """Toon huidige BoozyBank-instellingen."""
        g = await self.config.guild(ctx.guild).all()
        qch = ctx.guild.get_channel(g["quiz_channel"]) if g["quiz_channel"] else None
        excluded = [ctx.guild.get_channel(cid) for cid in g["excluded_channels"]]
        exc_names = ", ".join(ch.mention for ch in excluded if ch) or "_geen_"
        await ctx.send(
            f"🛠 **Boozy settings**\n"
            f"• Quizkanaal: {qch.mention if qch else '_niet ingesteld_'}\n"
            f"• Excluded: {exc_names}\n"
            f"• Auto-clean: {'aan' if g.get('quiz_autoclean', True) else 'uit'} "
            f"(delay {g.get('quiz_clean_delay',5)}s)"
        )

    @commands.command()
    @checks.admin()
    async def boozyclean(self, ctx: commands.Context, status: str):
        """Zet auto-clean aan/uit. Voorbeeld: !boozyclean on / off"""
        on = status.lower() in ("on", "aan", "true", "yes", "1")
        await self.config.guild(ctx.guild).quiz_autoclean.set(on)
        await ctx.send(f"🧹 Auto-clean staat nu **{'aan' if on else 'uit'}**.")

    @commands.command()
    @checks.admin()
    async def boozycleandelay(self, ctx: commands.Context, seconds: int):
        """Stel vertraging in voor auto-clean (seconden)."""
        seconds = max(0, min(120, seconds))
        await self.config.guild(ctx.guild).quiz_clean_delay.set(seconds)
        await ctx.send(f"⏱️ Auto-clean delay ingesteld op **{seconds}s**.")

    # ---------- Quiz ----------
    @commands.command()
    async def boozyquiz(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "medium"):
        """
        Start een BoozyQuiz™. Vereist 3+ humans in voice (behalve TEST_USER_ID).
        Cleanup: verwijdert alle berichten van de ronde na afloop (indien ingeschakeld).
        """
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")

        allow_test = ctx.author.id == TEST_USER_ID
        vc = ctx.author.voice.channel if ctx.author.voice else None
        humans = [m for m in (vc.members if vc else []) if not m.bot] if vc else []
        if not allow_test and len(humans) < 3:
            return await ctx.send("🔇 Je moet met minstens **3** gebruikers in een voice-kanaal zitten om te quizzen.")

        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid, is_test=allow_test)

    @commands.command()
    @checks.admin()
    async def boozyquiztest(self, ctx: commands.Context, thema: str = "algemeen", moeilijkheid: str = "medium"):
        """Forceer een testquiz (nooit rewards). Handig voor solo testen."""
        if self.quiz_active:
            return await ctx.send("⏳ Er is al een quiz bezig.")
        await self._start_quiz(ctx.channel, thema=thema, moeilijkheid=moeilijkheid, is_test=True)

    async def _cleanup_messages(self, channel: discord.TextChannel, to_delete: List[discord.Message]):
        if not to_delete:
            return
        # Alleen berichten <14 dagen, max 100 per bulk
        try:
            if len(to_delete) == 1:
                await to_delete[0].delete()
            else:
                await channel.delete_messages([m for m in to_delete if (discord.utils.utcnow() - m.created_at).days < 14][:100])
        except Exception:
            # Fallback naar individuele deletes
            for m in to_delete:
                try:
                    if (discord.utils.utcnow() - m.created_at).days < 14:
                        await m.delete()
                except Exception:
                    pass

    async def _start_quiz(self, channel: discord.TextChannel, thema: str, moeilijkheid: str, is_test: bool):
        thema = normalize_theme(thema)
        self.quiz_active = True
        round_messages: List[discord.Message] = []   # alles wat we straks wissen
        answer_messages: List[discord.Message] = []  # spelers-antwoorden

        try:
            typing = channel.typing()
            await typing.__aenter__()
            mcq = await self._generate_mcq(thema, moeilijkheid)
            await typing.__aexit__(None, None, None)

            options_str = "\n".join(f"{LETTERS[i]}. {mcq.options[i]}" for i in range(4))
            qmsg = await channel.send(f"❓ **{mcq.question}**\n*(antwoord met A/B/C/D — 25s)*\n{options_str}")
            round_messages.append(qmsg)

            end_time = asyncio.get_event_loop().time() + 25
            winner: Optional[discord.Member] = None

            while True:
                timeout = max(0, end_time - asyncio.get_event_loop().time())
                if timeout == 0:
                    break

                def check(m: discord.Message) -> bool:
                    return m.channel == channel and not m.author.bot and m.content.upper().strip() in LETTERS

                try:
                    msg = await self.bot.wait_for("message", timeout=timeout, check=check)
                except asyncio.TimeoutError:
                    break

                answer_messages.append(msg)

                if msg.content.upper().strip() == mcq.answer_letter.upper():
                    winner = msg.author
                    break
                else:
                    # markeer fout antwoord (minder spam dan reply)
                    try:
                        await msg.add_reaction("❌")
                    except Exception:
                        pass
                    continue  # blijf luisteren

            if winner:
                reward = DIFF_REWARD.get(moeilijkheid.lower(), 10)
                reason = None
                if is_test or winner.id == TEST_USER_ID:
                    reward = 0
                    reason = "testmodus"
                excluded = await self.config.guild(channel.guild).excluded_channels()
                if channel.id in excluded:
                    reward = 0
                    reason = "excluded kanaal"

                if reward > 0:
                    bal = await self.config.user(winner).booz()
                    await self.config.user(winner).booz.set(bal + reward)
                rmsg = await channel.send(
                    f"✅ Correct, {winner.mention}! Je wint **{reward} Boo'z**." + (f" *(geen reward: {reason})*" if reason else "")
                )
                round_messages.append(rmsg)
            else:
                ct = mcq.options[letter_index(mcq.answer_letter)]
                imsg = await channel.send(f"⌛ Niemand goed geantwoord. Antwoord: **{mcq.answer_letter}** — {ct}")
                round_messages.append(imsg)

        finally:
            self.quiz_active = False
            # Auto-clean
            g = await self.config.guild(channel.guild).all()
            if g.get("quiz_autoclean", True):
                await asyncio.sleep(int(g.get("quiz_clean_delay", 5)))
                # combineer en wis
                await self._cleanup_messages(channel, round_messages + answer_messages)
