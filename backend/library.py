"""
The uploaded-file library.

Uploads used to live in a module-level dict. The file was written to disk and
the record of it existed only in memory, so every restart emptied the Material
tab while leaving the bytes behind - seven files and twelve megabytes of them,
in this install, that nothing in the app could see or delete.

So the record moves into the database and the disk becomes something we
reconcile against rather than trust:

  * The id IS the content hash, so uploading the same lecture twice returns the
    first row instead of a second copy. Three identical PDFs had accumulated
    under different random prefixes before this existed.
  * `adopt_orphans()` gives a row to any file already on disk without one, so
    the files stranded by the old behaviour reappear rather than needing a
    manual cleanup nobody would know to run.
  * `listing()` reports `present`, because a row whose file was deleted from
    underneath us should say so rather than fail later at generation time.

Text extraction here is deliberately local. Reading a PDF to paste into a chat
should not cost an API call.
"""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

from . import db

KINDS = ("lecture", "slides", "textbook", "notes", "other")


def _dir() -> Path:
    d = db.path().parent / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def content_id(data: bytes) -> str:
    """Same hash ingest.py uses, so the two agree on what 'the same file' means."""
    return hashlib.sha256(data).hexdigest()[:16]


def _page_count(path: Path) -> int | None:
    if path.suffix.lower() != ".pdf":
        return None
    try:
        from pypdf import PdfReader
        return len(PdfReader(str(path)).pages)
    except Exception:                                  # noqa: BLE001
        return None


def _slug(text: str) -> str:
    """Reduce a filename or label to just its letters and digits, lowercased.

    A question records where it came from as a free-text label, and those
    labels do not match filenames exactly: the API path stored the old
    random-prefixed filename, while an imported set stores the analysis title.
    Both should still count against the file they came from, so the comparison
    throws away everything that differs for uninteresting reasons - extension,
    prefix, punctuation, case.
    """
    stem = text.rsplit(".", 1)[0] if "." in text[-6:] else text
    if len(stem) > 9 and stem[8] == "_" and all(
            c in "0123456789abcdef" for c in stem[:8]):
        stem = stem[9:]                                # old upload prefix
    return "".join(c for c in stem.lower() if c.isalnum())


# Grouping every question by its source label is cheap once and wasteful per
# page render. The key is (rows, highest rowid), which changes on any insert or
# retirement - so the memo is exact rather than time-based.
_counts_cache: dict = {"key": None, "value": {}}


def _counts_key():
    r = db.q1("SELECT COUNT(*) n, COALESCE(MAX(rowid), 0) m "
              "FROM question WHERE retired = 0")
    return (r["n"], r["m"]) if r else (0, 0)


def question_counts(*, fresh: bool = False) -> dict[str, int]:
    """How many banked questions cite each source label, by slug."""
    key = _counts_key()
    if not fresh and _counts_cache["key"] == key:
        return _counts_cache["value"]
    out: dict[str, int] = {}
    for r in db.q("SELECT source_refs, COUNT(*) c FROM question "
                  "WHERE retired = 0 GROUP BY source_refs"):
        for ref in db.unjs(r["source_refs"], []) or []:
            label = (ref or {}).get("label") if isinstance(ref, dict) else None
            if label:
                out[_slug(label)] = out.get(_slug(label), 0) + r["c"]
    _counts_cache["key"] = key
    _counts_cache["value"] = out
    return out


def _label_questions(name: str, counts: dict[str, int]) -> int:
    slug = _slug(name)
    # A label may be the file's name, or a title derived from it, so accept a
    # match in either direction rather than requiring the two to be identical.
    n = counts.get(slug, 0)
    if not n:
        n = sum(v for k, v in counts.items() if k and (k in slug or slug in k))
    return n


def _col(r, name, default=None):
    """Read a column that may not exist yet on an old row object."""
    try:
        return r[name]
    except (IndexError, KeyError):
        return default


# What state a file is in, as one word. This is the column you scan down when
# there are two hundred files and you want to know what still needs work.
STATUSES = ("missing", "unprocessed", "concepts_only", "ready")
STATUS_LABEL = {
    "missing": "File missing",
    "unprocessed": "Needs processing",
    "concepts_only": "Concepts only",
    "ready": "Ready",
}


def _status(present: bool, n_concepts: int, n_questions: int) -> str:
    if not present:
        return "missing"
    if n_questions:
        return "ready"
    if n_concepts:
        return "concepts_only"
    return "unprocessed"


def _row(r, counts: dict[str, int] | None = None) -> dict:
    path = _dir() / r["stored_name"]
    present = path.is_file()

    # Cached where it has been reconciled, computed where it has not, so a
    # library that has never been reconciled still reports honest numbers.
    if _col(r, "counted_at", 0):
        n_q = _col(r, "n_questions", 0) or 0
        n_c = _col(r, "n_concepts", 0) or 0
    else:
        counts = question_counts() if counts is None else counts
        n_q = _label_questions(r["original_name"], counts)
        n_c = 0

    return {
        "id": r["id"],
        "name": r["original_name"],
        "kind": r["kind"],
        "pages": r["pages"],
        "bytes": r["bytes"],
        "mb": round((r["bytes"] or 0) / 1_048_576, 2),
        "added_at": r["added_at"],
        "file_id": r["file_id"],
        "present": present,
        "questions": n_q,
        "concepts": n_c,
        "status": _status(present, n_c, n_q),
        "tags": db.unjs(_col(r, "tags", "[]"), []),
        "exam_id": r["exam_id"],
        "exam": _exam_label(r["exam_id"]),
        "term_id": _col(r, "term_id"),
        "course_id": _col(r, "course_id"),
        "ext": (Path(r["original_name"]).suffix.lower().lstrip(".") or "file"),
    }


def _exam_label(eid: str | None) -> dict | None:
    if not eid:
        return None
    row = db.q1("SELECT id, name, date, kind, term_id FROM exam WHERE id = ?", eid)
    if row is None:
        return None                      # exam deleted; the file simply unfiles
    return {"id": row["id"], "name": row["name"], "date": row["date"],
            "kind": row["kind"], "term_id": row["term_id"]}


def add(data: bytes, original_name: str, *, kind: str = "lecture",
        file_id: str | None = None, pages: int | None = None) -> dict:
    """Store a file and record it. Re-uploading the same bytes is a no-op."""
    cid = content_id(data)
    existing = db.q1("SELECT * FROM upload WHERE id = ?", cid)
    if existing:
        path = _dir() / existing["stored_name"]
        if not path.is_file():
            path.write_bytes(data)          # row survived, file did not
        db.run("UPDATE upload SET last_seen = ? WHERE id = ?", time.time(), cid)
        return _row(db.q1("SELECT * FROM upload WHERE id = ?", cid))

    stored = f"{cid}_{Path(original_name).name}"[:180]
    path = _dir() / stored
    path.write_bytes(data)

    db.run(
        "INSERT INTO upload (id, original_name, stored_name, kind, pages, bytes,"
        " file_id, added_at, last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
        cid, original_name, stored, kind if kind in KINDS else "other",
        pages if pages is not None else _page_count(path),
        len(data), file_id, time.time(), time.time(),
    )
    return _row(db.q1("SELECT * FROM upload WHERE id = ?", cid))


def listing() -> list[dict]:
    counts = question_counts()      # one query, not one per file
    return [_row(r, counts) for r in db.q(
        "SELECT * FROM upload ORDER BY added_at DESC")]


def get(uid: str) -> dict:
    r = db.q1("SELECT * FROM upload WHERE id = ?", uid)
    if r is None:
        raise KeyError(f"no such upload: {uid}")
    return _row(r)


def path_of(uid: str) -> Path:
    r = db.q1("SELECT stored_name FROM upload WHERE id = ?", uid)
    if r is None:
        raise KeyError(f"no such upload: {uid}")
    return _dir() / r["stored_name"]


def update(uid: str, **fields) -> dict:
    sets, vals = [], []
    for k in ("kind", "original_name", "file_id", "exam_id",
              "term_id", "course_id", "tags"):
        if k in fields:
            sets.append(f"{k} = ?")
            vals.append(fields[k])
    if sets:
        db.run(f"UPDATE upload SET {', '.join(sets)} WHERE id = ?", *vals, uid)
    return get(uid)


def remove(uid: str, *, delete_file: bool = True) -> dict:
    row = get(uid)
    if delete_file:
        try:
            path_of(uid).unlink(missing_ok=True)
        except OSError:
            pass
    db.run("DELETE FROM upload WHERE id = ?", uid)
    return row


def concept_ids_from(uid: str) -> list[str]:
    """Concepts whose questions cite this file, matched by the same slug rule.

    Used when a file is filed under an exam after its questions were already
    imported - the common order, since material usually arrives before the
    exam date is known.
    """
    want = _slug(get(uid)["name"])
    out: set[str] = set()
    for r in db.q("SELECT id, source_refs FROM question WHERE retired = 0"):
        labels = [ (ref or {}).get("label", "") for ref in
                   (db.unjs(r["source_refs"], []) or []) if isinstance(ref, dict) ]
        if not any(_slug(l) and (_slug(l) in want or want in _slug(l))
                   for l in labels):
            continue
        for qc in db.q("SELECT concept_id FROM question_concept WHERE question_id = ?",
                       r["id"]):
            out.add(qc["concept_id"])
    return sorted(out)


def by_exam(exam_id: str) -> list[dict]:
    return [_row(r) for r in db.q(
        "SELECT * FROM upload WHERE exam_id = ? ORDER BY added_at", exam_id)]


def unfiled() -> list[dict]:
    """Files not yet attached to an exam. The nag line at the top of the Library."""
    return [_row(r) for r in db.q(
        "SELECT * FROM upload WHERE exam_id IS NULL ORDER BY added_at DESC")]


def extract_text(uid: str) -> dict:
    """Plain text from the file, locally. No API call.

    This is what makes the paste-into-a-chat workflow practical: the whole
    point is to author questions somewhere else, and paying for a round trip
    just to read a PDF you already have would defeat that.
    """
    path = path_of(uid)
    if not path.is_file():
        raise FileNotFoundError(f"{get(uid)['name']} is recorded but missing from disk.")

    ext = path.suffix.lower()
    if ext == ".pdf":
        from pypdf import PdfReader
        pages = []
        for i, pg in enumerate(PdfReader(str(path)).pages):
            t = (pg.extract_text() or "").strip()
            if t:
                pages.append(f"===== PAGE {i + 1} =====\n{t}")
        text = "\n\n".join(pages)
    else:
        from .ingest import _extract_docx, _extract_plain, _extract_pptx
        if ext in (".docx",):
            text = _extract_docx(path)
        elif ext in (".pptx",):
            text = _extract_pptx(path)
        else:
            text = _extract_plain(path)

    return {"id": uid, "name": get(uid)["name"], "chars": len(text), "text": text}


def adopt_orphans() -> int:
    """Give a row to every file on disk that has none.

    Runs at startup. Without it the files stranded by the in-memory registry
    stay invisible forever - the user can see them in Explorer and not in the
    app, which is the worst of both.
    """
    known = {r["stored_name"] for r in db.q("SELECT stored_name FROM upload")}
    adopted = 0
    for path in sorted(_dir().glob("*")):
        if not path.is_file() or path.name in known:
            continue
        try:
            data = path.read_bytes()
        except OSError:
            continue
        cid = content_id(data)
        if db.q1("SELECT id FROM upload WHERE id = ?", cid):
            # Same content already recorded under another name: this is a
            # duplicate copy, so drop the file rather than record it twice.
            path.unlink(missing_ok=True)
            continue
        # Strip the old random 8-hex prefix so the name reads as she named it.
        name = path.name
        if len(name) > 9 and name[8] == "_" and all(
                c in "0123456789abcdef" for c in name[:8]):
            name = name[9:]
        db.run(
            "INSERT INTO upload (id, original_name, stored_name, kind, pages,"
            " bytes, file_id, added_at, last_seen) VALUES (?,?,?,?,?,?,?,?,?)",
            cid, name, path.name, "lecture", _page_count(path),
            len(data), None, path.stat().st_mtime, time.time(),
        )
        adopted += 1
    return adopted


def prune_missing() -> list[str]:
    """Names of rows whose file is gone. Reported, never deleted silently."""
    return [r["name"] for r in listing() if not r["present"]]


# ====================== reconciliation and cached counts ====================

def link_concepts(uid: str, concept_ids) -> int:
    """Record that these concepts came out of this file."""
    rows = [(uid, cid) for cid in dict.fromkeys(concept_ids) if cid]
    if not rows:
        return 0
    db.runmany("INSERT OR IGNORE INTO upload_concept (upload_id, concept_id) "
               "VALUES (?,?)", rows)
    return len(rows)


def concepts_of(uid: str) -> list[str]:
    """Concepts linked to this file. Falls back to the label rule if the link
    table has nothing yet, so a library imported before this existed is not
    silently reported as empty."""
    rows = db.q("SELECT concept_id FROM upload_concept WHERE upload_id = ?", uid)
    if rows:
        return [r["concept_id"] for r in rows]
    return concept_ids_from(uid)


def recount(uid: str) -> dict:
    """Refresh one file's cached numbers, linking concepts if not yet linked."""
    r = db.q1("SELECT * FROM upload WHERE id = ?", uid)
    if r is None:
        raise KeyError(f"no such upload: {uid}")

    linked = [x["concept_id"] for x in
              db.q("SELECT concept_id FROM upload_concept WHERE upload_id = ?", uid)]
    if not linked:
        linked = concept_ids_from(uid)     # the historic rule, run once
        link_concepts(uid, linked)

    n_q = _label_questions(r["original_name"], question_counts())
    db.run("UPDATE upload SET n_concepts = ?, n_questions = ?, counted_at = ? "
           "WHERE id = ?", len(linked), n_q, time.time(), uid)
    return get(uid)


def reconcile(*, force: bool = False) -> int:
    """Materialise counts and concept links for files that have none.

    Runs at startup. Before this, "which concepts came from this file" was a
    scan of every question in the bank, per file, on every render of the
    Library - which is fine at four files and unusable at four hundred.
    """
    where = "" if force else " WHERE counted_at = 0"
    ids = [r["id"] for r in db.q(f"SELECT id FROM upload{where}")]
    for uid in ids:
        try:
            recount(uid)
        except Exception:                              # noqa: BLE001
            continue          # one bad row must not stop the rest coming up
    return len(ids)


def invalidate(uid: str | None = None) -> None:
    """Mark counts stale. Cheap: the next reconcile picks them up."""
    if uid:
        db.run("UPDATE upload SET counted_at = 0 WHERE id = ?", uid)
    else:
        db.run("UPDATE upload SET counted_at = 0")


# ================================ querying =================================

SORTS = {
    "added": "added_at DESC",
    "added_asc": "added_at ASC",
    "name": "original_name COLLATE NOCASE ASC",
    "name_desc": "original_name COLLATE NOCASE DESC",
    "questions": "n_questions DESC",
    "concepts": "n_concepts DESC",
    "size": "bytes DESC",
}


def query(*, q: str = "", term_id: str = "", course_id: str = "",
          exam_id: str = "", kind: str = "", status: str = "",
          tag: str = "", sort: str = "added",
          limit: int = 50, offset: int = 0) -> dict:
    """A page of the library, plus the totals the filter bar needs.

    Filtering happens in SQL for everything the database knows. `status` is
    derived from the cached counts and the file's presence on disk, so it is
    applied in Python after the rows come back - which is correct, because
    presence is a fact about the filesystem, not about the row.
    """
    where, params = ["1=1"], []
    if q:
        where.append("original_name LIKE ? COLLATE NOCASE")
        params.append(f"%{q}%")
    if term_id:
        # A file inherits its term from the exam it is filed under, so a term
        # filter has to accept either route.
        where.append("(term_id = ? OR exam_id IN "
                     "(SELECT id FROM exam WHERE term_id = ?))")
        params += [term_id, term_id]
    if course_id:
        where.append("(course_id = ? OR exam_id IN "
                     "(SELECT id FROM exam WHERE course_id = ?))")
        params += [course_id, course_id]
    if exam_id == "none":
        where.append("exam_id IS NULL")
    elif exam_id:
        where.append("exam_id = ?")
        params.append(exam_id)
    if kind:
        where.append("kind = ?")
        params.append(kind)
    if tag:
        where.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    sql_where = " AND ".join(where)
    order = SORTS.get(sort, SORTS["added"])

    rows = db.q(f"SELECT * FROM upload WHERE {sql_where} ORDER BY {order}", *params)
    counts = question_counts()
    files = [_row(r, counts) for r in rows]

    if status:
        wanted = set(status.split(","))
        files = [f for f in files if f["status"] in wanted]

    total = len(files)
    page = files[offset:offset + limit] if limit else files
    return {
        "files": page,
        "total": total,
        "offset": offset,
        "limit": limit,
        "facets": facets(),
    }


def facets() -> dict:
    """Counts for the filter bar. One pass over the library, not one per filter."""
    all_rows = [_row(r, question_counts()) for r in
                db.q("SELECT * FROM upload")]
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    by_exam: dict[str, int] = {}
    tags: dict[str, int] = {}
    for f in all_rows:
        by_status[f["status"]] = by_status.get(f["status"], 0) + 1
        by_kind[f["kind"]] = by_kind.get(f["kind"], 0) + 1
        key = f["exam_id"] or "none"
        by_exam[key] = by_exam.get(key, 0) + 1
        for t in f["tags"]:
            tags[t] = tags.get(t, 0) + 1
    return {"total": len(all_rows), "status": by_status, "kind": by_kind,
            "exam": by_exam, "tags": tags}


# ============================== the detail view ============================

def detail(uid: str) -> dict:
    """Everything the app knows about one file, joined to what it taught.

    The point of this view is the last section: which concepts from this
    lecture are weak. A file that is only a file tells you nothing; a file
    that knows it produced eleven shaky concepts is a study plan.
    """
    from . import bank

    entry = get(uid)
    cids = concepts_of(uid)

    concepts = []
    for cid in cids:
        row = db.q1("SELECT c.id, c.name, c.high_yield, c.hy_tier, t.path topic "
                    "FROM concept c LEFT JOIN topic t ON t.id = c.topic_id "
                    "WHERE c.id = ? AND c.retired = 0", cid)
        if row is None:
            continue
        m = bank.current(cid)
        concepts.append({
            "id": row["id"], "name": row["name"], "topic": row["topic"],
            "high_yield": row["high_yield"], "hy_tier": row["hy_tier"],
            "effective": round(m.effective, 4), "band": m.band,
            "attempts": m.attempts,
        })

    seen = [c for c in concepts if c["attempts"] > 0]
    weak = sorted(seen, key=lambda c: c["effective"])[:8]
    entry.update({
        "concept_list": sorted(concepts, key=lambda c: -c["high_yield"]),
        "weak": weak,
        # Only counts what has actually been answered. An average over
        # untouched concepts would be an average over a prior, not over
        # evidence - which is the thing this app refuses to do elsewhere.
        "mastery": (round(sum(c["effective"] for c in seen) / len(seen), 4)
                    if seen else None),
        "assessed": len(seen),
        "status_label": STATUS_LABEL.get(entry["status"], entry["status"]),
    })
    return entry


# ================================= searching ===============================

def search(text: str, limit: int = 8) -> dict:
    """One query across files, concepts and questions.

    Deliberately three separate lists rather than one ranked list: "where is
    that lecture" and "what do I know about bethanechol" are different
    questions, and merging them makes both answers harder to see.
    """
    t = (text or "").strip()
    if len(t) < 2:
        return {"query": t, "files": [], "concepts": [], "questions": 0}

    like = f"%{t}%"
    counts = question_counts()
    files = [_row(r, counts) for r in db.q(
        "SELECT * FROM upload WHERE original_name LIKE ? COLLATE NOCASE "
        "ORDER BY added_at DESC LIMIT ?", like, limit)]

    concepts = [{"id": r["id"], "name": r["name"], "topic": r["path"]}
                for r in db.q(
                    "SELECT c.id, c.name, t.path FROM concept c "
                    "LEFT JOIN topic t ON t.id = c.topic_id "
                    "WHERE c.retired = 0 AND c.name LIKE ? COLLATE NOCASE "
                    "ORDER BY c.high_yield DESC LIMIT ?", like, limit)]

    nq = db.q1("SELECT COUNT(*) n FROM question WHERE retired = 0 "
               "AND stem LIKE ? COLLATE NOCASE", like)
    return {"query": t, "files": files, "concepts": concepts,
            "questions": nq["n"] if nq else 0}


# ========================== operating on many at once ======================

BULK_ACTIONS = ("exam", "term", "course", "kind", "tag", "untag", "delete")


def bulk(ids: list[str], action: str, value=None) -> dict:
    """Apply one change to many files.

    Managing a hundred lectures one row at a time is not a workflow. Failures
    are collected rather than raised, so one deleted file cannot abort the
    other ninety-nine.
    """
    if action not in BULK_ACTIONS:
        raise ValueError(f"unknown bulk action: {action}")
    done, failed = [], []
    for uid in ids:
        try:
            if action == "delete":
                remove(uid)
            elif action == "exam":
                update(uid, exam_id=value or None)
            elif action == "term":
                update(uid, term_id=value or None)
            elif action == "course":
                update(uid, course_id=value or None)
            elif action == "kind":
                update(uid, kind=value if value in KINDS else "other")
            elif action in ("tag", "untag"):
                have = get(uid)["tags"]
                if action == "tag" and value and value not in have:
                    have = sorted(have + [value])
                elif action == "untag":
                    have = [t for t in have if t != value]
                update(uid, tags=db.js(have))
            done.append(uid)
        except Exception as exc:                       # noqa: BLE001
            failed.append({"id": uid, "error": str(exc)})
    return {"action": action, "value": value, "done": len(done),
            "failed": failed}
