"""
The question bank and the attempt recorder.

This is the seam between the existing generator (which produces questions for
one session and forgets them) and the new system of record. Generated questions
now land in a durable bank keyed by stable concept ids, and every answer she
gives is written to the append-only `attempt` table.
"""

from __future__ import annotations

import time
import uuid

from . import db, mastery as mastery_math, taxonomy

# The generator's retrieval-ladder formats carry an implied cognitive level.
# Explicit difficulty on the question always wins; this is only the fallback.
FORMAT_DEFAULT_DIFFICULTY = {
    "recognition": 1,
    "visual_map": 1,
    "cued_recall": 2,
    "discrimination": 3,
    "application": 3,
}

VALID_CONFIDENCE = {"knew", "unsure", "guessed"}


# ------------------------------------------------------- persisting analysis

def persist_analysis(analysis: dict, source_ref: dict | None = None) -> dict[str, str]:
    """Turn one analyze() result into durable concepts.

    Returns a map from the generator's session-local ids ("c1") to stable
    concept ids, so the questions generated alongside it can be linked.
    """
    topic_hint = analysis.get("subject_area") or analysis.get("title") or ""
    default_topic = taxonomy.resolve_topic(topic_hint)
    refs = [source_ref] if source_ref else []

    mapping: dict[str, str] = {}
    confusable: list[tuple[str, str]] = []

    for c in analysis.get("concepts", []):
        local = c.get("id") or c.get("name")
        topic_id = taxonomy.resolve_topic(c.get("topic") or topic_hint) or default_topic
        cid = taxonomy.resolve_concept(
            c["name"],
            topic_id=topic_id,
            one_line=c.get("one_line", ""),
            load_risk=c.get("load_risk", ""),
            yield_tier=c.get("yield", "medium"),
            source_refs=refs,
        )
        mapping[local] = cid

        other = (c.get("confusable_with") or "").strip()
        if other and other.lower() not in ("none", "n/a", "nothing"):
            confusable.append((cid, other))

    # Edges are added after every concept exists, so a "confusable with" target
    # that is itself in this batch links to the real row instead of a new one.
    for cid, other_name in confusable:
        other_id = taxonomy.resolve_concept(
            other_name, topic_id=db.q1(
                "SELECT topic_id FROM concept WHERE id = ?", cid)["topic_id"]
        )
        taxonomy.link(cid, other_id, "confusable_with")

    return mapping


# --------------------------------------------------------- saving questions

def save_questions(
    questions: list[dict],
    mapping: dict[str, str],
    *,
    source_ref: dict | None = None,
) -> list[dict]:
    """Persist generated questions.

    Returns one row per stored question carrying the generator's local id, so
    the caller can map the questions it is holding onto their durable ids.
    """
    now = time.time()
    saved: list[dict] = []

    for q in questions:
        local = q.get("concept_id")
        cid = mapping.get(local)
        if cid is None:
            # A question whose concept we cannot resolve would be an orphan with
            # no mastery target, which is worse than dropping it.
            continue

        local_id = q.get("id") or uuid.uuid4().hex[:12]
        qid = f"{cid}#{local_id}"[:200]
        fmt = q.get("type", "recognition")
        difficulty = int(q.get("difficulty") or FORMAT_DEFAULT_DIFFICULTY.get(fmt, 1))
        difficulty = max(1, min(4, difficulty))

        hy = db.q1("SELECT high_yield, topic_id FROM concept WHERE id = ?", cid)

        db.run(
            "INSERT OR REPLACE INTO question (id, stem, premise_table, options, "
            "answer_text, accepted, cue, why_right, derive_from, visual, memory_hook, "
            "key_clue, takeaway, difficulty, fmt, topic_id, high_yield, source_refs, "
            "objective, source_ref, created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            qid, q.get("stem", ""), q.get("premise_table"),
            db.js(q.get("options") or []), q.get("answer_text"),
            db.js(q.get("accepted_answers") or []), q.get("cue", ""),
            q.get("why_right", ""), q.get("derive_from", ""), q.get("visual", ""),
            q.get("memory_hook", ""), q.get("key_clue", ""), q.get("takeaway", ""),
            difficulty, fmt, hy["topic_id"] if hy else "unsorted",
            hy["high_yield"] if hy else 0.5,
            db.js([source_ref] if source_ref else []),
            # This column was being fed q["source_ref"] - the slide number -
            # so it held the wrong data entirely. It stores the objectives the
            # question tests, which is what it was named for.
            db.js(q.get("objective_ids") or []),
            q.get("source_ref", ""), now,
        )
        db.run(
            "INSERT OR REPLACE INTO question_concept (question_id, concept_id, primary_) "
            "VALUES (?, ?, 1)", qid, cid,
        )
        saved.append({
            "local_id": local_id,
            "question_id": qid,
            "concept_id": cid,
            "difficulty": difficulty,
        })

    return saved


def load_questions(ids: list[str]) -> list[dict]:
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = db.q(f"SELECT * FROM question WHERE id IN ({marks})", *ids)
    by_id = {r["id"]: _question_dict(r) for r in rows}
    return [by_id[i] for i in ids if i in by_id]


def _question_dict(row) -> dict:
    d = dict(row)
    d["options"] = db.unjs(d["options"], [])
    d["accepted_answers"] = db.unjs(d.pop("accepted"), [])
    d["source_refs"] = db.unjs(d["source_refs"], [])
    d["type"] = d.pop("fmt")
    cids = db.q("SELECT concept_id FROM question_concept WHERE question_id = ?", d["id"])
    d["concept_ids"] = [r["concept_id"] for r in cids]
    d["concept_id"] = d["concept_ids"][0] if d["concept_ids"] else None
    return d


# --------------------------------------------------------------- attempts

def record_attempt(
    *,
    question_id: str,
    correct: bool,
    given: str = "",
    confidence: str = "unsure",
    used_cue: bool = False,
    error_type: str | None = None,
    rt_ms: int | None = None,
    session_id: str | None = None,
) -> dict:
    """Write one attempt and refresh the affected concepts' mastery.

    Returns before/after mastery so the UI can animate the change and show
    "3 more to master this".
    """
    q = db.q1("SELECT id, difficulty, fmt FROM question WHERE id = ?", question_id)
    if q is None:
        raise KeyError(f"unknown question: {question_id}")

    if confidence not in VALID_CONFIDENCE:
        # An unrecognized self-report is treated as the neutral case rather than
        # silently crediting or penalizing her for a UI bug.
        confidence = "unsure"

    # If she needed the cue, she did not retrieve it unaided. Cap the claim at
    # "unsure" - this is the word-finding case, not a knowledge claim.
    if used_cue and confidence == "knew":
        confidence = "unsure"

    concept_ids = [
        r["concept_id"]
        for r in db.q("SELECT concept_id FROM question_concept WHERE question_id = ?",
                      question_id)
    ]
    if not concept_ids:
        raise KeyError(f"question {question_id} has no concept")

    now = time.time()
    result = {"concepts": []}

    for cid in concept_ids:
        before = current(cid)
        db.run(
            "INSERT INTO attempt (session_id, question_id, concept_id, ts, given, "
            "correct, confidence, used_cue, error_type, difficulty, fmt, rt_ms, "
            "mastery_before) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            session_id, question_id, cid, now, given, 1 if correct else 0,
            confidence, 1 if used_cue else 0, error_type,
            q["difficulty"], q["fmt"], rt_ms, before.effective,
        )
        _reschedule(cid, correct=correct, confidence=confidence, now=now)
        after = refresh(cid)
        db.run(
            "UPDATE attempt SET mastery_after = ? WHERE id = (SELECT MAX(id) FROM attempt)",
            after.effective,
        )
        result["concepts"].append({
            "concept_id": cid,
            "name": _concept_name(cid),
            "before": round(before.effective, 4),
            "after": round(after.effective, 4),
            "delta": round(after.effective - before.effective, 4),
            "band": after.band,
            "band_before": before.band,
            "streak": after.streak,
            "to_next_band": to_next_band(after),
        })

    from . import gamify

    result["xp"] = gamify.award(gamify.xp_for_attempt(
        correct=correct, difficulty=q["difficulty"], confidence=confidence,
        used_cue=used_cue))
    result["streak"] = gamify.current_streak()
    result["unlocked"] = gamify.check_achievements()
    return result


def _reschedule(cid: str, *, correct: bool, confidence: str, now: float) -> None:
    """Advance the spaced-repetition schedule for one concept.

    Runs before refresh() so the new interval feeds straight into the stability
    term, and a well-scheduled concept immediately decays more slowly.
    """
    from . import scheduler

    row = db.q1("SELECT ease, interval_d, reps, lapses FROM review WHERE concept_id = ?", cid)
    ease = row["ease"] if row else 2.5
    interval = row["interval_d"] if row else 0.0
    reps = row["reps"] if row else 0
    lapses = row["lapses"] if row else 0

    nxt = scheduler.schedule_next(
        correct=correct, ease=ease, interval_d=interval, reps=reps, confidence=confidence)

    db.run(
        "INSERT INTO review (concept_id, ease, interval_d, due_at, reps, lapses) "
        "VALUES (?,?,?,?,?,?) "
        "ON CONFLICT(concept_id) DO UPDATE SET ease=excluded.ease, "
        "interval_d=excluded.interval_d, due_at=excluded.due_at, reps=excluded.reps, "
        "lapses=excluded.lapses",
        cid, nxt["ease"], nxt["interval_d"], now + nxt["interval_d"] * 86400.0,
        nxt["reps"], lapses + (1 if nxt["lapsed"] else 0),
    )


def _concept_name(cid: str) -> str:
    row = db.q1("SELECT name FROM concept WHERE id = ?", cid)
    return row["name"] if row else cid


# ---------------------------------------------------------------- mastery

def _attempts_for(cid: str) -> list[mastery_math.Attempt]:
    rows = db.q(
        "SELECT ts, correct, difficulty, confidence, fmt, rt_ms FROM attempt "
        "WHERE concept_id = ? ORDER BY ts DESC LIMIT 200", cid,
    )
    return [
        mastery_math.Attempt(
            ts=r["ts"], correct=bool(r["correct"]), difficulty=r["difficulty"],
            confidence=r["confidence"], fmt=r["fmt"] or "", rt_ms=r["rt_ms"],
        )
        for r in rows
    ]


def refresh(cid: str, now: float | None = None) -> mastery_math.Mastery:
    """Recompute mastery from attempt history and write the cache."""
    now = now or time.time()
    sched = db.q1("SELECT interval_d, ease FROM review WHERE concept_id = ?", cid)
    m = mastery_math.compute(
        _attempts_for(cid),
        now=now,
        interval_d=sched["interval_d"] if sched else 0.0,
        ease=sched["ease"] if sched else 2.5,
    )
    db.run(
        "INSERT INTO mastery (concept_id, mastery, est_confidence, retention, effective, "
        "band, attempts, correct, streak, longest_streak, variance, by_difficulty, "
        "by_format, avg_rt_ms, last_reviewed, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(concept_id) DO UPDATE SET "
        "mastery=excluded.mastery, est_confidence=excluded.est_confidence, "
        "retention=excluded.retention, effective=excluded.effective, band=excluded.band, "
        "attempts=excluded.attempts, correct=excluded.correct, streak=excluded.streak, "
        "longest_streak=excluded.longest_streak, variance=excluded.variance, "
        "by_difficulty=excluded.by_difficulty, by_format=excluded.by_format, "
        "avg_rt_ms=excluded.avg_rt_ms, last_reviewed=excluded.last_reviewed, "
        "updated_at=excluded.updated_at",
        cid, m.mastery, m.est_confidence, m.retention, m.effective, m.band,
        m.attempts, m.correct, m.streak, m.longest_streak, m.variance,
        db.js(m.by_difficulty), db.js(m.by_format), m.avg_rt_ms,
        m.last_reviewed, now,
    )
    return m


def current(cid: str) -> mastery_math.Mastery:
    """Cached mastery, with decay applied as of now.

    Retention is recomputed on read rather than on write - otherwise a concept
    would only appear to decay when something else touched it.
    """
    row = db.q1("SELECT * FROM mastery WHERE concept_id = ?", cid)
    if row is None:
        return mastery_math.Mastery()

    m = mastery_math.Mastery(
        mastery=row["mastery"], est_confidence=row["est_confidence"],
        retention=row["retention"], effective=row["effective"], band=row["band"],
        attempts=row["attempts"], correct=row["correct"], streak=row["streak"],
        longest_streak=row["longest_streak"], variance=row["variance"],
        by_difficulty=db.unjs(row["by_difficulty"], {}),
        by_format=db.unjs(row["by_format"], {}),
        avg_rt_ms=row["avg_rt_ms"], last_reviewed=row["last_reviewed"],
    )
    if m.last_reviewed:
        sched = db.q1("SELECT interval_d, ease FROM review WHERE concept_id = ?", cid)
        m.stability_days = mastery_math.stability_days(
            sched["interval_d"] if sched else 0.0,
            sched["ease"] if sched else 2.5,
            m.mastery,
        )
        days = max(0.0, (time.time() - m.last_reviewed) / mastery_math.DAY)
        m.retention = mastery_math.retention_at(days, m.stability_days)
        m.effective = min(1.0, m.mastery * (0.6 + 0.4 * m.retention))
        m.band = mastery_math.band_for(m.effective, m.retention, m.variance, m.attempts)
    return m


def rebuild_all() -> int:
    """Recompute every concept's mastery from history.

    This is what makes the mastery formula safe to change: it is a backfill,
    not a migration.
    """
    now = time.time()
    rows = db.q("SELECT id FROM concept")
    for r in rows:
        refresh(r["id"], now)
    return len(rows)


# ------------------------------------------------------------- momentum

BAND_FLOORS = [
    ("orange", mastery_math.BAND_RED),
    ("yellow", mastery_math.BAND_ORANGE),
    ("light_green", mastery_math.BAND_YELLOW),
    ("dark_green", mastery_math.BAND_LGREEN),
]


def to_next_band(m: mastery_math.Mastery) -> dict | None:
    """How close she is to the next color - the "3 more questions" line.

    Estimated by simulating additional correct L2 "unsure" answers, which is a
    deliberately conservative assumption: the real number is usually smaller,
    and a promise that undershoots is better than one that overshoots.
    """
    for name, floor in BAND_FLOORS:
        if m.effective < floor:
            target = floor
            break
    else:
        return None

    # Two probes, weakest first. If routine Level 2 work gets her there, say so.
    # If only harder items can, say that instead - because it is true and it is
    # the actionable part: a concept practiced only at Level 1-2 has a credit
    # ceiling below the mastered threshold and will never turn dark green.
    probes = [
        (mastery_math.Attempt(ts=0, correct=True, difficulty=2, confidence="unsure"), False),
        (mastery_math.Attempt(ts=0, correct=True, difficulty=3, confidence="knew"), True),
    ]
    for probe, needs_harder in probes:
        sim = list(_simulate_state(m))
        for n in range(1, 13):
            sim.insert(0, probe)
            num = den = 0.0
            for rank, a in enumerate(sim[:mastery_math.WINDOW]):
                w = mastery_math.RECENCY_LAMBDA ** rank
                num += mastery_math.credit(a) * w
                den += w
            val = (num + mastery_math.PRIOR_STRENGTH * mastery_math.PRIOR) / \
                  (den + mastery_math.PRIOR_STRENGTH)
            if min(1.0, val * (0.6 + 0.4 * m.retention)) >= target:
                return {"band": name, "questions": n, "needs_harder": needs_harder}
    return None


def _simulate_state(m: mastery_math.Mastery):
    """Approximate the recent window from cached counts.

    The cache does not store the raw sequence, so this reconstructs a window
    with the same accuracy at the median difficulty. Good enough for a
    motivational estimate; never used for the real mastery number.
    """
    n = min(m.attempts, mastery_math.WINDOW)
    if n == 0:
        return []
    acc = (m.correct / m.attempts) if m.attempts else 0.0
    n_correct = round(acc * n)
    out = []
    for i in range(n):
        out.append(mastery_math.Attempt(
            ts=0, correct=i < n_correct, difficulty=2, confidence="unsure"))
    return out


# ------------------------------------------------------- adaptive selection

MISSED_WINDOW_HOURS = 48


def candidates(now: float | None = None, scope_filter=None) -> list:
    """Build the selector's input from the database.

    Everything the scheduler needs is assembled here so that scheduler.py stays
    pure and testable against hand-built pools.
    """
    from . import scheduler, scope as scope_mod

    now = now or time.time()
    cutoff = now - MISSED_WINDOW_HOURS * 3600

    # None means "no restriction"; an empty set means "the filter matched
    # nothing", which must serve nothing rather than silently serving all.
    allowed = None
    if scope_filter is not None:
        allowed = scope_mod.allowed(scope_filter)

    missed = {
        r["concept_id"] for r in db.q(
            "SELECT DISTINCT concept_id FROM attempt WHERE correct = 0 AND ts > ?",
            cutoff)
    }
    # A concept sitting next to a recently-missed one in the graph: the signal
    # that distinguishes one isolated gap from a whole broken cluster.
    neighbors: set[str] = set()
    for cid in missed:
        for r in db.q("SELECT dst FROM concept_edge WHERE src = ?", cid):
            if r["dst"] not in missed:
                neighbors.add(r["dst"])

    exams = db.q("SELECT date, topic_ids FROM exam")
    exam_topics: dict[str, float] = {}
    for e in exams:
        try:
            days = (time.mktime(time.strptime(e["date"], "%Y-%m-%d")) - now) / 86400.0
        except (ValueError, TypeError):
            continue
        urgency = scheduler.exam_urgency(days)
        for tid in db.unjs(e["topic_ids"], []):
            exam_topics[tid] = max(exam_topics.get(tid, 0.0), urgency)

    # Which (format, difficulty) variants exist per concept, and when each was
    # last served. This is what makes variant rotation possible.
    cells: dict[str, list] = {}
    for r in db.q(
        "SELECT qc.concept_id, q.fmt, q.difficulty, MAX(a.ts) AS last_seen "
        "FROM question q "
        "JOIN question_concept qc ON qc.question_id = q.id "
        "LEFT JOIN attempt a ON a.question_id = q.id "
        "WHERE q.retired = 0 "
        "GROUP BY qc.concept_id, q.fmt, q.difficulty"
    ):
        cells.setdefault(r["concept_id"], []).append(
            (r["fmt"], r["difficulty"], r["last_seen"]))

    out = []
    for r in db.q(
        # What her professor stressed rides on top of the textbook weighting.
        # Kept as a separate column so the two stay distinguishable, but they
        # are summed here - otherwise recording emphasis would change nothing.
        "SELECT c.id, c.topic_id, "
        "       MIN(1.0, c.high_yield + COALESCE(c.emphasis_boost, 0)) AS high_yield "
        "FROM concept c WHERE c.retired = 0"
    ):
        cid = r["id"]
        if allowed is not None and cid not in allowed:
            continue
        if cid not in cells:
            continue  # no questions exist for it yet - nothing to serve
        m = current(cid)
        sched = db.q1("SELECT due_at FROM review WHERE concept_id = ?", cid)
        out.append(scheduler.Candidate(
            concept_id=cid,
            effective=m.effective,
            retention=m.retention,
            high_yield=r["high_yield"],
            attempts=m.attempts,
            difficulty_gap=mastery_math.difficulty_gap(m),
            due_at=sched["due_at"] if sched else None,
            exam_urgency=exam_topics.get(r["topic_id"], 0.0),
            last_attempt_ts=m.last_reviewed,
            missed_recently=cid in missed,
            related_to_missed=cid in neighbors,
            available_cells=cells[cid],
        ))
    return out


def select_session(n: int = 10, mode: str = "mixed", scope_filter=None) -> list[dict]:
    """Pick n questions adaptively. The heart of Phase 2."""
    from . import scheduler

    now = time.time()
    pool = candidates(now, scope_filter=scope_filter)
    if not pool:
        return []

    # Ask for extra candidates: some will resolve to a question already served
    # this session, and a "10-question session" that quietly delivers 8 is a
    # broken promise the UI has already made.
    picked = scheduler.compose(pool, n=n * 3, mode=mode, now=now)

    questions: list[dict] = []
    served: set[str] = set()

    for c in picked:
        if len(questions) >= n:
            break
        qid = _question_for(c, served)
        if qid is None:
            continue
        served.add(qid)
        q = load_questions([qid])
        if q:
            q[0]["_why_selected"] = {
                "effective": round(c.effective, 3),
                "retention": round(c.retention, 3),
                "priority": round(scheduler.priority(c), 4),
                # All of them, not just the most specific: a concept is usually
                # eligible for several, and showing one label hides the reason.
                "buckets": sorted(scheduler.buckets_for(c, now)),
                "bucket": scheduler.bucket_of(c, now),
            }
            questions.append(q[0])

    return questions


def _question_for(c, served: set[str]) -> str | None:
    """Best unserved question for a concept: preferred variant, then any other."""
    from . import scheduler

    cell = scheduler.pick_cell(c)
    if cell is not None:
        fmt, difficulty, _ = cell
        row = db.q1(
            "SELECT q.id FROM question q "
            "JOIN question_concept qc ON qc.question_id = q.id "
            "LEFT JOIN attempt a ON a.question_id = q.id "
            "WHERE qc.concept_id = ? AND q.fmt = ? AND q.difficulty = ? AND q.retired = 0 "
            "GROUP BY q.id ORDER BY COALESCE(MAX(a.ts), 0) ASC LIMIT 1",
            c.concept_id, fmt, difficulty,
        )
        if row and row["id"] not in served:
            return row["id"]

    # Fall back to any other variant of the same concept, least recently seen.
    for row in db.q(
        "SELECT q.id FROM question q "
        "JOIN question_concept qc ON qc.question_id = q.id "
        "LEFT JOIN attempt a ON a.question_id = q.id "
        "WHERE qc.concept_id = ? AND q.retired = 0 "
        "GROUP BY q.id ORDER BY COALESCE(MAX(a.ts), 0) ASC",
        c.concept_id,
    ):
        if row["id"] not in served:
            return row["id"]
    return None


# --------------------------------------------------------------- boss

def boss_session(topic_id: str, n: int = 8) -> list[dict]:
    """A system's boss challenge: its hardest items across its weakest concepts.

    Prefers Level 3 and 4 questions, spread across concepts rather than
    hammering one, so it tests integration rather than a single fact. The
    3-4 element ceiling still applies inside each question - that is enforced
    by the generator, not relaxed here because the question is called a boss.
    """
    from . import scheduler

    rows = db.q(
        "SELECT DISTINCT qc.concept_id, q.id AS qid, q.difficulty "
        "FROM question q JOIN question_concept qc ON qc.question_id = q.id "
        "JOIN concept c ON c.id = qc.concept_id "
        "JOIN topic t ON t.id = c.topic_id "
        "WHERE q.retired = 0 AND (t.id = ? OR t.parent_id = ?) "
        "ORDER BY q.difficulty DESC", topic_id, topic_id)
    if not rows:
        return []

    by_concept: dict[str, list] = {}
    for r in rows:
        by_concept.setdefault(r["concept_id"], []).append(r)

    # Weakest concepts first, one question each, then round again if short.
    order = sorted(by_concept, key=lambda cid: current(cid).effective)
    picked: list[str] = []
    round_no = 0
    while len(picked) < n and round_no < 4:
        for cid in order:
            if len(picked) >= n:
                break
            pool = [r["qid"] for r in by_concept[cid] if r["qid"] not in picked]
            if pool:
                picked.append(pool[0])
        round_no += 1

    questions = load_questions(picked)
    for q in questions:
        q["_boss"] = True
    return questions
