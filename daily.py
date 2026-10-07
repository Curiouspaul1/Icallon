"""Daily challenge: one short solo game per day, the same letters for
everyone, one attempt each, and a leaderboard.

Storage is a single JSON file. On Cloud Run that file lives inside the
container, so the board resets whenever the service restarts or is
redeployed. Everything that touches storage is in the "STORAGE" section
below; moving to Firestore later means rewriting only those functions.
"""

import random
import time
from datetime import datetime, timedelta

from pytz import timezone

from bots import SOLO_LETTERS
from utils import Resp, execute_action, execute_read

DAILY_FILE = "daily_results.json"
DAILY_ROUNDS = 5
DAILY_CATEGORIES = ["Name", "Animal", "Place", "Thing"]
DAILY_MAX_SCORE = DAILY_ROUNDS * len(DAILY_CATEGORIES) * 10
DAILY_TZ = timezone("Africa/Lagos")  # the day rolls over at midnight here
KEEP_DAYS = 21  # older days are dropped from the file
BOARD_SIZE = 10


def today():
    return datetime.now(DAILY_TZ).strftime("%Y-%m-%d")


def letters_for(date):
    """The day's letters, in playing order. Seeded by the date, so every
    player (and every server restart) gets the same ones."""
    rng = random.Random(f"icallon-daily-{date}")
    return "".join(rng.sample(SOLO_LETTERS, DAILY_ROUNDS))


def _week_dates(date):
    """Monday up to and including `date`."""
    day = datetime.strptime(date, "%Y-%m-%d")
    monday = day - timedelta(days=day.weekday())
    return [
        (monday + timedelta(days=i)).strftime("%Y-%m-%d")
        for i in range(day.weekday() + 1)
    ]


def _rank_key(item):
    # Higher score first. On a tie: a finished game beats an abandoned one
    # (which has fewer rounds on its clock), then whoever answered faster,
    # then whoever played earlier.
    name, entry = item
    return (
        -entry["score"],
        0 if entry["finished"] else 1,
        entry["seconds"],
        entry.get("started_at", 0),
        name,
    )


# =========================================================
# STORAGE
# File layout: {date: {username: entry}} where entry is
# {"score", "seconds", "rounds": [points per round], "finished", "started_at"}
# =========================================================


@execute_action(filename=DAILY_FILE)
def start(data, date, username):
    """Claim today's attempt. Returns False if this player already has one
    (finished or not): starting is what uses up the attempt, so leaving
    half way and coming back doesn't give a second go."""
    day = data.setdefault(date, {})
    if username in day:
        return Resp(routine_resp=False)

    day[username] = {
        "score": 0,
        "seconds": 0,
        "rounds": [],
        "finished": False,
        "started_at": time.time(),
    }

    cutoff = (datetime.strptime(date, "%Y-%m-%d") - timedelta(days=KEEP_DAYS)).strftime(
        "%Y-%m-%d"
    )
    for old in [d for d in data if d < cutoff]:
        del data[old]

    return Resp(file_json=data, routine_resp=True)


@execute_action(filename=DAILY_FILE)
def record_round(data, date, username, points, seconds):
    """Saved after every round, so an abandoned game keeps what it earned."""
    entry = data.get(date, {}).get(username)
    if entry is None or entry["finished"]:
        return Resp(routine_resp=False)
    entry["rounds"].append(points)
    entry["score"] += points
    entry["seconds"] = round(entry["seconds"] + seconds, 1)
    if len(entry["rounds"]) >= DAILY_ROUNDS:
        entry["finished"] = True
    return Resp(file_json=data, routine_resp=True)


@execute_read(filename=DAILY_FILE)
def _load(data):
    return Resp(routine_resp=data)


# =========================================================
# READ MODEL
# =========================================================


def has_played(date, username):
    return username in ((_load() or {}).get(date) or {})


def board(date, username):
    """Everything the daily screen shows for one player."""
    data = _load() or {}
    day = data.get(date) or {}
    ranked = sorted(day.items(), key=_rank_key)

    me = day.get(username)
    rank = next((i + 1 for i, (name, _) in enumerate(ranked) if name == username), None)

    week = {}
    for d in _week_dates(date):
        for name, entry in (data.get(d) or {}).items():
            row = week.setdefault(name, {"name": name, "score": 0, "days": 0})
            row["score"] += entry["score"]
            row["days"] += 1
    week_ranked = sorted(week.values(), key=lambda r: (-r["score"], r["name"]))
    week_rank = next(
        (i + 1 for i, r in enumerate(week_ranked) if r["name"] == username), None
    )

    return {
        "date": date,
        "rounds": DAILY_ROUNDS,
        "max_score": DAILY_MAX_SCORE,
        "played": me is not None,
        "me": me,
        "rank": rank,
        "players": len(ranked),
        "top": [
            {"name": name, "score": e["score"], "seconds": e["seconds"]}
            for name, e in ranked[:BOARD_SIZE]
        ],
        "week": week_ranked[:BOARD_SIZE],
        "week_rank": week_rank,
        "week_players": len(week_ranked),
    }