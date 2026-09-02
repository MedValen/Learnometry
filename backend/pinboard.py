"""
The pinboard: topics, images, mnemonics and notes she wants kept in front of her.

Deliberately simple and entirely hers. Nothing here is generated, scored, or
scheduled - the rest of the app decides what she should study, and this is the
one surface where she decides.

The one profile-driven choice: a pin can carry an image, because her own visual
and spatial hooks are worth more to her than any wording the app could generate
(visual working memory against auditory).
"""

from __future__ import annotations

import time
import uuid

from . import db

KINDS = ["topic", "mnemonic", "image", "question", "note", "link"]


def create(
    *,
    kind: str = "note",
    title: str,
    body: str = "",
    asset_id: str | None = None,
    concept_id: str | None = None,
    exam_id: str | None = None,
    course_id: str | None = None,
    tags: list[str] | None = None,
    starred: bool = False,
) -> dict:
    if not title.strip():
        raise ValueError("A pin needs a title.")
    pid = f"pin_{uuid.uuid4().hex[:8]}"
    now = time.time()
    db.run(
        "INSERT INTO pin (id, kind, title, body, asset_id, concept_id, exam_id, "
        "course_id, tags, starred, created_at, updated_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        pid, kind if kind in KINDS else "note", title.strip(), body.strip(),
        asset_id, concept_id, exam_id, course_id,
        db.js([t.strip() for t in (tags or []) if t.strip()]),
        1 if starred else 0, now, now,
    )
    return get(pid)


def get(pid: str) -> dict:
    row = db.q1("SELECT * FROM pin WHERE id = ?", pid)
    if row is None:
        raise KeyError(f"no such pin: {pid}")
    d = dict(row)
    d["tags"] = db.unjs(d["tags"], [])
    d["starred"] = bool(d["starred"])
    d["archived"] = bool(d["archived"])
    if d.get("concept_id"):
        c = db.q1("SELECT name FROM concept WHERE id = ?", d["concept_id"])
        d["concept_name"] = c["name"] if c else None
    if d.get("exam_id"):
        e = db.q1("SELECT name FROM exam WHERE id = ?", d["exam_id"])
        d["exam_name"] = e["name"] if e else None
    return d


def listing(
    *, kind: str | None = None, exam_id: str | None = None,
    course_id: str | None = None, tag: str | None = None,
    starred_only: bool = False, include_archived: bool = False,
) -> list[dict]:
    where, params = [], []
    if not include_archived:
        where.append("archived = 0")
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if exam_id:
        where.append("exam_id = ?")
        params.append(exam_id)
    if course_id:
        where.append("course_id = ?")
        params.append(course_id)
    if starred_only:
        where.append("starred = 1")

    sql = "SELECT id FROM pin"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY starred DESC, updated_at DESC"

    out = [get(r["id"]) for r in db.q(sql, *params)]
    if tag:
        needle = tag.strip().lower()
        out = [p for p in out if any(t.lower() == needle for t in p["tags"])]
    return out


def update(pid: str, **fields) -> dict:
    allowed = {"kind", "title", "body", "asset_id", "concept_id",
               "exam_id", "course_id"}
    sets, vals = [], []
    for k, v in fields.items():
        if k in allowed:
            sets.append(f"{k} = ?")
            vals.append(v)
        elif k == "tags":
            sets.append("tags = ?")
            vals.append(db.js([t.strip() for t in (v or []) if t.strip()]))
        elif k in ("starred", "archived"):
            sets.append(f"{k} = ?")
            vals.append(1 if v else 0)
    if sets:
        sets.append("updated_at = ?")
        vals.append(time.time())
        db.run(f"UPDATE pin SET {', '.join(sets)} WHERE id = ?", *vals, pid)
    return get(pid)


def remove(pid: str) -> None:
    db.run("DELETE FROM pin WHERE id = ?", pid)


def all_tags() -> list[dict]:
    counts: dict[str, int] = {}
    for r in db.q("SELECT tags FROM pin WHERE archived = 0"):
        for t in db.unjs(r["tags"], []):
            counts[t] = counts.get(t, 0) + 1
    return [{"tag": t, "count": n}
            for t, n in sorted(counts.items(), key=lambda kv: -kv[1])]
