"""
Standing notes: things about her that should not have to be said twice.

The profile already carries what a test measured. This carries what nobody
measured but everybody keeps repeating - that a professor said the boards
version differs from the lecture, that she keeps inverting two drug names,
that Thursday afternoons are clinic and she cannot study then.

Three properties make this useful rather than a scratchpad:

  * Notes are carried into EVERY prompt, appended to the profile contract, so
    anything generated afterwards already knows. That is the whole point: the
    alternative is retyping the same caveat into each new chat.
  * A note can be switched off without being deleted. "The professor said X"
    stops being true after that exam, and losing the record of why the
    material was weighted that way would make the history unreadable later.
  * Notes are kinds, not free text alone. What a professor emphasised should
    influence question weighting; a scheduling constraint should not. Storing
    the kind keeps that distinction available.

They are HER words, not inferences. Nothing here is derived from her answers -
that is what mastery and analytics are for, and blurring the two would let a
statistical guess masquerade as something she told us.
"""

from __future__ import annotations

import time
import uuid

from . import db

KINDS = {
    "emphasis": "What a professor stressed",
    "confusion": "Something she keeps mixing up",
    "preference": "How she wants material presented",
    "schedule": "When she can and cannot study",
    "context": "Anything else worth remembering",
}

# Only these reach the model. A scheduling note has no business shaping how a
# question is written, and letting it would be a quiet way to leak noise into
# every prompt.
PROMPT_KINDS = ("emphasis", "confusion", "preference", "context")


def add(user_id: str, text: str, *, kind: str = "context") -> dict:
    text = (text or "").strip()
    if not text:
        raise ValueError("A note needs some text.")
    if kind not in KINDS:
        kind = "context"
    nid = f"note_{uuid.uuid4().hex[:8]}"
    db.run(
        "INSERT INTO user_note (id, user_id, kind, text, active, created_at) "
        "VALUES (?,?,?,?,1,?)",
        nid, user_id, kind, text, time.time(),
    )
    return get(nid)


def get(nid: str) -> dict:
    row = db.q1("SELECT * FROM user_note WHERE id = ?", nid)
    if row is None:
        raise KeyError(f"no such note: {nid}")
    return _public(row)


def _public(row) -> dict:
    return {
        "id": row["id"], "user_id": row["user_id"], "kind": row["kind"],
        "kind_label": KINDS.get(row["kind"], row["kind"]),
        "text": row["text"], "active": bool(row["active"]),
        "created_at": row["created_at"],
        "in_prompt": bool(row["active"]) and row["kind"] in PROMPT_KINDS,
    }


def listing(user_id: str, *, active_only: bool = False) -> list[dict]:
    sql = "SELECT * FROM user_note WHERE user_id = ?"
    if active_only:
        sql += " AND active = 1"
    sql += " ORDER BY active DESC, created_at DESC"
    return [_public(r) for r in db.q(sql, user_id)]


def update(nid: str, **fields) -> dict:
    sets, vals = [], []
    if "text" in fields:
        t = (fields["text"] or "").strip()
        if not t:
            raise ValueError("A note needs some text.")
        sets.append("text = ?")
        vals.append(t)
    if "kind" in fields and fields["kind"] in KINDS:
        sets.append("kind = ?")
        vals.append(fields["kind"])
    if "active" in fields:
        sets.append("active = ?")
        vals.append(1 if fields["active"] else 0)
    if sets:
        db.run(f"UPDATE user_note SET {', '.join(sets)} WHERE id = ?", *vals, nid)
    return get(nid)


def remove(nid: str) -> None:
    db.run("DELETE FROM user_note WHERE id = ?", nid)


def for_prompt(user_id: str) -> str:
    """The block appended to the profile contract. Empty string if none."""
    rows = [n for n in listing(user_id, active_only=True)
            if n["kind"] in PROMPT_KINDS]
    if not rows:
        return ""

    by_kind: dict[str, list[str]] = {}
    for n in rows:
        by_kind.setdefault(n["kind"], []).append(n["text"])

    lines = [
        "",
        "STANDING NOTES",
        "Things she has told us that no test measured. Treat these as fact "
        "about her situation, not as suggestions.",
    ]
    for kind in PROMPT_KINDS:
        if kind not in by_kind:
            continue
        lines.append(f"\n{KINDS[kind]}:")
        for text in by_kind[kind]:
            lines.append(f"  - {text}")
    return "\n".join(lines)
