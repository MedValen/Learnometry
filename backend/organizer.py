"""
Terms, courses, exams - her own filing system.

This is a second axis, deliberately not folded into the First Aid taxonomy. The
taxonomy answers "what kind of knowledge is this"; a term answers "when do I
need it". Keeping them apart is what lets a concept drilled for the Renal
midterm carry its entire history into the final, instead of being re-created
under a new heading and starting from zero.

An exam therefore *references* concepts and topics. It never owns them.
"""

from __future__ import annotations

import time
import uuid
from datetime import date, datetime

from . import bank, db, scheduler, taxonomy

EXAM_KINDS = ["quiz", "midterm", "final", "nbme", "shelf", "practical", "other"]


def _uid(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def days_until(iso_date: str | None) -> float | None:
    if not iso_date:
        return None
    try:
        target = datetime.strptime(iso_date, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None
    return (target - date.today()).days


# ------------------------------------------------------------------ terms

def create_term(name: str, starts: str = "", ends: str = "", active: bool = True) -> dict:
    tid = _uid("term")
    if active:
        db.run("UPDATE term SET active = 0")
    order = (db.q1("SELECT COALESCE(MAX(sort_order), 0) m FROM term")["m"] or 0) + 1
    db.run(
        "INSERT INTO term (id, name, starts, ends, active, sort_order, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        tid, name.strip(), starts, ends, 1 if active else 0, order, time.time(),
    )
    return get_term(tid)


def get_term(tid: str) -> dict:
    row = db.q1("SELECT * FROM term WHERE id = ?", tid)
    if row is None:
        raise KeyError(f"no such term: {tid}")
    d = dict(row)
    d["courses"] = [dict(r) for r in db.q(
        "SELECT * FROM course WHERE term_id = ? ORDER BY sort_order", tid)]
    d["exams"] = list_exams(term_id=tid)
    return d


def list_terms() -> list[dict]:
    out = []
    for row in db.q("SELECT * FROM term ORDER BY sort_order DESC"):
        d = dict(row)
        d["course_count"] = db.q1(
            "SELECT COUNT(*) n FROM course WHERE term_id = ?", row["id"])["n"]
        d["exam_count"] = db.q1(
            "SELECT COUNT(*) n FROM exam WHERE term_id = ?", row["id"])["n"]
        out.append(d)
    return out


def set_active_term(tid: str) -> None:
    db.run("UPDATE term SET active = 0")
    db.run("UPDATE term SET active = 1 WHERE id = ?", tid)


def delete_term(tid: str) -> None:
    """Detach rather than cascade - losing exam history to a mis-click is worse
    than an orphaned course row."""
    db.run("UPDATE course SET term_id = NULL WHERE term_id = ?", tid)
    db.run("UPDATE exam SET term_id = NULL WHERE term_id = ?", tid)
    db.run("DELETE FROM term WHERE id = ?", tid)


# ---------------------------------------------------------------- courses

def create_course(term_id: str | None, name: str, code: str = "") -> dict:
    cid = _uid("crs")
    order = (db.q1("SELECT COALESCE(MAX(sort_order), 0) m FROM course")["m"] or 0) + 1
    db.run(
        "INSERT INTO course (id, term_id, name, code, sort_order, created_at) "
        "VALUES (?,?,?,?,?,?)",
        cid, term_id, name.strip(), code.strip(), order, time.time(),
    )
    return dict(db.q1("SELECT * FROM course WHERE id = ?", cid))


def list_courses(term_id: str | None = None) -> list[dict]:
    if term_id:
        rows = db.q("SELECT * FROM course WHERE term_id = ? ORDER BY sort_order", term_id)
    else:
        rows = db.q("SELECT * FROM course ORDER BY sort_order")
    out = []
    for r in rows:
        d = dict(r)
        d["exam_count"] = db.q1(
            "SELECT COUNT(*) n FROM exam WHERE course_id = ?", r["id"])["n"]
        out.append(d)
    return out


def delete_course(cid: str) -> None:
    db.run("UPDATE exam SET course_id = NULL WHERE course_id = ?", cid)
    db.run("DELETE FROM course WHERE id = ?", cid)


# ------------------------------------------------------------------ exams

def create_exam(
    name: str,
    exam_date: str,
    *,
    term_id: str | None = None,
    course_id: str | None = None,
    kind: str = "exam",
    topic_ids: list[str] | None = None,
    concept_ids: list[str] | None = None,
    notes: str = "",
) -> dict:
    eid = _uid("exam")
    db.run(
        "INSERT INTO exam (id, name, date, topic_ids, created_at, term_id, "
        "course_id, kind, concept_ids, notes) VALUES (?,?,?,?,?,?,?,?,?,?)",
        eid, name.strip(), exam_date, db.js(topic_ids or []), time.time(),
        term_id, course_id, kind, db.js(concept_ids or []), notes,
    )
    return get_exam(eid)


def update_exam(eid: str, **fields) -> dict:
    allowed = {"name", "date", "kind", "notes", "term_id", "course_id"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
        elif k in ("topic_ids", "concept_ids"):
            sets.append(f"{k} = ?")
            vals.append(db.js(v or []))
    if sets:
        db.run(f"UPDATE exam SET {', '.join(sets)} WHERE id = ?", *vals, eid)
    return get_exam(eid)


def get_exam(eid: str) -> dict:
    row = db.q1("SELECT * FROM exam WHERE id = ?", eid)
    if row is None:
        raise KeyError(f"no such exam: {eid}")
    d = dict(row)
    d["topic_ids"] = db.unjs(d["topic_ids"], [])
    d["concept_ids"] = db.unjs(d["concept_ids"], [])
    d["days_left"] = days_until(d["date"])
    d["urgency"] = round(scheduler.exam_urgency(d["days_left"]), 3)
    d["course"] = None
    if d.get("course_id"):
        c = db.q1("SELECT name FROM course WHERE id = ?", d["course_id"])
        d["course"] = c["name"] if c else None
    return d


def list_exams(term_id: str | None = None, upcoming_only: bool = False) -> list[dict]:
    if term_id:
        rows = db.q("SELECT id FROM exam WHERE term_id = ? ORDER BY date", term_id)
    else:
        rows = db.q("SELECT id FROM exam ORDER BY date")
    out = [get_exam(r["id"]) for r in rows]
    if upcoming_only:
        out = [e for e in out if (e["days_left"] is None or e["days_left"] >= 0)]
    return out


def delete_exam(eid: str) -> None:
    db.run("DELETE FROM exam WHERE id = ?", eid)


# ------------------------------------------------------- what's on the exam

def exam_concepts(eid: str) -> list[dict]:
    """Every concept this exam covers, via explicit list or topic subtree."""
    e = get_exam(eid)
    ids: set[str] = set(e["concept_ids"])

    for tid in e["topic_ids"]:
        # A parent topic pulls in its children, so "Renal" means all of Renal.
        for r in db.q(
            "SELECT id FROM concept WHERE retired = 0 AND (topic_id = ? OR topic_id IN "
            "(SELECT id FROM topic WHERE parent_id = ?))", tid, tid,
        ):
            ids.add(r["id"])

    out = []
    for cid in ids:
        row = db.q1(
            "SELECT c.id, c.name, c.high_yield, c.emphasis_boost, c.hy_tier, t.path "
            "FROM concept c JOIN topic t ON t.id = c.topic_id WHERE c.id = ?", cid)
        if row is None:
            continue
        m = bank.current(cid)
        out.append({
            "concept_id": cid,
            "name": row["name"],
            "topic": row["path"],
            "weight": min(1.0, row["high_yield"] + (row["emphasis_boost"] or 0)),
            "base_yield": row["high_yield"],
            "emphasis_boost": row["emphasis_boost"] or 0,
            "hy_tier": row["hy_tier"],
            "effective": round(m.effective, 4),
            "retention": round(m.retention, 4),
            "band": m.band,
            "attempts": m.attempts,
            "est_confidence": round(m.est_confidence, 4),
        })
    return out


def readiness(eid: str) -> dict:
    """How ready she is, weighted by what matters on this exam.

    Deliberately NOT a predicted score. There is no validation data behind this
    app, so a percentage claiming to forecast an exam result would be invented
    precision. This is coverage: how much of the weighted material she can
    currently recall, and how sure the system is of that.
    """
    e = get_exam(eid)
    concepts = exam_concepts(eid)
    if not concepts:
        return {
            "exam": e, "empty": True,
            "message": "Nothing mapped to this exam yet. Add topics or concepts to it.",
        }

    total_w = sum(c["weight"] for c in concepts) or 1.0
    score = sum(c["effective"] * c["weight"] for c in concepts) / total_w
    evidence = sum(c["est_confidence"] * c["weight"] for c in concepts) / total_w
    untouched = [c for c in concepts if c["attempts"] == 0]

    ranked = sorted(
        concepts,
        key=lambda c: (1 - c["effective"]) * c["weight"] * (1.3 - c["retention"]),
        reverse=True,
    )
    secure = [c for c in concepts if c["effective"] >= 0.7 and c["attempts"] >= 3]

    return {
        "exam": e,
        "empty": False,
        "readiness": round(score, 4),
        "evidence": round(evidence, 4),
        "concepts_total": len(concepts),
        "concepts_untested": len(untouched),
        "high_risk": ranked[:6],
        "likely_secure": sorted(secure, key=lambda c: -c["effective"])[:5],
        "band_counts": _band_counts(concepts),
        # Stated plainly so the number is never mistaken for a score forecast.
        "caveat": (
            "Readiness is weighted coverage of what you've mapped to this exam - "
            "not a predicted score. "
            + (f"{len(untouched)} concept(s) have no attempts yet and count as unknown."
               if untouched else "Every mapped concept has been practised at least once.")
        ),
    }


def _band_counts(concepts: list[dict]) -> dict:
    out = {"red": 0, "orange": 0, "yellow": 0, "light_green": 0, "dark_green": 0}
    for c in concepts:
        out[c["band"]] = out.get(c["band"], 0) + 1
    return out


def suggest_topics(query: str, limit: int = 12) -> list[dict]:
    """Find topics/concepts to attach to an exam."""
    norm = taxonomy.normalize_name(query)
    if not norm:
        return []
    like = f"%{query.strip()}%"
    out = []
    for r in db.q(
        "SELECT id, path AS label, 'topic' AS kind FROM topic WHERE path LIKE ? LIMIT ?",
        like, limit,
    ):
        out.append(dict(r))
    for r in db.q(
        "SELECT c.id, c.name || '  ·  ' || t.path AS label, 'concept' AS kind "
        "FROM concept c JOIN topic t ON t.id = c.topic_id "
        "WHERE c.retired = 0 AND c.name LIKE ? LIMIT ?", like, limit,
    ):
        out.append(dict(r))
    return out[:limit]
