# [01] UTILS — helpers, canonicalization, fallbacks (licht makkelijk)

import re
import random
import datetime
from dataclasses import dataclass, replace
from typing import List, Dict

TEST_USER_ID = 489127123446005780  # jouw test ID
LETTERS = ["A", "B", "C", "D"]

@dataclass
class MCQ:
    question: str
    options: List[str]   # exact 4
    answer_letter: str   # "A"/"B"/"C"/"D"

def letter_index(letter: str) -> int:
    return {"A": 0, "B": 1, "C": 2, "D": 3}[letter.upper()]

OPTION_PREFIX_RE = re.compile(
    r"""^\s*([A-Da-d]|\d{1,2})\s*[\.\)\:\-]\s*""",
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
        "games": "games",
        "alcohol": "alcohol",
        "films": "films", "movies": "films",
        "algemeen": "algemeen", "general": "algemeen",
        "electronics": "electronics", "electronica": "electronics", "elektronica": "electronics",
        "controllers": "electronics", "gamecontrollers": "electronics",
    }
    return mapping.get(t, t or "algemeen")

def cutoff_ts_at_hour_utc(hour: int) -> float:
    now = datetime.datetime.utcnow()
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if now < target:
        target -= datetime.timedelta(days=1)
    return target.timestamp()

_CANON_RE = re.compile(r"[^\w]+", re.UNICODE)
def canonical_question(text: str) -> str:
    t = str(text or "").lower()
    t = _CANON_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

# ---- EASY-ish fallback bank (licht makkelijk) ----
FALLBACK_BANK: Dict[str, List[MCQ]] = {
    "games": [
        MCQ("Welk bedrijf maakt de PlayStation?", ["Sony", "Microsoft", "Nintendo", "Valve"], "A"),
        MCQ("Welke Nintendo-held draagt een groene pet?", ["Luigi", "Mario", "Link", "Yoshi"], "A"),
        MCQ("Wat verzamel je in *Minecraft* om tools te maken?", ["Hout", "Munten", "Mana", "Tickets"], "A"),
        MCQ("In welke serie komt Master Chief voor?", ["Halo", "Gears of War", "Doom", "Mass Effect"], "A"),
        MCQ("Welke knop springt meestal op een Xbox-controller?", ["A", "B", "X", "Y"], "A"),
    ],
    "alcohol": [
        MCQ("Welk hoofdingrediënt heeft bier?", ["Gerst", "Aardappelen", "Rijst", "Maïs"], "A"),
        MCQ("Wat is de basisalcohol in een Mojito?", ["Rum", "Gin", "Wodka", "Tequila"], "A"),
        MCQ("Welke drank is typisch blauw?", ["Blue Curaçao", "Vermout", "Port", "Amaretto"], "A"),
        MCQ("Wat is een alcoholvrije cocktail?", ["Mocktail", "Short", "Neat", "On the rocks"], "A"),
        MCQ("Welke wijn is rood?", ["Merlot", "Sauvignon Blanc", "Pinot Grigio", "Prosecco"], "A"),
    ],
    "films": [
        MCQ("Wie speelde Jack in *Titanic*?", ["Leonardo DiCaprio", "Brad Pitt", "Keanu Reeves", "Tom Cruise"], "A"),
        MCQ("Welke serie hoort bij lightsabers?", ["Star Wars", "Star Trek", "Blade Runner", "Alien"], "A"),
        MCQ("Wie regisseerde *Jurassic Park*?", ["Steven Spielberg", "James Cameron", "Ridley Scott", "Peter Jackson"], "A"),
        MCQ("Wie is de clown in *It*?", ["Pennywise", "Joker", "Chucky", "Ghostface"], "A"),
        MCQ("Welke film gaat over een tovenaarsschool?", ["Harry Potter", "Twilight", "Dune", "Matrix"], "A"),
    ],
    "boardgames": [
        MCQ("In *Catan* ruil je vooral…", ["Grondstoffen", "Munten", "Kaarten met vragen", "Dobbelstenen"], "A"),
        MCQ("Waarmee beweeg je in *Monopoly*?", ["Dobbelstenen", "Kaarten", "Fiches", "Zandlopers"], "A"),
        MCQ("Bij *Uno* win je door…", ["Je laatste kaart te spelen", "Geld te sparen", "Het bord te vullen", "De koning te slaan"], "A"),
        MCQ("Welke kleur heeft de start in *Mens-erger-je-niet*?", ["Rood", "Paars", "Zwart", "Goud"], "A"),
        MCQ("Schaken: hoe heet de sterkste stuk?", ["Dame", "Toren", "Loper", "Koning"], "A"),
    ],
    "electronics": [
        MCQ("Welke pool van een batterij is aangeduid met een plus?", ["Positief", "Negatief", "Aarde", "Signaal"], "A"),
        MCQ("Welke eenheid meet spanning?", ["Volt", "Ampère", "Ohm", "Watt"], "A"),
        MCQ("Wat doet een weerstand?", ["Beperkt stroom", "Versterkt signaal", "Slaat energie op", "Maakt licht"], "A"),
        MCQ("Welke kleur is vaak massa/aarde in DC-kabels?", ["Zwart", "Rood", "Geel", "Blauw"], "A"),
        MCQ("Welke component geeft licht als er stroom loopt?", ["LED", "Spoel", "Diodebrug", "Relais"], "A"),
    ],
    "algemeen": [
        MCQ("Hoeveel minuten zitten er in een uur?", ["60", "30", "90", "120"], "A"),
        MCQ("Welk dier miauwt?", ["Kat", "Hond", "Koe", "Vogel"], "A"),
        MCQ("Welke kleur krijg je door blauw + geel?", ["Groen", "Paars", "Oranje", "Bruin"], "A"),
        MCQ("Wat gebruik je om te bellen?", ["Telefoon", "Printer", "Router", "Muis"], "A"),
        MCQ("Welke maand komt na juni?", ["Juli", "Mei", "Augustus", "September"], "A"),
    ],
}

def pick_fallback(thema: str) -> MCQ:
    bank = FALLBACK_BANK.get(normalize_theme(thema)) or FALLBACK_BANK["algemeen"]
    mcq = random.choice(bank)
    return replace(mcq, options=sanitize_options(mcq.options))
