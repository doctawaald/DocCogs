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

def cutoff_ts_at_hour_utc(hour: int) -> float:
    """Timestamp van vandaag op <hour>:00:00 UTC; als nu vóór dat uur is, pak gisteren."""
    now = datetime.datetime.utcnow()
    target = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if now < target:
        target -= datetime.timedelta(days=1)
    return target.timestamp()

_CANON_RE = re.compile(r"[^\w]+", re.UNICODE)

def canonical_question(text: str) -> str:
    """
    Canonicaliseer vraag voor anti-dup:
    - lowercased
    - niet-alfanumeriek -> spaties
    - samengevoegde whitespace gestript
    """
    t = str(text or "").lower()
    t = _CANON_RE.sub(" ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t

FALLBACK_BANK: Dict[str, List[MCQ]] = {
    "games": [
        MCQ("Welke engine draait *Half-Life 2*?", ["Source", "id Tech 3", "Unreal 2", "GoldSrc"], "A"),
        MCQ("Welke *Dark Souls* stat verhoogt Equip Load?", ["Vitality", "Endurance", "Strength", "Dexterity"], "A"),
        MCQ("Welke studio maakte *Hades*?", ["Supergiant Games", "Larian Studios", "Arkane", "Supercell"], "A"),
        MCQ("In *Portal*, hoe heet de AI tegenstander?", ["GLaDOS", "SHODAN", "AM", "EDI"], "A"),
        MCQ("Welke reeks introduceerde de 'V.A.T.S.' mechanic?", ["Fallout", "Borderlands", "Deus Ex", "Bioshock"], "A"),
    ],
    "alcohol": [
        MCQ("Welke graansoort domineert in bourbon?", ["Maïs", "Rogge", "Tarwe", "Gerst"], "A"),
        MCQ("Calvados is een brandewijn van…", ["Peren", "Appels", "Druiven", "Kersen"], "B"),
        MCQ("Waar komt de 'Islay' whiskystijl vandaan?", ["Schotland", "Ierland", "VS", "Japan"], "A"),
        MCQ("Welke cocktail gebruikt Campari?", ["Negroni", "Old Fashioned", "Martini", "Margarita"], "A"),
        MCQ("Wat is de minimale ABV voor EU-vodka?", ["37.5%", "40%", "35%", "30%"], "A"),
    ],
    "films": [
        MCQ("Welke editor werkte vaak met Scorsese?", ["Thelma Schoonmaker", "Walter Murch", "Lee Smith", "Sally Menke"], "A"),
        MCQ("Welke film wordt geassocieerd met de Kuleshov-montage?", ["Man with a Movie Camera", "Battleship Potemkin", "Strike", "October"], "B"),
        MCQ("Wie regisseerde *Stalker* (1979)?", ["Andrei Tarkovsky", "Sergei Eisenstein", "Kieslowski", "Bergman"], "A"),
        MCQ("Welke term duidt een object dat het plot drijft aan?", ["MacGuffin", "Deus ex machina", "Chekhov's gun", "Montage"], "A"),
        MCQ("Wie componeerde vaak voor Christopher Nolan?", ["Hans Zimmer", "John Williams", "Max Richter", "Thomas Newman"], "A"),
    ],
    "boardgames": [
        MCQ("Designer van *Agricola*?", ["Uwe Rosenberg", "Reiner Knizia", "Vlada Chvátil", "Isaac Childres"], "A"),
        MCQ("In *Twilight Struggle* staat DEFCON initieel op…", ["3", "2", "4", "5"], "D"),
        MCQ("Welke mechaniek hoort bij *Dominion*?", ["Deckbuilding", "Tile laying", "Trick-taking", "Dexterity"], "A"),
        MCQ("In *Catan*, hoeveel punten is een langste handelsroute?", ["2", "3", "4", "5"], "A"),
        MCQ("Welke uitgever bracht *Gloomhaven* uit?", ["Cephalofair Games", "Asmadi", "Portal", "CGP"], "A"),
    ],
    "algemeen": [
        MCQ("Element met atoomnummer 74?", ["Wolfram", "Rhenium", "Iridium", "Osmium"], "A"),
        MCQ("Welke wiskundige introduceerde de lambda-calculus?", ["Alonzo Church", "Alan Turing", "Kurt Gödel", "John von Neumann"], "A"),
        MCQ("Wat is O-notatie voor binaire zoekopdracht?", ["O(log n)", "O(n)", "O(n^2)", "O(1)"], "A"),
        MCQ("Kleinste tweecijferige priemgetal?", ["11", "13", "17", "19"], "A"),
        MCQ("Afgeleide van sin(x)?", ["cos(x)", "-sin(x)", "tan(x)", "sec^2(x)"], "A"),
    ],
}

def pick_fallback(thema: str) -> MCQ:
    bank = FALLBACK_BANK.get(normalize_theme(thema)) or FALLBACK_BANK["algemeen"]
    mcq = random.choice(bank)
    return replace(mcq, options=sanitize_options(mcq.options))
