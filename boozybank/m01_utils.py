# ============================
# m01_utils.py
# ============================
from __future__ import annotations
import datetime, random, re

# M01#1 CONST
COIN = "🪙"
DAILY_RESET_UTC_HOUR = 4
MIN_REWARD, MAX_REWARD = 20, 50

# M01#2 TIME

def utc_now():
    return datetime.datetime.utcnow()

def utc_ts():
    return utc_now().timestamp()

def day_key_utc():
    return utc_now().strftime("%Y-%m-%d")

def cutoff_ts_at_hour_utc(hour: int) -> float:
    now = utc_now()
    tgt = now.replace(hour=hour % 24, minute=0, second=0, microsecond=0)
    if now < tgt:
        tgt -= datetime.timedelta(days=1)
    return tgt.timestamp()

# M01#3 STRING

def short(s: str, n: int = 80) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "…"

def norm_game(name: str | None) -> str:
    return (name or "").strip()

# M01#4 RANDOM & REWARD

def seeded_daily_choice(seq, seed_extra: str = ""):
    if not seq:
        return None
    rnd = random.Random(day_key_utc() + seed_extra)
    pool = list(seq)
    rnd.shuffle(pool)
    return pool[0]

def round5(x: int) -> int:
    return int(5 * round(int(x) / 5))

def clamp_reward(x: int) -> int:
    return max(MIN_REWARD, min(MAX_REWARD, round5(x)))

def scaled_reward_minutes(mins: int) -> int:
    if mins <= 30:
        return MIN_REWARD
    if mins >= 120:
        return MAX_REWARD
    r = MIN_REWARD + (mins - 30) * (MAX_REWARD - MIN_REWARD) / (120 - 30)
    return clamp_reward(int(r))
