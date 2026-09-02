"""
The vault: photos of whiteboards, exam questions, handwritten notes, handouts.

Two jobs, and the second is optional on purpose.

STORAGE is the promise: whatever she photographs is kept, captioned, tagged to a
term / course / exam / concept, and findable later. That works with no API key
and no network.

ANALYSIS is the bonus: a whiteboard brain dump is a retrieval attempt she has
already performed, so Claude can read it, map what she wrote onto the concept
taxonomy, and - the useful half - name what is *missing* relative to what the
topic actually contains. She asks for it per image; it never runs on upload.
"""

from __future__ import annotations

import mimetypes
import shutil
import time
import uuid
from pathlib import Path

from . import claude, db, taxonomy
from . import learner_profile

IMAGE_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic"}
DOC_TYPES = {".pdf", ".txt", ".md", ".docx", ".pptx"}
ALLOWED = IMAGE_TYPES | DOC_TYPES

MAX_BYTES = 40 * 1024 * 1024

KINDS = ["photo", "whiteboard", "question", "handout", "note"]

LINK_KINDS = {"term", "course", "exam", "concept", "topic", "pin"}


class Rejected(Exception):
    pass


def _dir() -> Path:
    # Ask db.path() rather than importing app.DATA. app.DATA is resolved once at
    # import time, so it ignores db.configure() entirely - which meant the test
    # suite, pointed at a temp database, still wrote its fixture images into the
    # real data directory. Twenty-one stray 208-byte PNGs accumulated there
    # before anyone noticed. The images belong beside the rows that describe
    # them; db.path() is the one fact that says where that is.
    d = db.path().parent / "vault"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ store

def add(
    src_path: Path,
    *,
    original_name: str,
    kind: str = "photo",
    caption: str = "",
    links: list[dict] | None = None,
) -> dict:
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED:
        raise Rejected(
            f"{original_name}: {ext or 'no extension'} isn't supported here. "
            f"Use an image, PDF, or document."
        )
    size = src_path.stat().st_size
    if size > MAX_BYTES:
        raise Rejected(f"{original_name} is {size / 1e6:.0f} MB; the limit is 40 MB.")

    aid = f"a_{uuid.uuid4().hex[:10]}"
    dest = _dir() / f"{aid}{ext}"
    shutil.copyfile(src_path, dest)

    db.run(
        "INSERT INTO asset (id, kind, filename, stored_path, mime, bytes, caption, "
        "added_at) VALUES (?,?,?,?,?,?,?,?)",
        aid, kind if kind in KINDS else "photo", original_name, str(dest),
        mimetypes.guess_type(original_name)[0] or "application/octet-stream",
        size, caption.strip(), time.time(),
    )
    for link in links or []:
        attach(aid, link.get("kind", ""), link.get("target_id", ""))
    return get(aid)


def attach(asset_id: str, kind: str, target_id: str) -> None:
    if kind not in LINK_KINDS or not target_id:
        return
    db.run(
        "INSERT OR IGNORE INTO asset_link (asset_id, kind, target_id) VALUES (?,?,?)",
        asset_id, kind, target_id,
    )


def detach(asset_id: str, kind: str, target_id: str) -> None:
    db.run(
        "DELETE FROM asset_link WHERE asset_id = ? AND kind = ? AND target_id = ?",
        asset_id, kind, target_id,
    )


def get(aid: str) -> dict:
    row = db.q1("SELECT * FROM asset WHERE id = ?", aid)
    if row is None:
        raise KeyError(f"no such file: {aid}")
    d = dict(row)
    d["analysis"] = db.unjs(d["analysis"], None) if d["analysis"] else None
    d["links"] = [dict(r) for r in db.q(
        "SELECT kind, target_id FROM asset_link WHERE asset_id = ?", aid)]
    d["is_image"] = Path(d["filename"]).suffix.lower() in IMAGE_TYPES
    d.pop("stored_path", None)     # never leaks a filesystem path to the browser
    return d


def listing(
    *, kind: str | None = None, link_kind: str | None = None,
    target_id: str | None = None, limit: int = 200,
) -> list[dict]:
    sql = "SELECT DISTINCT a.id FROM asset a"
    params: list = []
    where = []
    if link_kind and target_id:
        sql += " JOIN asset_link l ON l.asset_id = a.id"
        where.append("l.kind = ? AND l.target_id = ?")
        params += [link_kind, target_id]
    if kind:
        where.append("a.kind = ?")
        params.append(kind)
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += " ORDER BY a.added_at DESC LIMIT ?"
    params.append(limit)
    return [get(r["id"]) for r in db.q(sql, *params)]


def file_path(aid: str) -> Path:
    row = db.q1("SELECT stored_path FROM asset WHERE id = ?", aid)
    if row is None:
        raise KeyError(f"no such file: {aid}")
    return Path(row["stored_path"])


def update(aid: str, *, caption: str | None = None, kind: str | None = None) -> dict:
    if caption is not None:
        db.run("UPDATE asset SET caption = ? WHERE id = ?", caption.strip(), aid)
    if kind in KINDS:
        db.run("UPDATE asset SET kind = ? WHERE id = ?", kind, aid)
    return get(aid)


def remove(aid: str) -> None:
    try:
        file_path(aid).unlink(missing_ok=True)
    except KeyError:
        pass
    db.run("DELETE FROM asset_link WHERE asset_id = ?", aid)
    db.run("UPDATE pin SET asset_id = NULL WHERE asset_id = ?", aid)
    db.run("DELETE FROM asset WHERE id = ?", aid)


# --------------------------------------------------------------- analysis

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "summary": {"type": "string",
                    "description": "Two or three short lines on what this image shows."},
        "kind_guess": {"type": "string",
                       "enum": ["whiteboard", "question", "handout", "note", "other"]},
        "recalled": {
            "type": "array",
            "description": "Concepts she DID write down / get right. Names only.",
            "items": {"type": "string"},
        },
        "missing": {
            "type": "array",
            "description": "Concepts a complete answer on this topic would include that are absent here. The useful half.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "why_it_matters": {"type": "string"},
                },
                "required": ["name", "why_it_matters"],
                "additionalProperties": False,
            },
        },
        "errors": {
            "type": "array",
            "description": "Anything written that is factually wrong. Empty if none - do not invent errors.",
            "items": {
                "type": "object",
                "properties": {
                    "wrote": {"type": "string"},
                    "correction": {"type": "string"},
                },
                "required": ["wrote", "correction"],
                "additionalProperties": False,
            },
        },
        "topic_guess": {"type": "string",
                        "description": "Best-guess topic path, e.g. 'Renal / Physiology'."},
        "legibility": {
            "type": "string",
            "description": "Say so plainly if parts are unreadable. Never guess at illegible handwriting.",
        },
    },
    "required": ["summary", "kind_guess", "recalled", "missing", "errors",
                 "topic_guess", "legibility"],
    "additionalProperties": False,
}

ANALYSIS_PROMPT = """\
Read this image from her study vault and turn it into something useful.

If it is a WHITEBOARD BRAIN DUMP, treat it as a retrieval attempt she has
already performed. That makes it evidence, and the valuable half of your answer
is not what she remembered - it is what a complete answer on this topic would
contain that is **absent** here. Those gaps are what she should study next.

If it is an EXAM QUESTION or a handout, extract what is being tested and the
concept behind it.

Rules:
- Do not invent errors. If everything written is correct, return an empty list.
- If handwriting is unreadable, say so in `legibility` rather than guessing.
  A confident misreading of her notes is worse than an admission.
- Keep every line short. One idea per line.
- `missing` is ordered most important first.
"""


def analyse(aid: str) -> dict:
    """Ask Claude to read one image. Explicitly requested, never automatic."""
    row = db.q1("SELECT * FROM asset WHERE id = ?", aid)
    if row is None:
        raise KeyError(f"no such file: {aid}")

    path = Path(row["stored_path"])
    if not path.exists():
        raise KeyError(f"the stored file for {aid} is missing from disk")

    file_id = row["file_id"]
    if not file_id:
        mime = row["mime"] or "application/octet-stream"
        with path.open("rb") as fh:
            uploaded = claude.client().beta.files.upload(
                file=(row["filename"], fh, mime))
        file_id = uploaded.id
        db.run("UPDATE asset SET file_id = ? WHERE id = ?", file_id, aid)

    is_image = path.suffix.lower() in IMAGE_TYPES
    block = ({"type": "image", "source": {"type": "file", "file_id": file_id}}
             if is_image else
             {"type": "document", "source": {"type": "file", "file_id": file_id},
              "title": row["filename"]})

    caption = row["caption"]
    prompt = ANALYSIS_PROMPT
    if caption:
        prompt += f"\n\nHer own caption on this image: {caption}"

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": [block, {"type": "text", "text": prompt}]}],
        schema=ANALYSIS_SCHEMA,
        max_tokens=8000,
        effort="high",
    )
    result = claude.json_of(msg)
    result["topic_id"] = taxonomy.resolve_topic(result.get("topic_guess", ""))

    db.run(
        "UPDATE asset SET analysis = ?, analysed_at = ? WHERE id = ?",
        db.js(result), time.time(), aid,
    )
    return get(aid)
