# BoozyBank — Economy + BoozyQuiz (3 vragen, 1 poging p/p, cleanup, anti-dup)
# by ChatGPT 5 & dOCTAWAALd 🍻👻

import asyncio
import datetime
import json
import random
import re
from dataclasses import dataclass
from typing import Dict, List, Optional, Set

import aiohttp
import discord
from redbot.core import Config, checks, commands

TEST_USER_ID = 489127123446005780  # jouw ID voor testmodus
LETTERS = ["A", "B", "C", "D"]

# ---------- Helpers ----------
@dataclass
class MCQ:
    question: str
    options: List[str]   # sanitized (geen labels), len == 4
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
            "quiz_autoclean": True,
            "quiz_clean_delay": 5,
            "test_mode": False,        # als True: TEST_USER_ID mag solo spelen zonder reward
            "asked_questions": [],     # persistente anti-dup lijst (laatste 50 vragenstrings)
        }
        self.config.register_user(**default_user)
        self.config.register_guild(**default_guild)

        self.quiz_active = False
        self._recent_questions: List[str] = []  # in-memory anti-dup
        self._api_key: Optional[str] = None
        self._auto_task = self.bot.loop.create_task(self._voice_loop())
        self.thema_pool = ["games", "alcohol", "films", "board games", "algemeen"]

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

    def _record_recent_mem(self, q: str) -> None:
        self._recent_questions.append(q)
        if len(self._recent_questions) > 50:
            self._recent_questions.pop(0)

    async def _get_asked_set(self, guild: discord.Guild) -> Set[str]:
        lst = await self.config.guild(guild).asked_questions()
        return set(lst or [])

    async def _remember_question(self, guild: discord.Guild, q: str) -> None:
        async with self.config.guild(guild).asked_questions() as lst:
            lst.append(q)
            if len(lst) > 50:
                del lst[:-50]

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

    # ---------- Voice loop (random drop + auto-quiz) ----------
    async def _voice_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                for guild in self.bot.guilds:
                    # VC met meeste humans
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

                    # random drop: 1×/nacht
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

                    # auto-quiz: 1×/nacht, met aanvraag, random thema uit 5
                    last_quiz = await self.config.guild(guild).last_quiz()
                    if not last_quiz or last_quiz < reset:
                        quiz_channel_id = await self.config.guild(guild).quiz_channel()
                        channel = guild.get_channel(quiz_channel_id) if quiz_channel_id else None
                        if not channel:
                            continue
                        thema = random.choice(self.thema_pool)
                        ask = await channel.send(
                            f"📣 **BoozyQuiz™** Zin in een snelle quiz over *{thema}*? Reageer binnen **30s** om te starten!"
                        )
                        def check(m: discord.Message) -> bool:
                            return m.channel == channel and not m.author.bot
                        try:
                            await self.bot.wait_for("message", timeout=30, check=check)
                        except asyncio.TimeoutError:
                            try:
                                await ask.delete()
                            except Exception:
                                pass
                        else:
                            await self.config.guild(guild).last_quiz.set(now_ts)
                            await self._start_quiz(
                                channel, thema=thema, moeilijkheid="medium", is_test=False, count=3, include_ask=ask
                            )
            except Exception as e:
                print(f"[BoozyBank voice loop] {e}")
            await asyncio.sleep(60)

    # ---------- Quiz generatie ----------
    async def
