import re
import random
import datetime
from dataclasses import dataclass
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

# Een iets pittigere fallback-bank (per thema)
FALLBACK_BANK: Dict[str, List[MCQ]] = {
    "games": [
        MCQ("Welke engine draait *Half-Life 2*?", ["Source", "id Tech 3", "Unreal 2", "GoldSrc"], "A"),
        MCQ("Welke *Dark Souls* stat verhoogt Equip Load?", ["Vitality", "Endurance", "Strength", "Dexterity"], "A"),
    ],
    "alcohol": [
        MCQ("Welke graansoort domineert in bourbon?", ["Maïs", "Rogge", "Tarwe", "Gerst"], "A"),
        MCQ("Calvados is een brandewijn van…", ["Peren", "Appels", "Druiven", "Kersen"], "B"),
    ],
    "films": [
        MCQ("Welke editor werkte vaak met Scorsese?", ["Thelma Schoonmaker", "Walter Murch", "Lee Smith", "Sally Menke"], "A"),
        MCQ("Welke film wordt geassocieerd met de Kuleshov-montage?", ["Man with a Movie Camera", "Battleship Potemkin", "Strike", "October"], "B"),
    ],
    "boardgames": [
        MCQ("Designer van *Agricola*?", ["Uwe Rosenberg", "Reiner Knizia", "Vlada Chvátil", "Isaac Childres"], "A"),
        MCQ("In *Twilight Struggle* staat DEFCON initieel op…", ["3", "2", "4", "5"], "D"),
    ],
    "algemeen": [
        MCQ("Element met atoomnummer 74?", ["Wolfram", "Rhenium", "Iridium", "Osmium"], "A"),
        MCQ("Welke wiskundige introduceerde de lambda-calculus?", ["Alonzo Church", "Alan Turing", "Kurt Gödel", "John von Neumann"], "A"),
    ],
}

def pick_fallback(thema: str) -> MCQ:
    from dataclasses import replace
    bank = FALLBACK_BANK.get(normalize_theme(thema)) or FALLBACK_BANK["algemeen"]
    mcq = random.choice(bank)
    # return a copy to avoid mutation side-effects
    return replace(mcq, options=sanitize_options(mcq.options))
