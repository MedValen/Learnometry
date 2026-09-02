"""
Phase 1 routes: the durable question bank, attempt recording, and mastery.

Kept in its own module so app.py stays a thin aggregator as later phases add
their own routers.
"""

from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Body, HTTPException

from . import (analytics, bank, db, gamify, mastery as mastery_math,
               scope as scope_mod, taxonomy)

router = APIRouter(prefix="/api")


# ------------------------------------------------------------------ bank

@router.post("/bank/save")
def save_to_bank(body: dict = Body(...)):
    """Persist an analysis + its questions into the durable bank.

    Called by the browser right after generation, so a session's work outlives
    the session instead of vanishing on restart.
    """
    analysis = body.get("analysis") or {}
    questions = body.get("questions") or []
    if not analysis.get("concepts"):
        raise HTTPException(status_code=400, detail="No concepts in the analysis.")

    source_ref = body.get("source_ref") or {
        "label": analysis.get("title", "Uploaded material"),
        "kind": "lecture",
    }

    mapping = bank.persist_analysis(analysis, source_ref)
    saved = bank.save_questions(questions, mapping, source_ref=source_ref)

    return {
        "concepts": len(mapping),
        "questions": len(saved),
        "saved": saved,                                  # [{local_id, question_id, ...}]
        "ids": {s["local_id"]: s["question_id"] for s in saved},
        "concept_ids": list(mapping.values()),
        "dropped": len(questions) - len(saved),
    }


@router.get("/bank/stats")
def bank_stats():
    row = db.q1(
        "SELECT (SELECT COUNT(*) FROM concept WHERE retired = 0) AS concepts, "
        "       (SELECT COUNT(*) FROM question WHERE retired = 0) AS questions, "
        "       (SELECT COUNT(*) FROM attempt) AS attempts, "
        "       (SELECT COUNT(*) FROM topic) AS topics"
    )
    return dict(row)


@router.post("/bank/questions")
def bank_questions(body: dict = Body(...)):
    """Load stored questions by id."""
    return {"questions": bank.load_questions(body.get("ids") or [])}


# --------------------------------------------------------------- attempts

@router.post("/attempt")
def post_attempt(body: dict = Body(...)):
    qid = body.get("question_id")
    if not qid:
        raise HTTPException(status_code=400, detail="question_id is required.")
    try:
        return bank.record_attempt(
            question_id=qid,
            correct=bool(body.get("correct")),
            given=str(body.get("given") or ""),
            confidence=body.get("confidence") or "unsure",
            used_cue=bool(body.get("used_cue")),
            error_type=body.get("error_type"),
            rt_ms=body.get("rt_ms"),
            session_id=body.get("session_id"),
        )
    except KeyError as exc:
        # str(KeyError("x")) is "'x'" - unwrap it so she doesn't see the quotes.
        raise HTTPException(
            status_code=404,
            detail=str(exc.args[0]) if exc.args else str(exc))


@router.post("/session/start")
def session_start(body: dict = Body(...)):
    sid = uuid.uuid4().hex[:12]
    db.run(
        "INSERT INTO session (id, mode, started_at, planned) VALUES (?, ?, ?, ?)",
        sid, body.get("mode", "mixed"), time.time(), int(body.get("planned") or 0),
    )
    return {"session_id": sid}


@router.post("/session/end")
def session_end(body: dict = Body(...)):
    sid = body.get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="session_id is required.")
    rows = db.q(
        "SELECT correct, concept_id, mastery_before, mastery_after FROM attempt "
        "WHERE session_id = ?", sid,
    )
    answered = len(rows)
    correct = sum(1 for r in rows if r["correct"])

    moved: dict[str, float] = {}
    for r in rows:
        if r["mastery_before"] is None or r["mastery_after"] is None:
            continue
        moved[r["concept_id"]] = moved.get(r["concept_id"], 0.0) + (
            r["mastery_after"] - r["mastery_before"])

    gains = sorted(moved.items(), key=lambda kv: kv[1], reverse=True)
    named = lambda items: [                                    # noqa: E731
        {"concept_id": c, "name": bank._concept_name(c), "delta": round(d, 4)}
        for c, d in items
    ]

    db.run(
        "UPDATE session SET ended_at = ?, answered = ?, correct = ? WHERE id = ?",
        time.time(), answered, correct, sid,
    )
    return {
        "answered": answered,
        "correct": correct,
        "improved": named([g for g in gains[:3] if g[1] > 0]),
        "needs_work": named([g for g in gains[::-1][:3] if g[1] < 0]),
    }


# ---------------------------------------------------------------- mastery

@router.get("/mastery/concept/{concept_id:path}")
def mastery_concept(concept_id: str):
    row = db.q1("SELECT * FROM concept WHERE id = ?", concept_id)
    if row is None:
        raise HTTPException(status_code=404, detail="No such concept.")
    m = bank.current(concept_id)
    return {
        "concept": {
            "id": row["id"], "name": row["name"], "topic_id": row["topic_id"],
            "one_line": row["one_line"], "high_yield": row["high_yield"],
            "hy_tier": row["hy_tier"],
        },
        "mastery": _mastery_dict(m),
        "related": [
            dict(r) for r in db.q(
                "SELECT e.dst AS concept_id, e.relation, c.name "
                "FROM concept_edge e JOIN concept c ON c.id = e.dst WHERE e.src = ?",
                concept_id,
            )
        ],
    }


def _mastery_dict(m: mastery_math.Mastery) -> dict:
    return {
        "mastery": round(m.mastery, 4),
        "retention": round(m.retention, 4),
        "effective": round(m.effective, 4),
        "est_confidence": round(m.est_confidence, 4),
        "band": m.band,
        "attempts": m.attempts,
        "correct": m.correct,
        "streak": m.streak,
        "longest_streak": m.longest_streak,
        "variance": round(m.variance, 4),
        "difficulty_gap": round(mastery_math.difficulty_gap(m), 4),
        "by_difficulty": m.by_difficulty,
        "by_format": m.by_format,
        "stability_days": round(m.stability_days, 2),
        "last_reviewed": m.last_reviewed,
        "to_next_band": bank.to_next_band(m),
        # Reported, never scored. See mastery.py.
        "avg_rt_ms": m.avg_rt_ms,
    }


@router.get("/mastery/map")
def mastery_map():
    """Topic tree with rolled-up mastery. Feeds the heatmap."""
    concepts = db.q(
        "SELECT c.id, c.name, c.topic_id, c.high_yield, c.hy_tier "
        "FROM concept c WHERE c.retired = 0"
    )
    topics = {t["id"]: dict(t) for t in db.q("SELECT * FROM topic ORDER BY sort_order")}

    per_topic: dict[str, list] = {}
    out_concepts = []
    for c in concepts:
        m = bank.current(c["id"])
        entry = {
            "id": c["id"], "name": c["name"], "topic_id": c["topic_id"],
            "high_yield": c["high_yield"], "hy_tier": c["hy_tier"],
            "effective": round(m.effective, 4), "mastery": round(m.mastery, 4),
            "retention": round(m.retention, 4), "band": m.band,
            "attempts": m.attempts, "est_confidence": round(m.est_confidence, 4),
        }
        out_concepts.append(entry)
        per_topic.setdefault(c["topic_id"], []).append(entry)

    # Roll up over each topic's WHOLE SUBTREE, and over ANSWERED concepts only.
    #
    # Two separate things are being fixed here. Averaging in untouched concepts
    # meant averaging in the prior and reporting it as a measurement, which is
    # how every unopened subject came to read 35%. And summing only over direct
    # children discarded any concept filed on the parent itself - "Pharmacology"
    # read 0 of 332 answered while the Home screen listed three answered
    # Pharmacology concepts, because all of them sat on the parent.
    children: dict[str | None, list[str]] = {}
    for t in topics.values():
        children.setdefault(t["parent_id"], []).append(t["id"])

    def subtree(tid: str) -> list[str]:
        out = [tid]
        for kid in children.get(tid, []):
            out.extend(subtree(kid))
        return out

    for tid, t in topics.items():
        kids: list[dict] = []
        for sub in subtree(tid):
            kids.extend(per_topic.get(sub, []))
        seen = [k for k in kids if k["attempts"] > 0]
        t["concepts"] = len(kids)
        t["assessed"] = len(seen)
        t["attempts"] = sum(k["attempts"] for k in kids)
        t["effective"] = (round(sum(k["effective"] for k in seen) / len(seen), 4)
                          if seen else None)

    for t in topics.values():
        t["band"] = (
            mastery_math.band_for(t["effective"], 1.0, 0.0, t["attempts"])
            if t["effective"] is not None else "untouched"
        )
        t["coverage"] = (round(t["assessed"] / t["concepts"], 4)
                         if t["concepts"] else 0.0)
        t["evidence"] = _evidence(t["assessed"], t["concepts"], t["attempts"])

    return {
        "topics": [t for t in topics.values() if t["concepts"]],
        "concepts": out_concepts,
    }


# How much of a topic has actually been answered. The interface has to be
# able to say UNKNOWN and WEAK differently; these are the three states it can
# distinguish, and nothing else may be claimed.
EVIDENCE_MIN_CONCEPTS = 3       # below this, one lucky run moves the number
EVIDENCE_MIN_SHARE = 0.25       # and a quarter of the topic must be covered


def _evidence(assessed: int, concepts: int, attempts: int) -> str:
    if assessed == 0 or attempts == 0:
        return "none"
    enough = max(EVIDENCE_MIN_CONCEPTS,
                 round(concepts * EVIDENCE_MIN_SHARE))
    return "measured" if assessed >= enough and attempts >= 8 else "thin"


@router.get("/mastery/weakest")
def weakest(limit: int = 10):
    """High-yield weaknesses. The most useful screen in the app.

    Ranked by weakness x high-yield x forgetting risk - a badly-known
    low-yield concept ranks below a moderately-known critical one.
    """
    rows = db.q(
        "SELECT c.id, c.name, c.topic_id, c.hy_tier, t.path, "
        "       MIN(1.0, c.high_yield + COALESCE(c.emphasis_boost, 0)) AS high_yield, "
        "       COALESCE(c.emphasis_boost, 0) AS emphasis_boost "
        "FROM concept c JOIN topic t ON t.id = c.topic_id WHERE c.retired = 0"
    )
    scored = []
    for r in rows:
        m = bank.current(r["id"])
        if m.attempts == 0:
            continue  # no evidence yet - not a measured weakness
        weakness = 1.0 - m.effective
        priority = (weakness ** 1.5) * (0.5 + 1.5 * r["high_yield"]) * \
                   (0.3 + 0.7 * (1.0 - m.retention))
        scored.append({
            "concept_id": r["id"], "name": r["name"], "topic": r["path"],
            "hy_tier": r["hy_tier"], "high_yield": r["high_yield"],
            "emphasis_boost": round(r["emphasis_boost"], 3),
            "effective": round(m.effective, 4), "band": m.band,
            "attempts": m.attempts, "priority": round(priority, 5),
        })
    scored.sort(key=lambda x: x["priority"], reverse=True)
    return {"weakest": scored[:limit]}


@router.get("/mastery/rebuild")
def rebuild():
    """Recompute all mastery from attempt history. Safe to run any time."""
    return {"rebuilt": bank.rebuild_all()}


# --------------------------------------------------------------- taxonomy

@router.get("/topics")
def topics():
    return {"topics": taxonomy.tree()}


# ------------------------------------------------ adaptive selection (phase 2)

@router.post("/select")
def select(body: dict = Body(...)):
    """Adaptively pick the next n questions.

    This is the route that replaces "generate a fixed set and walk it": the
    engine now decides what she should see, from what it knows about her.
    """
    n = max(1, min(50, int(body.get("n") or 10)))
    mode = body.get("mode") or "mixed"
    sc = scope_mod.Scope.from_dict(body.get("scope"))
    questions = bank.select_session(n=n, mode=mode, scope_filter=sc)
    if not questions:
        desc = scope_mod.describe(sc)
        detail = (
            f"Nothing to serve for this filter ({desc['summary']}). "
            + (desc["warning"] or "Widen the scope, or generate questions for it.")
        ) if not sc.is_everything else (
            "Nothing in the bank yet. Add material in the Library and build a "
            "question set from it — adaptive practice needs something to draw from."
        )
        raise HTTPException(status_code=409, detail=detail)
    return {"questions": questions, "mode": mode, "requested": n,
            "scope": scope_mod.describe(sc)}


@router.get("/select/recommend")
def recommend():
    """Which of the existing modes fits right now, and why.

    Deliberately a CHOICE among the modes rather than a seventh mixture: the
    reason can then be stated in one sentence, and anything it recommends is
    something you could have picked yourself.
    """
    from . import organizer, scheduler
    now = time.time()
    pool = bank.candidates(now)
    if not pool:
        return {"mode": "mixed", "available": 0,
                "title": "Nothing to practise yet",
                "why": "Add material and build a question set first."}

    due = [c for c in pool if scheduler.is_due(c, now)]
    weak = [c for c in pool if c.attempts > 0 and c.effective < 0.5]
    fresh = [c for c in pool if c.attempts == 0]

    soon = None
    try:
        # organizer.get_exam reports days_left, not a "past" flag - reading a
        # key that does not exist would have treated every sat exam as upcoming.
        upcoming = [e for e in organizer.list_exams()
                    if e.get("days_left") is not None and e["days_left"] >= 0]
        if upcoming:
            nxt = min(upcoming, key=lambda e: e["days_left"])
            if nxt["days_left"] <= 14:
                soon = nxt
    except Exception:                                  # noqa: BLE001
        soon = None

    # Order matters: forgetting is time-critical, an exam is date-critical, and
    # a known weakness beats new ground. New material is what is left when
    # there is nothing owed.
    if len(due) >= 5:
        pick = ("spaced", f"{len(due)} concepts are due for review",
                "Review what is slipping")
    elif soon:
        pick = ("exam_cram", f"{soon['name']} is in {soon['days_left']} days",
                f"Work toward {soon['name']}")
    elif weak:
        pick = ("weak_areas", f"{len(weak)} concepts are measurably weak",
                "Go at your weak areas")
    elif due:
        pick = ("spaced", f"{len(due)} concepts are due for review",
                "Review what is slipping")
    elif fresh:
        pick = ("new_material", f"{len(fresh)} concepts you have not seen yet",
                "Start on new material")
    else:
        pick = ("mixed", "nothing is overdue and nothing is measurably weak",
                "A balanced mixed set")

    mode, why, title = pick
    return {"mode": mode, "title": title, "why": why,
            "available": len(pool), "due": len(due),
            "weak": len(weak), "new": len(fresh),
            "exam": soon["name"] if soon else None}


@router.get("/scope/options")
def scope_options():
    """Terms, courses and exams the practice filter can offer."""
    return scope_mod.options()


@router.post("/scope/describe")
def scope_describe(body: dict = Body(...)):
    """What a filter would do, before she commits to it."""
    return scope_mod.describe(scope_mod.Scope.from_dict(body.get("scope")))


@router.get("/select/modes")
def select_modes():
    from . import scheduler
    pool = bank.candidates()
    return {
        "modes": [
            {"id": m, "shares": shares,
             "label": m.replace("_", " ").title()}
            for m, shares in scheduler.MODES.items()
        ],
        "available_concepts": len(pool),
        "due_now": sum(1 for c in pool if scheduler.is_due(c, time.time())),
    }


@router.get("/plan/today")
def plan_today():
    """The adaptive daily recommendation.

    Counts come from the actual state of the bank, so an empty review queue
    produces a smaller, honest plan rather than a padded one.
    """
    from . import scheduler
    now = time.time()
    pool = bank.candidates(now)
    if not pool:
        return {"empty": True,
                "message": "No questions banked yet. Generate a set to get started."}

    due = [c for c in pool if scheduler.is_due(c, now)]
    weak_hy = sorted(
        (c for c in pool if c.effective < 0.5 and c.high_yield >= 0.7),
        key=scheduler.priority, reverse=True)
    fresh = [c for c in pool if c.attempts == 0]

    blocks = []
    if due:
        blocks.append({"kind": "spaced", "count": min(len(due), 12),
                       "label": "spaced repetition due"})
    if weak_hy:
        blocks.append({"kind": "high_yield", "count": min(len(weak_hy), 8),
                       "label": "high-yield weaknesses"})
    if fresh:
        blocks.append({"kind": "new", "count": min(len(fresh), 5),
                       "label": "new concepts"})
    blocks.append({"kind": "mixed", "count": 5, "label": "mixed clinical questions"})

    total = sum(b["count"] for b in blocks)
    top = max(pool, key=scheduler.priority)
    top_row = db.q1("SELECT name FROM concept WHERE id = ?", top.concept_id)

    return {
        "empty": False,
        "blocks": blocks,
        "total": total,
        # ~45s/question is a deliberately unhurried estimate. Extended time is
        # an accommodation; a tight estimate would read as a deadline.
        "estimated_minutes": round(total * 0.75),
        "top_priority": {
            "concept_id": top.concept_id,
            "name": top_row["name"] if top_row else top.concept_id,
            "effective": round(top.effective, 3),
        },
    }


# ------------------------------------------------------- progression

@router.get("/game/state")
def game_state():
    return gamify.state()


@router.get("/game/achievements")
def game_achievements():
    return {"achievements": gamify.achievements()}


@router.get("/game/map")
def game_map():
    """Organ systems as territories, with boss readiness."""
    return {"territories": gamify.territories()}


@router.post("/game/boss")
def game_boss(body: dict = Body(...)):
    topic_id = body.get("topic_id")
    if not topic_id:
        raise HTTPException(status_code=400, detail="Pick a system first.")
    questions = bank.boss_session(topic_id, n=int(body.get("n") or 8))
    if not questions:
        raise HTTPException(
            status_code=409,
            detail="No questions banked for that system yet.")
    return {"questions": questions, "mode": "boss"}


@router.get("/analytics")
def analytics_report():
    """How she learns - only the parts the data actually supports."""
    return analytics.report()
