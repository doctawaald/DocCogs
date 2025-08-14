# M01 --- UTILS -------------------------------------------------------------
# Kleine hulpfuncties die door meerdere modules gebruikt worden.
# ---------------------------------------------------------------------------

# M01#1 IMPORTS
import datetime
import random

# M01#2 TIME HELPERS
def utc_ts() -> float:
    return datetime.datetime.utcnow().timestamp()

def day_key_utc() -> str:
    return datetime.datetime.utcnow().strftime("%Y-%m-%d")

def cutoff_ts_at_hour_utc(hour: int) -> float:
    now = datetime.datetime.utcnow()
    tgt = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if now < tgt:
        tgt -= datetime.timedelta(days=1)
    return tgt.timestamp()

def weekday_key_utc() -> str:
    return ["mon","tue","wed","thu","fri","sat","sun"][datetime.datetime.utcnow().weekday()]

# M01#3 STR HELPERS
def short_game(n: str | None, limit: int = 40) -> str:
    s = (n or "").strip()
    return s if len(s) <= limit else (s[: limit - 1] + "…")

def norm_game(n: str | None) -> str:
    return (n or "").strip()

# M01#4 RANDOM HELPERS
def daily_seeded_choice(seq, seed_extra: str = ""):
    seed = day_key_utc() + seed_extra
    rnd = random.Random(seed)
    if not seq:
        return None
    return rnd.choice(list(seq))
