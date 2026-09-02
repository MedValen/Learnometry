"""
The profile builder: working out how to route material for a new user.

WHAT THIS IS NOT
----------------
This is not the WAIS-5, and it is not a substitute for one. The WAIS-5 is a
restricted, copyrighted instrument that requires a qualified administrator, and
a self-administered version of it would produce numbers that look clinical and
mean nothing. Nothing here reports an IQ, a percentile, or any comparison
against other people, because none of those would be valid.

WHAT IT IS
----------
Four short tasks built from classic public paradigms - span, rapid naming, and
task-switching - with our own items. They are scored ONLY against each other,
within one person, to answer one practical question:

    which channel should this app route material through?

That is a configuration question, not a diagnosis. "Your visual span ran two
items longer than your spoken span" is a fact about a fifteen-minute sitting; it
tells the app to lead with tables, and it tells you nothing about your brain
that a psychologist would sign their name to.

Anyone with a real neuropsychological report should enter those scores instead -
`kind: "report"` - because a proper evaluation is better evidence than anything
that can be run in a browser.

THE TASKS
---------
  visual_span   items appear in a grid, reproduced in order        (visual WM)
  spoken_span   items are SPOKEN, reproduced in order              (auditory WM)
  naming        produce a word from a picture-like prompt          (retrieval)
  switching     sort under a rule that keeps changing              (set-shifting)

The first two are the pair that matters. Presenting the same task in two
modalities is what turns "I'm bad at remembering" into "the spoken channel is
the narrow one" - and that distinction is the whole basis of how this app
teaches.
"""

from __future__ import annotations

import time
import uuid

from . import db

# Deliberately ordinary words: the task is holding a sequence, not knowing
# vocabulary, so anything obscure would measure the wrong thing.
WORD_POOL = [
    "anchor", "basket", "candle", "dolphin", "engine", "feather", "garden",
    "hammer", "island", "jacket", "kettle", "ladder", "magnet", "needle",
    "orange", "pencil", "rabbit", "saddle", "tunnel", "violin", "window",
    "yellow", "bridge", "copper", "meadow", "ribbon", "shadow", "temple",
]

# Simple shapes and colours: nameable, but distinguishable without naming them,
# so the visual task is not secretly a verbal one.
TILE_POOL = [
    {"shape": "circle", "color": "#2f6f8f"}, {"shape": "square", "color": "#b4443a"},
    {"shape": "triangle", "color": "#2e7d5b"}, {"shape": "diamond", "color": "#a8861a"},
    {"shape": "hexagon", "color": "#6b4fa8"}, {"shape": "star", "color": "#bf6f36"},
    {"shape": "cross", "color": "#3b7d7d"}, {"shape": "heart", "color": "#a8477a"},
    {"shape": "moon", "color": "#4a6fa5"}, {"shape": "arrow", "color": "#7a7a3a"},
    {"shape": "cloud", "color": "#5e9a63"}, {"shape": "bolt", "color": "#8a5a12"},
]

# Prompts for the naming task. Each is a description with exactly one ordinary
# answer - this measures how fast a known word arrives, not whether it is known.
NAMING_ITEMS = [
    {"prompt": "The yellow fruit that monkeys are drawn with", "answer": "banana",
     "accept": ["bananas"]},
    {"prompt": "What you turn to open a door", "answer": "handle",
     "accept": ["doorknob", "knob", "door handle"]},
    {"prompt": "The animal that says 'moo'", "answer": "cow", "accept": ["cattle"]},
    {"prompt": "What you write on a blackboard with", "answer": "chalk", "accept": []},
    {"prompt": "The thing on your wrist that tells the time", "answer": "watch",
     "accept": ["wristwatch"]},
    {"prompt": "What you use to cut paper", "answer": "scissors", "accept": ["shears"]},
    {"prompt": "The flat thing you eat dinner off", "answer": "plate", "accept": ["dish"]},
    {"prompt": "What holds water and has a handle and a spout", "answer": "kettle",
     "accept": ["teapot", "jug", "pot"]},
    {"prompt": "The part of a tree under the ground", "answer": "roots",
     "accept": ["root"]},
    {"prompt": "What you look through to see yourself", "answer": "mirror", "accept": []},
    {"prompt": "The frozen water that floats in a drink", "answer": "ice",
     "accept": ["ice cube", "ice cubes"]},
    {"prompt": "What a bird builds to lay eggs in", "answer": "nest", "accept": []},
]

# Switching task: sort by one rule, then the rule flips without warning.
SWITCH_POOL = [
    {"word": "apple", "category": "food", "size": "small", "living": True},
    {"word": "bus", "category": "vehicle", "size": "big", "living": False},
    {"word": "salmon", "category": "food", "size": "small", "living": True},
    {"word": "truck", "category": "vehicle", "size": "big", "living": False},
    {"word": "bread", "category": "food", "size": "small", "living": False},
    {"word": "bicycle", "category": "vehicle", "size": "small", "living": False},
    {"word": "carrot", "category": "food", "size": "small", "living": True},
    {"word": "aeroplane", "category": "vehicle", "size": "big", "living": False},
    {"word": "cheese", "category": "food", "size": "small", "living": False},
    {"word": "tram", "category": "vehicle", "size": "big", "living": False},
]

TASKS = [
    {"id": "visual_span", "name": "Shapes in order",
     "measures": "Holding a sequence you can see",
     "how": "Shapes light up one at a time. Tap them back in the same order.",
     "minutes": 4},
    {"id": "spoken_span", "name": "Words in order",
     "measures": "Holding a sequence you hear",
     "how": "Words are read aloud. Type them back in the same order. "
            "Turn your sound on.",
     "minutes": 4},
    {"id": "naming", "name": "Name it",
     "measures": "How quickly a word you know arrives",
     "how": "Read a description and type the word. Never scored on being right "
            "or wrong alone - the pace is the point.",
     "minutes": 3},
    {"id": "switching", "name": "Changing rules",
     "measures": "Switching between rules without losing track",
     "how": "Sort each word by the current rule. The rule changes as you go.",
     "minutes": 3},
]

DISCLAIMER = (
    "This is not the WAIS-5 or any clinical test, and it does not produce an IQ "
    "or a percentile. It compares your own results against each other over about "
    "fifteen minutes, to work out how this app should present material to you. "
    "If you have had a real neuropsychological evaluation, enter those scores "
    "instead — they are far better evidence than anything a browser can measure."
)


def catalogue() -> dict:
    return {
        "tasks": TASKS,
        "disclaimer": DISCLAIMER,
        "minutes": sum(t["minutes"] for t in TASKS),
    }


# ------------------------------------------------------------- building

def build(task: str, *, span: int = 3, rounds: int = 6, seed: int | None = None) -> dict:
    import random

    rng = random.Random(seed)
    if task == "visual_span":
        out = []
        for _ in range(rounds):
            grid = rng.sample(TILE_POOL, min(9, len(TILE_POOL)))
            run = rng.sample(range(len(grid)), min(span, len(grid)))
            out.append({"grid": grid, "sequence": run})
        return {"task": task, "span": span, "rounds": out}

    if task == "spoken_span":
        out = []
        for _ in range(rounds):
            out.append({"words": rng.sample(WORD_POOL, min(span, len(WORD_POOL)))})
        return {"task": task, "span": span, "rounds": out}

    if task == "naming":
        items = rng.sample(NAMING_ITEMS, min(rounds + 4, len(NAMING_ITEMS)))
        return {"task": task, "rounds": items}

    if task == "switching":
        out = []
        rules = ["category", "size", "living"]
        rule = rules[0]
        for i in range(max(rounds, 12)):
            # Switch on roughly a third of trials, never twice in a row, so the
            # cost of switching is separable from the cost of the rule itself.
            if i and i % 3 == 0:
                rule = rng.choice([r for r in rules if r != rule])
            item = rng.choice(SWITCH_POOL)
            out.append({
                "word": item["word"], "rule": rule,
                "options": _options_for(rule),
                "answer": _answer_for(item, rule),
                "switched": bool(i and out and out[-1]["rule"] != rule),
            })
        return {"task": task, "rounds": out}

    raise ValueError(f"Unknown task: {task}")


def _options_for(rule: str) -> list[str]:
    return {"category": ["food", "vehicle"],
            "size": ["small", "big"],
            "living": ["living", "not living"]}[rule]


def _answer_for(item: dict, rule: str) -> str:
    if rule == "living":
        return "living" if item["living"] else "not living"
    return item[rule]


# -------------------------------------------------------------- scoring

def score(tasks: dict) -> dict:
    """Turn raw task results into an app configuration.

    Everything here is a within-person comparison. There is no norm, no
    percentile, and no attempt to convert any of it into a standard score -
    doing so would be inventing precision this cannot support.
    """
    # Two of these are policy, not findings, so they do not wait on a task:
    # nothing is timed unless the person asks for it, and a near-miss on a word
    # is never marked as not knowing the thing. Making them conditional would
    # mean someone who skipped a task got the harsher behaviour by accident.
    out: dict = {"tasks": {}, "contrasts": [], "notes": [],
                 "settings": {"timed_by_default": False,
                              "generous_matching": True}}

    vis = tasks.get("visual_span") or {}
    spo = tasks.get("spoken_span") or {}
    nam = tasks.get("naming") or {}
    swi = tasks.get("switching") or {}

    v_span = vis.get("best_span")
    s_span = spo.get("best_span")

    for key, data in (("visual_span", vis), ("spoken_span", spo)):
        if data.get("best_span"):
            out["tasks"][key] = {
                "best_span": data["best_span"],
                "rounds": data.get("rounds", 0),
                "accuracy": data.get("accuracy"),
            }
    if nam.get("median_ms"):
        out["tasks"]["naming"] = {
            "median_ms": nam["median_ms"], "accuracy": nam.get("accuracy"),
            "rounds": nam.get("rounds", 0),
        }
    if swi.get("accuracy") is not None:
        out["tasks"]["switching"] = {
            "accuracy": swi["accuracy"],
            "switch_accuracy": swi.get("switch_accuracy"),
            "stay_accuracy": swi.get("stay_accuracy"),
            "rounds": swi.get("rounds", 0),
        }

    # --- the contrast that matters -------------------------------------
    if v_span and s_span:
        gap = v_span - s_span
        if gap >= 2:
            out["contrasts"].append({
                "id": "modality",
                "finding": f"Your visual span ran {gap} items longer than your "
                           f"spoken span ({v_span} vs {s_span}).",
                "means": "Material you can see is easier for you to hold than "
                         "material you hear. This app will lead with tables and "
                         "diagrams and keep lists short.",
            })
            out["settings"]["route"] = "visual"
        elif gap <= -2:
            out["contrasts"].append({
                "id": "modality",
                "finding": f"Your spoken span ran {abs(gap)} items longer than "
                           f"your visual span ({s_span} vs {v_span}).",
                "means": "Spoken and written explanations work well for you. "
                         "Tables still help, but they are not doing the heavy "
                         "lifting.",
            })
            out["settings"]["route"] = "verbal"
        else:
            out["contrasts"].append({
                "id": "modality",
                "finding": f"Your two spans came out close ({v_span} visual, "
                           f"{s_span} spoken).",
                "means": "No strong channel preference. The app will mix "
                         "formats rather than favour one.",
            })
            out["settings"]["route"] = "balanced"

        out["settings"]["chunk_at"] = max(3, min(v_span, s_span))

    # --- retrieval -------------------------------------------------------
    if nam.get("median_ms"):
        slow = nam["median_ms"] > 4000
        out["contrasts"].append({
            "id": "retrieval",
            "finding": f"Words took about {nam['median_ms'] / 1000:.1f}s to "
                       f"arrive, with {nam.get('accuracy', 0):.0%} of them right.",
            "means": ("Answers will never be timed, and near-misses will count. "
                      "Slow retrieval of a word you know is not the same as not "
                      "knowing it.") if slow else
                     ("Retrieval is comfortable. Answers still aren't timed by "
                      "default, but the cue ladder will stay out of your way."),
        })
        out["settings"]["cue_ladder"] = "prominent" if slow else "available"

    # --- switching -------------------------------------------------------
    if swi.get("switch_accuracy") is not None and swi.get("stay_accuracy") is not None:
        cost = swi["stay_accuracy"] - swi["switch_accuracy"]
        strong = cost < 0.15
        out["contrasts"].append({
            "id": "switching",
            "finding": f"When the rule changed you were "
                       f"{swi['switch_accuracy']:.0%} accurate, against "
                       f"{swi['stay_accuracy']:.0%} when it stayed the same.",
            "means": ("Rule changes cost you very little. Interleaved practice "
                      "and look-alike comparisons will suit you and are worth "
                      "more than blocked practice.") if strong else
                     ("Rule changes cost you something. The app will keep "
                      "switches deliberate and signposted rather than constant."),
        })
        out["settings"]["interleave"] = "strong" if strong else "gentle"

    out["settings"].setdefault("chunk_at", 4)
    out["settings"].setdefault("route", "balanced")

    out["notes"].append(DISCLAIMER)
    if len(out["tasks"]) < 4:
        out["notes"].append(
            f"Only {len(out['tasks'])} of 4 tasks were completed, so this is a "
            "partial picture. You can run the missing ones any time.")
    return out


# --------------------------------------------------------------- storage

def start(user_id: str | None = None) -> str:
    rid = f"scr_{uuid.uuid4().hex[:8]}"
    db.run("INSERT INTO screener_run (id, user_id, ts, tasks, profile, complete) "
           "VALUES (?,?,?,?,?,0)", rid, user_id, time.time(), db.js({}), db.js({}))
    return rid


def record(run_id: str, task: str, result: dict) -> dict:
    row = db.q1("SELECT * FROM screener_run WHERE id = ?", run_id)
    if row is None:
        raise KeyError(f"no such screener run: {run_id}")

    tasks = db.unjs(row["tasks"], {})
    tasks[task] = result
    profile = score(tasks)
    complete = 1 if len(tasks) >= len(TASKS) else 0

    db.run("UPDATE screener_run SET tasks = ?, profile = ?, complete = ? WHERE id = ?",
           db.js(tasks), db.js(profile), complete, run_id)
    return {"run_id": run_id, "done": sorted(tasks), "remaining":
            [t["id"] for t in TASKS if t["id"] not in tasks],
            "profile": profile, "complete": bool(complete)}


def get(run_id: str) -> dict:
    row = db.q1("SELECT * FROM screener_run WHERE id = ?", run_id)
    if row is None:
        raise KeyError(f"no such screener run: {run_id}")
    return {
        "id": row["id"], "ts": row["ts"], "complete": bool(row["complete"]),
        "tasks": db.unjs(row["tasks"], {}), "profile": db.unjs(row["profile"], {}),
    }
