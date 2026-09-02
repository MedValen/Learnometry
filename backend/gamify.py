"""
Progression: XP, levels, streaks, achievements, and the organ-system map.

Built to the constraint set out in the architecture doc, which is worth
restating because it is what makes this layer safe for her rather than
counterproductive:

  * NOTHING DRAINS. Bars fill; they never empty. A decaying streak clock turns a
    formal accommodation into a stressor, and the report notes this working-
    memory pattern is itself produced by anxiety - so a system that generates
    anxiety degrades the very thing it is measuring.
  * STREAKS COUNT CORRECT ANSWERS, NOT CONSECUTIVE DAYS. A day-streak punishes
    rest, and a missed day should not erase three weeks of work.
  * XP FOLLOWS DIFFICULTY AND HONESTY, NOT SPEED. A confident Level 3 answer is
    worth more than a Level 1 guess. Response time is not a term anywhere here,
    for the same reason it is not a term in the mastery model.
  * ACHIEVEMENTS ARE FOR THINGS SHE DID, NOT THINGS SHE HAPPENED TO GET. Every
    one below is earned by an action she chose - answering honestly, escalating
    difficulty, coming back to decayed material.
"""

from __future__ import annotations

import time

from . import db, mastery as mastery_math

# XP per answered question. Difficulty scales it; honesty scales it further,
# because a "guessed" that turns out right should not pay like knowing.
BASE_XP = 10
DIFFICULTY_XP = {1: 1.0, 2: 1.3, 3: 1.7, 4: 2.2}
CONFIDENCE_XP = {"knew": 1.0, "unsure": 0.9, "guessed": 0.7}

# A wrong answer still pays. It is a retrieval attempt, it moves the model, and
# paying nothing for it would teach her to avoid hard questions.
WRONG_XP_SHARE = 0.4

# Owning up to a guess pays a small bonus - the metacognitive data is worth more
# to the engine than the point difference costs her.
HONESTY_BONUS = 3

LEVEL_BASE = 120      # XP for level 2
LEVEL_GROWTH = 1.18   # each level costs this much more than the last


def level_for(xp: int) -> dict:
    """Level, and progress toward the next. Growth is gentle on purpose."""
    level, spent, need = 1, 0, LEVEL_BASE
    while xp >= spent + need:
        spent += need
        level += 1
        need = int(need * LEVEL_GROWTH)
    return {
        "level": level,
        "xp": xp,
        "into_level": xp - spent,
        "need": need,
        "to_next": spent + need - xp,
        "pct": round((xp - spent) / need, 3) if need else 0.0,
    }


def xp_for_attempt(*, correct: bool, difficulty: int, confidence: str,
                   used_cue: bool = False) -> int:
    mult = DIFFICULTY_XP.get(difficulty, 1.0) * CONFIDENCE_XP.get(confidence, 0.9)
    xp = BASE_XP * mult * (1.0 if correct else WRONG_XP_SHARE)
    if confidence == "guessed":
        xp += HONESTY_BONUS
    if used_cue:
        xp *= 0.85
    return max(1, round(xp))


# ------------------------------------------------------------------ state

def _row() -> dict:
    r = db.q1("SELECT * FROM progression WHERE id = 1")
    if r is None:
        db.run("INSERT INTO progression (id, xp, level, updated_at) VALUES (1,0,1,0)")
        r = db.q1("SELECT * FROM progression WHERE id = 1")
    return dict(r)


def award(xp: int) -> dict:
    row = _row()
    before = level_for(row["xp"])
    total = row["xp"] + max(0, xp)
    after = level_for(total)
    db.run("UPDATE progression SET xp = ?, level = ?, updated_at = ? WHERE id = 1",
           total, after["level"], time.time())
    return {"gained": xp, "total": total, "level": after,
            "levelled_up": after["level"] > before["level"]}


def current_streak() -> dict:
    """Correct answers in a row, newest backward. Never day-based."""
    rows = db.q("SELECT correct FROM attempt ORDER BY id DESC LIMIT 200")
    streak = 0
    for r in rows:
        if r["correct"]:
            streak += 1
        else:
            break

    best = _row()["best_streak"] or 0
    if streak > best:
        db.run("UPDATE progression SET best_streak = ? WHERE id = 1", streak)
        best = streak
    return {"streak": streak, "best": best}


# ------------------------------------------------------------ achievements

ACHIEVEMENTS = [
    {"id": "first_answer", "name": "Opened the book",
     "how": "Answer your first question", "hidden": False},
    {"id": "streak_10", "name": "Ten in a row",
     "how": "Get 10 correct in a row", "hidden": False},
    {"id": "streak_25", "name": "Twenty-five in a row",
     "how": "Get 25 correct in a row", "hidden": False},
    {"id": "honest_50", "name": "Kept yourself honest",
     "how": "Mark 50 answers as guessed or unsure — the data is worth more "
            "than the points", "hidden": False},
    {"id": "level_3", "name": "Climbed",
     "how": "Answer 25 Level 3 questions", "hidden": False},
    {"id": "level_4", "name": "Integrated",
     "how": "Answer 10 Level 4 questions", "hidden": False},
    {"id": "first_master", "name": "First mastered concept",
     "how": "Take any concept to dark green", "hidden": False},
    {"id": "ten_master", "name": "Ten mastered",
     "how": "Take 10 concepts to dark green", "hidden": False},
    {"id": "revived", "name": "Brought it back",
     "how": "Return a decayed concept to green", "hidden": False},
    {"id": "boss_first", "name": "Boss down",
     "how": "Clear a system's boss challenge", "hidden": False},
    {"id": "hundred", "name": "A hundred questions",
     "how": "Answer 100 questions", "hidden": False},
    {"id": "thousand", "name": "A thousand questions",
     "how": "Answer 1000 questions", "hidden": False},
]


def check_achievements() -> list[dict]:
    """Recompute from history. Idempotent, so it can run after every attempt."""
    row = _row()
    unlocked = set(db.unjs(row["unlocked"], []))
    newly: list[dict] = []

    total = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    honest = db.q1(
        "SELECT COUNT(*) n FROM attempt WHERE confidence IN ('guessed','unsure')")["n"]
    l3 = db.q1("SELECT COUNT(*) n FROM attempt WHERE difficulty = 3")["n"]
    l4 = db.q1("SELECT COUNT(*) n FROM attempt WHERE difficulty = 4")["n"]
    mastered = db.q1("SELECT COUNT(*) n FROM mastery WHERE band = 'dark_green'")["n"]
    best = current_streak()["best"]
    bosses = db.q1(
        "SELECT COUNT(*) n FROM session WHERE mode = 'boss' AND ended_at IS NOT NULL "
        "AND answered > 0 AND correct * 10 >= answered * 7")["n"]

    # A concept that dropped below green and has since come back.
    revived = db.q1(
        "SELECT COUNT(*) n FROM attempt a WHERE a.mastery_before < 0.5 "
        "AND a.mastery_after >= 0.65")["n"]

    tests = {
        "first_answer": total >= 1,
        "hundred": total >= 100,
        "thousand": total >= 1000,
        "streak_10": best >= 10,
        "streak_25": best >= 25,
        "honest_50": honest >= 50,
        "level_3": l3 >= 25,
        "level_4": l4 >= 10,
        "first_master": mastered >= 1,
        "ten_master": mastered >= 10,
        "revived": revived >= 1,
        "boss_first": bosses >= 1,
    }

    for a in ACHIEVEMENTS:
        if tests.get(a["id"]) and a["id"] not in unlocked:
            unlocked.add(a["id"])
            newly.append(a)

    if newly:
        db.run("UPDATE progression SET unlocked = ? WHERE id = 1",
               db.js(sorted(unlocked)))
    return newly


def achievements() -> list[dict]:
    unlocked = set(db.unjs(_row()["unlocked"], []))
    return [{**a, "unlocked": a["id"] in unlocked} for a in ACHIEVEMENTS]


# -------------------------------------------------------------- the map

def territories() -> list[dict]:
    """Organ systems as regions, with their state.

    Damaged regions read red and restored ones green - the same ramp as the
    mastery map, because inventing a second colour language for the same
    underlying number would be decoration pretending to be information.
    """
    out = []
    for t in db.q("SELECT id, name FROM topic WHERE depth = 0 ORDER BY sort_order"):
        rows = db.q(
            "SELECT c.id FROM concept c JOIN topic tp ON tp.id = c.topic_id "
            "WHERE c.retired = 0 AND (tp.id = ? OR tp.parent_id = ?)", t["id"], t["id"])
        if not rows:
            continue

        from . import bank
        states = [bank.current(r["id"]) for r in rows]
        practised = [m for m in states if m.attempts > 0]
        if not practised:
            out.append({"id": t["id"], "name": t["name"], "concepts": len(rows),
                        "practised": 0, "mastery": None, "band": "untouched",
                        "mastered": 0, "boss_ready": False, "to_boss": len(rows)})
            continue

        avg = sum(m.effective for m in practised) / len(practised)
        mastered = sum(1 for m in states if m.band == "dark_green")
        weak = [m for m in states if m.effective < 0.5]

        out.append({
            "id": t["id"], "name": t["name"],
            "concepts": len(rows), "practised": len(practised),
            "mastery": round(avg, 3),
            "band": mastery_math.band_for(avg, 1.0, 0.0, len(practised)),
            "mastered": mastered,
            # A boss is only worth fighting once the region is mostly solid;
            # otherwise it is just a harder version of the work she's avoiding.
            "boss_ready": avg >= 0.6 and len(practised) >= max(3, len(rows) // 2),
            "to_boss": max(0, len(weak)),
            "weakest": sorted(
                ({"concept_id": r["id"], "effective": round(m.effective, 3)}
                 for r, m in zip(rows, states) if m.attempts > 0),
                key=lambda x: x["effective"])[:3],
        })
    return out


def state() -> dict:
    row = _row()
    lvl = level_for(row["xp"])
    streak = current_streak()
    total = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    correct = db.q1("SELECT COUNT(*) n FROM attempt WHERE correct = 1")["n"]
    unlocked = len(db.unjs(row["unlocked"], []))
    return {
        "level": lvl, "streak": streak,
        "answered": total, "correct": correct,
        "achievements": {"unlocked": unlocked, "total": len(ACHIEVEMENTS)},
        "mastered": db.q1(
            "SELECT COUNT(*) n FROM mastery WHERE band = 'dark_green'")["n"],
    }
