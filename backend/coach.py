"""
Exam intel: what she was told would matter, and a conversation about it.

Two halves.

CAPTURE. "Dr. Nassar spent twenty minutes on acid-base and said it's heavily
tested." That is the instructor-emphasis signal the original spec asked for, and
it is often better evidence than any textbook weighting. Each note records who
said it and how strongly, because "the professor said it's on the exam" and "an
upperclassman thought it might come up" are not the same claim.

CONVERSATION. She can talk to the app about the exam. Every note she has
captured, plus the real mastery state of the exam's concepts, is loaded as
context - so it answers from her actual situation rather than in general.

One rule shapes the design: **emphasis proposes, she disposes.** A note can
raise a concept's priority, but only after she confirms it. A misheard remark
should not silently distort what the engine serves her for the next month, and
`emphasis_boost` is stored separately from `high_yield` so it is always visible
and always reversible.
"""

from __future__ import annotations

import time
import uuid

from . import bank, claude, db, organizer, taxonomy
from . import learner_profile

SAID_BY = ["professor", "TA", "syllabus", "upperclassman", "hunch"]

# How much a note can raise a concept's weight, by how strong the claim is.
STRENGTH_BOOST = {"mentioned": 0.10, "stressed": 0.20, "explicit": 0.30}

# Same claim from a weaker source counts for less.
SOURCE_TRUST = {"professor": 1.0, "syllabus": 1.0, "TA": 0.8,
                "upperclassman": 0.5, "hunch": 0.3}


# ------------------------------------------------------------- capture

LINK_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "description": "Concepts from the provided list that this note points at. Empty if none match - do not force a match.",
            "items": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                    "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    "why": {"type": "string"},
                },
                "required": ["concept_id", "confidence", "why"],
                "additionalProperties": False,
            },
        },
        "unmatched": {
            "type": "array",
            "description": "Things the note names that have no concept in the bank yet.",
            "items": {"type": "string"},
        },
        "restated": {
            "type": "string",
            "description": "One short line restating what she was told, in plain terms.",
        },
    },
    "required": ["concepts", "unmatched", "restated"],
    "additionalProperties": False,
}


def add_note(
    text: str,
    *,
    exam_id: str | None = None,
    course_id: str | None = None,
    said_by: str = "professor",
    strength: str = "mentioned",
    auto_link: bool = True,
) -> dict:
    if not text.strip():
        raise ValueError("Write down what you were told first.")

    nid = f"emph_{uuid.uuid4().hex[:8]}"
    db.run(
        "INSERT INTO emphasis (id, exam_id, course_id, said_by, text, strength, "
        "concept_ids, applied, created_at) VALUES (?,?,?,?,?,?,?,0,?)",
        nid, exam_id, course_id,
        said_by if said_by in SAID_BY else "professor",
        text.strip(),
        strength if strength in STRENGTH_BOOST else "mentioned",
        db.js([]), time.time(),
    )

    if auto_link:
        try:
            link_note(nid)
        except Exception:
            # Linking is a convenience. Losing her note because the API is down
            # would be the actual failure.
            pass
    return get_note(nid)


def link_note(nid: str) -> dict:
    """Work out which concepts a note refers to. Suggests only - never applies."""
    row = db.q1("SELECT * FROM emphasis WHERE id = ?", nid)
    if row is None:
        raise KeyError(f"no such note: {nid}")

    scope = []
    if row["exam_id"]:
        scope = [(c["concept_id"], c["name"], c["topic"])
                 for c in organizer.exam_concepts(row["exam_id"])]
    if not scope:
        scope = [(r["id"], r["name"], r["path"]) for r in db.q(
            "SELECT c.id, c.name, t.path FROM concept c "
            "JOIN topic t ON t.id = c.topic_id WHERE c.retired = 0 LIMIT 400")]
    if not scope:
        return get_note(nid)

    listing = "\n".join(f"- {cid} | {name} | {topic}" for cid, name, topic in scope)
    prompt = (
        "She wrote down something she was told about an upcoming exam:\n\n"
        f"  \"{row['text']}\"\n\n"
        "Match it against the concepts already in her question bank:\n\n"
        f"{listing}\n\n"
        "Return only concepts the note genuinely points at. An empty list is a "
        "correct answer when nothing matches - a forced match would quietly "
        "raise the priority of the wrong material for weeks. List anything the "
        "note names that has no concept yet under `unmatched`."
    )

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": prompt}],
        schema=LINK_SCHEMA,
        max_tokens=4000,
        effort="medium",
        task="note_link",
    )
    result = claude.json_of(msg)

    valid = {cid for cid, _, _ in scope}
    matched = [c for c in result["concepts"] if c["concept_id"] in valid]

    db.run("UPDATE emphasis SET concept_ids = ? WHERE id = ?",
           db.js(matched), nid)

    note = get_note(nid)
    note["unmatched"] = result.get("unmatched", [])
    note["restated"] = result.get("restated", "")
    return note


def get_note(nid: str) -> dict:
    row = db.q1("SELECT * FROM emphasis WHERE id = ?", nid)
    if row is None:
        raise KeyError(f"no such note: {nid}")
    d = dict(row)
    d["applied"] = bool(d["applied"])
    links = db.unjs(d["concept_ids"], [])
    d["concepts"] = []
    for link in links:
        cid = link.get("concept_id") if isinstance(link, dict) else link
        c = db.q1("SELECT name, high_yield, emphasis_boost FROM concept WHERE id = ?", cid)
        if c:
            d["concepts"].append({
                "concept_id": cid, "name": c["name"],
                "confidence": link.get("confidence") if isinstance(link, dict) else "medium",
                "why": link.get("why", "") if isinstance(link, dict) else "",
                "base_yield": c["high_yield"],
                "emphasis_boost": c["emphasis_boost"] or 0,
            })
    d["proposed_boost"] = round(
        STRENGTH_BOOST.get(d["strength"], 0.1) * SOURCE_TRUST.get(d["said_by"], 0.5), 3)
    return d


def list_notes(exam_id: str | None = None, course_id: str | None = None) -> list[dict]:
    if exam_id:
        rows = db.q("SELECT id FROM emphasis WHERE exam_id = ? ORDER BY created_at DESC",
                    exam_id)
    elif course_id:
        rows = db.q("SELECT id FROM emphasis WHERE course_id = ? ORDER BY created_at DESC",
                    course_id)
    else:
        rows = db.q("SELECT id FROM emphasis ORDER BY created_at DESC")
    return [get_note(r["id"]) for r in rows]


def apply_note(nid: str, apply: bool = True) -> dict:
    """Confirm (or undo) the priority boost a note proposes.

    The boost lives in `concept.emphasis_boost`, never folded into `high_yield`,
    so what her professor stressed stays separable from what the textbook says -
    and undoing it is exact rather than approximate.
    """
    note = get_note(nid)
    if apply and note["applied"]:
        return note
    if not apply and not note["applied"]:
        return note

    delta = note["proposed_boost"] * (1 if apply else -1)
    for c in note["concepts"]:
        db.run(
            "UPDATE concept SET emphasis_boost = "
            "MAX(0, MIN(0.5, emphasis_boost + ?)) WHERE id = ?",
            delta, c["concept_id"],
        )
    db.run("UPDATE emphasis SET applied = ? WHERE id = ?", 1 if apply else 0, nid)
    return get_note(nid)


def delete_note(nid: str) -> None:
    note = get_note(nid)
    if note["applied"]:
        apply_note(nid, apply=False)   # never leave a phantom boost behind
    db.run("DELETE FROM emphasis WHERE id = ?", nid)


# -------------------------------------------------------- conversation

def _exam_context(exam_id: str | None) -> str:
    """Everything the conversation should already know."""
    parts: list[str] = []

    if exam_id:
        try:
            r = organizer.readiness(exam_id)
        except KeyError:
            return ""
        e = r["exam"]
        parts.append(
            f"EXAM: {e['name']} ({e['kind']}) on {e['date']}"
            + (f" - {e['days_left']} days away" if e["days_left"] is not None else ""))
        if e.get("course"):
            parts.append(f"COURSE: {e['course']}")
        if not r.get("empty"):
            parts.append(
                f"READINESS: {r['readiness']:.0%} weighted coverage across "
                f"{r['concepts_total']} mapped concepts "
                f"({r['concepts_untested']} never practised). "
                f"This is coverage, not a predicted score.")
            parts.append("WEAKEST MAPPED CONCEPTS:")
            for c in r["high_risk"]:
                parts.append(
                    f"  - {c['name']} ({c['topic']}): {c['effective']:.0%} "
                    f"[{c['band']}], {c['attempts']} attempts")
            if r["likely_secure"]:
                parts.append("SOLID: " + ", ".join(
                    c["name"] for c in r["likely_secure"]))

    notes = list_notes(exam_id) if exam_id else list_notes()
    if notes:
        parts.append("\nWHAT SHE WAS TOLD WOULD MATTER:")
        for n in notes[:25]:
            applied = "applied" if n["applied"] else "not yet applied"
            parts.append(
                f"  - [{n['said_by']}, {n['strength']}, {applied}] {n['text']}")
    else:
        parts.append("\nShe has not recorded anything she was told about this exam yet.")

    return "\n".join(parts)


CHAT_SYSTEM = """\
{profile}

# THIS CONVERSATION

You are helping her think about one upcoming exam. Everything below is her real
current state, pulled from the app: her mastery data, and the notes she has
recorded about what she was told would be tested.

Use it. Answer from her actual situation, not in general. When she asks what to
focus on, name specific concepts from her data and say why - the weak ones that
are also emphasised are the highest-value targets.

# HOW TO ANSWER HER

- Short paragraphs. One idea per line. This matters more here than anywhere else
  in the app, because a chat reply has no structure imposed on it.
- Lead with the answer, then the reasoning.
- When you list more than three things, put them in a markdown table instead.
- Never invent what a professor said. You only know what is recorded below. If
  she asks about something not in her notes, say it isn't recorded and ask.
- Be honest when her readiness is low. Do not reassure her out of the facts -
  but do give her the next concrete step rather than a verdict.
- Never predict an exam score. Talk about coverage and what is left to do.

# HER CURRENT STATE

{context}
"""


def start_conversation(exam_id: str | None = None, title: str = "") -> dict:
    cid = f"conv_{uuid.uuid4().hex[:8]}"
    now = time.time()
    if not title and exam_id:
        try:
            title = organizer.get_exam(exam_id)["name"]
        except KeyError:
            title = ""
    db.run(
        "INSERT INTO conversation (id, title, exam_id, created_at, updated_at) "
        "VALUES (?,?,?,?,?)", cid, title or "Exam prep", exam_id, now, now,
    )
    return get_conversation(cid)


def get_conversation(cid: str) -> dict:
    row = db.q1("SELECT * FROM conversation WHERE id = ?", cid)
    if row is None:
        raise KeyError(f"no such conversation: {cid}")
    d = dict(row)
    d["messages"] = [dict(r) for r in db.q(
        "SELECT role, content, created_at FROM message "
        "WHERE conversation_id = ? ORDER BY id", cid)]
    return d


def list_conversations(exam_id: str | None = None) -> list[dict]:
    if exam_id:
        rows = db.q("SELECT * FROM conversation WHERE exam_id = ? "
                    "ORDER BY updated_at DESC", exam_id)
    else:
        rows = db.q("SELECT * FROM conversation ORDER BY updated_at DESC")
    out = []
    for r in rows:
        d = dict(r)
        d["message_count"] = db.q1(
            "SELECT COUNT(*) n FROM message WHERE conversation_id = ?", r["id"])["n"]
        out.append(d)
    return out


def send(cid: str, text: str) -> dict:
    """One turn. Context is rebuilt each time so the reply reflects her state now."""
    conv = get_conversation(cid)
    if not text.strip():
        raise ValueError("Type a message first.")

    now = time.time()
    db.run("INSERT INTO message (conversation_id, role, content, created_at) "
           "VALUES (?,?,?,?)", cid, "user", text.strip(), now)

    history = [{"role": m["role"], "content": m["content"]}
               for m in conv["messages"]] + [{"role": "user", "content": text.strip()}]

    system = CHAT_SYSTEM.format(
        profile=learner_profile.active(), context=_exam_context(conv["exam_id"]) or "(no exam selected)")

    msg = claude.call(system=system, messages=history, max_tokens=8000, effort="medium")
    reply = claude.text_of(msg).strip()
    if not reply:
        reply = "I couldn't produce an answer to that. Try rephrasing it."

    db.run("INSERT INTO message (conversation_id, role, content, created_at) "
           "VALUES (?,?,?,?)", cid, "assistant", reply, time.time())
    db.run("UPDATE conversation SET updated_at = ? WHERE id = ?", time.time(), cid)
    return get_conversation(cid)


def delete_conversation(cid: str) -> None:
    db.run("DELETE FROM message WHERE conversation_id = ?", cid)
    db.run("DELETE FROM conversation WHERE id = ?", cid)
