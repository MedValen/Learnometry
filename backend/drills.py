"""
Skill drills built from the subtest profile.

Every drill here is generated from concepts already in her bank, so all of it
runs with no API key and no network.

WHAT THESE ARE, STATED HONESTLY
-------------------------------
Evidence that training working memory itself transfers to real-world capacity is
weak. These drills are not a treatment for a 4th-percentile auditory working
memory, and the app should never imply otherwise.

What they do instead, and what there is decent support for:

  * practise in the channel that works. Where visual working memory outruns
    auditory working memory, sequencing medical content
    VISUALLY builds fluency through the route that is actually open.
  * rehearse the compensations. Chunking a seven-item list into named buckets
    of three, and writing premises down instead of holding them, are strategies
    she can apply in a real exam. Practising a strategy is not the same claim as
    training a capacity.
  * build content fluency. Retrieving "Winter's formula" quickly is worth
    something regardless of what it does or doesn't do to her span.
  * play to a strength. Where set-shifting is intact, the switching
    drill exists partly because it is the one that should feel good.

Results are stored in `drill_result`, deliberately apart from `attempt`. A drill
is a skill exercise, not a knowledge test, and folding its scores into mastery
would corrupt the model with a different task.
"""

from __future__ import annotations

import random
import time

from . import db, scope as scope_mod

HONESTY = (
    "These train strategies and fluency, not raw memory span. Evidence that "
    "working-memory training transfers to real capacity is weak — extended time "
    "and a low-distraction room remain the things that actually help most."
)

DRILLS = [
    {
        "id": "sequence",
        "name": "Sequence",
        "tagline": "Hold a run of items visually, then play it back.",
        "why": "Holding things visually rather than as a spoken chain. The "
               "channel that works, carrying real content.",
        "targets": "Visual working memory",
        "min_concepts": 4,
    },
    {
        "id": "chunk",
        "name": "Chunk It",
        "tagline": "Break a long list into named groups of two or three.",
        "why": "A bare list of seven is unusable to anyone. Grouping it is the "
               "compensation — and it's a strategy, so practising it counts.",
        "targets": "Chunking strategy · working-memory load",
        "min_concepts": 6,
    },
    {
        "id": "oddone",
        "name": "Odd One Out",
        "tagline": "Spot the outsider — and the rule keeps changing.",
        "why": "Set-shifting under a changing rule, and discrimination "
               "between look-alikes is high-yield anyway.",
        "targets": "Set-shifting · discrimination",
        "min_concepts": 6,
    },
    {
        "id": "name",
        "name": "Name It",
        "tagline": "Produce the term from the description. Never timed.",
        "why": "Retrieval can be slow without being absent. Practice is "
               "untimed and pace is tracked only against your own baseline.",
        "targets": "Lexical retrieval · confrontation naming",
        "min_concepts": 4,
    },
]


def _pool(scope: scope_mod.Scope | None) -> list[dict]:
    """Concepts available to build drills from, respecting the practice filter."""
    allowed = scope_mod.allowed(scope) if scope is not None else None
    rows = db.q(
        "SELECT c.id, c.name, c.one_line, c.topic_id, t.path, t.parent_id "
        "FROM concept c JOIN topic t ON t.id = c.topic_id "
        "WHERE c.retired = 0 AND c.name != ''"
    )
    out = []
    for r in rows:
        if allowed is not None and r["id"] not in allowed:
            continue
        out.append(dict(r))
    return out


def available(scope: scope_mod.Scope | None = None) -> dict:
    """Which drills can actually be built right now, and why not otherwise."""
    pool = _pool(scope)
    by_topic: dict[str, int] = {}
    for c in pool:
        by_topic[c["topic_id"]] = by_topic.get(c["topic_id"], 0) + 1
    biggest = max(by_topic.values()) if by_topic else 0
    topics_with_two = sum(1 for n in by_topic.values() if n >= 3)

    out = []
    for d in DRILLS:
        ok = len(pool) >= d["min_concepts"]
        reason = None
        if not ok:
            reason = (f"Needs {d['min_concepts']} concepts in scope; "
                      f"you have {len(pool)}.")
        elif d["id"] == "chunk" and biggest < 6:
            ok, reason = False, ("Needs 6 concepts under one topic; the biggest "
                                 f"has {biggest}.")
        elif d["id"] == "oddone" and topics_with_two < 2:
            ok, reason = False, "Needs concepts from at least two different topics."
        out.append({**d, "available": ok, "reason": reason})
    return {"drills": out, "pool": len(pool), "honesty": HONESTY}


# --------------------------------------------------------------- builders

def build(drill: str, *, rounds: int = 6, scope: scope_mod.Scope | None = None,
          span: int = 3) -> dict:
    pool = _pool(scope)
    rng = random.Random()

    if drill == "sequence":
        return _sequence(pool, rounds, span, rng)
    if drill == "chunk":
        return _chunk(pool, rng)
    if drill == "oddone":
        return _oddone(pool, rounds, rng)
    if drill == "name":
        return _name(pool, rounds, rng)
    raise ValueError(f"Unknown drill: {drill}")


def _sequence(pool, rounds, span, rng) -> dict:
    """Visual span: items flash in order, she plays the order back.

    The grid is always larger than the run so she is choosing, not just
    re-reading, and span adapts on her own performance rather than a fixed
    ladder - the point is to sit at her edge, not to score her against a norm.
    """
    if len(pool) < 4:
        raise ValueError("Not enough concepts in scope for this drill.")
    span = max(2, min(7, span))
    out = []
    for _ in range(rounds):
        grid_size = min(len(pool), max(span + 3, 6))
        grid = rng.sample(pool, grid_size)
        run = rng.sample(grid, min(span, len(grid)))
        out.append({
            "grid": [{"id": c["id"], "name": c["name"]} for c in grid],
            "sequence": [c["id"] for c in run],
        })
    return {"drill": "sequence", "span": span, "rounds": out,
            "instruction": "Watch the order. Then click them back in the same order.",
            "honesty": HONESTY}


def _chunk(pool, rng) -> dict:
    """Group a long list into named buckets.

    Deliberately ungraded for 'correctness'. There are many defensible ways to
    group a list of findings, and marking one right would teach her to guess the
    app's grouping instead of building her own - which is the thing that
    actually transfers. What is scored is whether she chunked at all.
    """
    by_topic: dict[str, list] = {}
    for c in pool:
        by_topic.setdefault(c["topic_id"], []).append(c)
    candidates = [(t, cs) for t, cs in by_topic.items() if len(cs) >= 6]
    if not candidates:
        raise ValueError("Needs at least 6 concepts under one topic.")

    topic_id, concepts = rng.choice(candidates)
    items = rng.sample(concepts, min(9, len(concepts)))
    path = items[0]["path"]

    return {
        "drill": "chunk",
        "topic": path,
        "items": [{"id": c["id"], "name": c["name"], "one_line": c["one_line"]}
                  for c in items],
        "buckets": 3 if len(items) >= 7 else 2,
        "instruction": (f"Here are {len(items)} things from {path}. Sort them into "
                        f"groups of two or three and give each group a name."),
        "note": ("There's no single right grouping — the useful part is that YOU "
                 "made one. A named group of three is something you can hold; a "
                 "list of nine is not."),
        "honesty": HONESTY,
    }


def _oddone(pool, rounds, rng) -> dict:
    """Three from one topic, one from elsewhere - with the rule alternating.

    The switch is the point. Set-shifting is often the strongest measured
    score, so alternating the rule turns the drill into the thing she is good at
    rather than another test of the thing she is not.
    """
    by_topic: dict[str, list] = {}
    for c in pool:
        by_topic.setdefault(c["topic_id"], []).append(c)
    usable = {t: cs for t, cs in by_topic.items() if len(cs) >= 3}
    if len(usable) < 2:
        raise ValueError("Needs concepts from at least two different topics.")

    out = []
    topics = list(usable)
    for i in range(rounds):
        home = rng.choice(topics)
        away = rng.choice([t for t in topics if t != home])
        trio = rng.sample(usable[home], 3)
        outsider = rng.choice(by_topic[away])

        options = trio + [outsider]
        rng.shuffle(options)
        rule = "outsider" if i % 2 == 0 else "belongs"
        out.append({
            "rule": rule,
            "prompt": ("Which one does NOT belong with the others?"
                       if rule == "outsider"
                       else "Three of these share a home. Which one is the odd one — "
                            "click the one that fits somewhere else."),
            "options": [{"id": c["id"], "name": c["name"], "hint": c["one_line"]}
                        for c in options],
            "answer": outsider["id"],
            "because": f"{outsider['name']} is {outsider['path']}; "
                       f"the others are {trio[0]['path']}.",
        })
    return {"drill": "oddone", "rounds": out,
            "instruction": "The rule flips every round. Read it each time.",
            "honesty": HONESTY}


def _name(pool, rounds, rng) -> dict:
    """Produce the term from its description. Untimed, generous, cue available."""
    usable = [c for c in pool if (c["one_line"] or "").strip()]
    if len(usable) < 4:
        # Fall back to stored cued-recall questions if concepts lack one-liners.
        rows = db.q(
            "SELECT q.answer_text, q.stem, q.cue, q.accepted, qc.concept_id "
            "FROM question q JOIN question_concept qc ON qc.question_id = q.id "
            "WHERE q.fmt = 'cued_recall' AND q.retired = 0 AND q.answer_text IS NOT NULL "
            "LIMIT 40")
        if len(rows) < 3:
            raise ValueError("Not enough described concepts in scope for this drill.")
        picked = rng.sample(list(rows), min(rounds, len(rows)))
        return {
            "drill": "name", "honesty": HONESTY,
            "instruction": "Type the term. Take as long as you like.",
            "rounds": [{
                "concept_id": r["concept_id"], "clue": r["stem"],
                "answer": r["answer_text"],
                "accepted": db.unjs(r["accepted"], []),
                "cue": r["cue"] or "",
            } for r in picked],
        }

    picked = rng.sample(usable, min(rounds, len(usable)))
    out = []
    for c in picked:
        name = c["name"]
        first = name.strip()[0] if name.strip() else "?"
        out.append({
            "concept_id": c["id"],
            "clue": c["one_line"],
            "answer": name,
            "accepted": [],
            "cue": f"{c['path']} · starts with \"{first}\"",
        })
    return {"drill": "name", "rounds": out, "honesty": HONESTY,
            "instruction": "Type the term. Take as long as you like — this is "
                           "never timed, and near-misses count."}


# ---------------------------------------------------------------- results

def record(
    drill: str, *, score: float, rounds: int, correct: int,
    span: int | None = None, ms: int | None = None,
    concept_ids: list[str] | None = None, detail: dict | None = None,
) -> dict:
    db.run(
        "INSERT INTO drill_result (drill, ts, score, span, rounds, correct, ms, "
        "concept_ids, detail) VALUES (?,?,?,?,?,?,?,?,?)",
        drill, time.time(), score, span, rounds, correct, ms,
        db.js(concept_ids or []), db.js(detail or {}),
    )
    return history(drill)


def history(drill: str | None = None, limit: int = 30) -> dict:
    if drill:
        rows = db.q(
            "SELECT * FROM drill_result WHERE drill = ? ORDER BY ts DESC LIMIT ?",
            drill, limit)
    else:
        rows = db.q("SELECT * FROM drill_result ORDER BY ts DESC LIMIT ?", limit)

    runs = [{"drill": r["drill"], "ts": r["ts"], "score": r["score"],
             "span": r["span"], "rounds": r["rounds"], "correct": r["correct"],
             "ms": r["ms"]} for r in rows]

    best = {}
    for d in DRILLS:
        row = db.q1(
            "SELECT MAX(span) s, MAX(score) sc, COUNT(*) n FROM drill_result "
            "WHERE drill = ?", d["id"])
        best[d["id"]] = {"best_span": row["s"], "best_score": row["sc"],
                         "sessions": row["n"] or 0}

    # Personal trend only. Never compared against a norm - the whole point of
    # keeping response time out of the mastery model applies here too.
    trend = None
    if drill == "sequence":
        spans = [r["span"] for r in rows if r["span"]]
        if len(spans) >= 6:
            recent = sum(spans[:3]) / 3
            older = sum(spans[-3:]) / 3
            trend = {"recent": round(recent, 1), "earlier": round(older, 1),
                     "direction": "up" if recent > older + 0.3
                                  else "down" if recent < older - 0.3 else "flat"}

    return {"runs": runs, "best": best, "trend": trend}


def next_span(last_span: int, accuracy: float) -> int:
    """Adapt the run length to sit at her edge, not at a target.

    Up on a clean round, down on a poor one, hold in between. Bounded at 2 so it
    never becomes trivial and at 7 so it never becomes a wall.
    """
    if accuracy >= 0.99:
        return min(7, last_span + 1)
    if accuracy < 0.5:
        return max(2, last_span - 1)
    return last_span
