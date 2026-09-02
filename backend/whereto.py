"""
After a wrong answer: where to go and re-read.

"You got this wrong" is only half an answer. The other half is where to look,
and the two useful places are different in kind:

  * THE LECTURE, because that is what the exam is written from. The question
    carries the slide it came from and the objective it tests, so this is a
    direct pointer.
  * FIRST AID, because that is where the same idea is compressed to its
    examinable core. This is derived, not stored: the concept knows its topic,
    and the textbook ingestion recorded which pages of THAT topic sit where.

What this deliberately does not do is reproduce the book. The First Aid
ingestion only ever stored section names, topics and page numbers - never the
text - so what comes back here is "Renal / Physiology, pages 583-604", a
pointer into the copy she already owns. Anything more would be republishing a
copyrighted textbook inside a study app.

A pointer that might be wrong is worse than none, so page ranges are returned
only when the concept's topic actually matches an ingested section. Silence is
the correct output when the book has not been indexed.
"""

from __future__ import annotations

from . import db


def _lecture_refs(qrow) -> list[dict]:
    """Where in the uploaded material this question came from."""
    out = []
    for ref in (db.unjs(qrow["source_refs"], []) or []):
        if not isinstance(ref, dict):
            continue
        label = (ref.get("label") or "").strip()
        if not label:
            continue
        # Strip the old random upload prefix so the name reads as she named it.
        if len(label) > 9 and label[8] == "_" and all(
                c in "0123456789abcdef" for c in label[:8]):
            label = label[9:]
        out.append({"label": label, "kind": ref.get("kind", "lecture")})
    return out


def _textbook(topic_id: str | None) -> list[dict]:
    """Page ranges in First Aid for this topic, and its parent if need be."""
    if not topic_id:
        return []

    rows = db.q(
        "SELECT ss.section_path, ss.page_start, ss.page_end, s.title "
        "FROM source_section ss JOIN source s ON s.id = ss.source_id "
        "WHERE ss.topic_id = ? ORDER BY ss.page_start", topic_id)

    if not rows:
        # A concept may sit on a leaf topic while the book was indexed at the
        # parent. Widening one level is honest; guessing further is not.
        parent = db.q1("SELECT parent_id FROM topic WHERE id = ?", topic_id)
        if parent and parent["parent_id"]:
            rows = db.q(
                "SELECT ss.section_path, ss.page_start, ss.page_end, s.title "
                "FROM source_section ss JOIN source s ON s.id = ss.source_id "
                "WHERE ss.topic_id = ? ORDER BY ss.page_start",
                parent["parent_id"])

    return [{
        "book": r["title"],
        "section": r["section_path"],
        "pages": (f"{r['page_start']}-{r['page_end']}"
                  if r["page_start"] and r["page_end"] and
                  r["page_end"] != r["page_start"]
                  else str(r["page_start"] or "")),
    } for r in rows if r["page_start"]]


def for_question(question_id: str) -> dict:
    """Everything known about where to re-read this."""
    q = db.q1("SELECT * FROM question WHERE id = ?", question_id)
    if q is None:
        raise KeyError(f"no such question: {question_id}")

    cols = {c["name"] for c in db.q("PRAGMA table_info(question)")}
    slide = (q["source_ref"] if "source_ref" in cols else "") or ""

    # Objectives are stored as ids; the human-readable text lives with the
    # concept's source material, so surface the ids and let the UI label them.
    objectives = db.unjs(q["objective"], []) if q["objective"] else []
    if isinstance(objectives, str):        # pre-schema-10 rows held free text
        slide = slide or objectives
        objectives = []

    crow = db.q1(
        "SELECT c.id, c.name, c.topic_id, t.path FROM question_concept qc "
        "JOIN concept c ON c.id = qc.concept_id "
        "LEFT JOIN topic t ON t.id = c.topic_id "
        "WHERE qc.question_id = ? ORDER BY qc.primary_ DESC", question_id)

    return {
        "question_id": question_id,
        "concept": {"id": crow["id"], "name": crow["name"],
                    "topic": crow["path"]} if crow else None,
        "lecture": {
            "sources": _lecture_refs(q),
            "locator": slide,
        },
        "textbook": _textbook(crow["topic_id"] if crow else None),
        "objectives": objectives,
    }
