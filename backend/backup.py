"""
Backing up her study history.

The `attempt` table is the one thing in this app that cannot be regenerated.
Questions can be rewritten, concepts re-extracted, mastery recomputed - but a
year of answers is a year of answers. It lives in a single SQLite file on one
laptop, which is exactly one hard-drive failure away from gone.

So:

  * A backup is taken automatically on every start, and the last KEEP are kept.
  * Backups use SQLite's own `.backup()` API rather than copying the file,
    because copying a database that is being written to produces a file that
    looks fine and is corrupt.
  * Restoring backs up the *current* database first. Undoing a restore has to
    be possible, or the restore button is a loaded gun.
  * There is also a plain-JSON export, because a .db is only useful next to
    this app and her history should outlive it.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
import time
from datetime import datetime
from pathlib import Path

from . import db

KEEP = 10                    # rolling automatic backups
MIN_GAP_SECONDS = 6 * 3600   # don't stack backups on a restart loop

# Tables worth carrying into a portable export. Deliberately excludes the
# taxonomy, which is seeded from code and would only bloat the file.
EXPORT_TABLES = [
    "concept", "concept_alias", "concept_edge", "question", "question_concept",
    "attempt", "mastery", "review", "session", "term", "course", "exam",
    "pin", "emphasis", "conversation", "message", "study_plan",
    "drill_result", "note_review", "progression", "source", "source_section",
]


def _db_path() -> Path:
    return db.path()


def _dir() -> Path:
    """Backups sit beside the database, wherever that turns out to be."""
    d = _db_path().parent / "backups"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _stamp() -> str:
    return datetime.now().strftime("%Y%m%d-%H%M%S")


def take(reason: str = "manual") -> dict:
    """Consistent snapshot via SQLite's own backup API."""
    src = _db_path()
    if not src.exists():
        raise FileNotFoundError("There is no database to back up yet.")

    dest = _dir() / f"learnometry-{_stamp()}-{reason}.db"
    source = db.conn()
    target = sqlite3.connect(str(dest))
    try:
        source.backup(target)
    finally:
        target.close()

    prune()
    return describe(dest)


def describe(path: Path) -> dict:
    counts = {}
    try:
        c = sqlite3.connect(str(path))
        for t in ("attempt", "concept", "question"):
            try:
                counts[t] = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
            except sqlite3.Error:
                counts[t] = None
        c.close()
    except sqlite3.Error:
        pass
    stat = path.stat()
    return {
        "name": path.name,
        "bytes": stat.st_size,
        "mb": round(stat.st_size / 1e6, 2),
        "taken_at": stat.st_mtime,
        "when": datetime.fromtimestamp(stat.st_mtime).strftime("%d %b %Y, %H:%M"),
        "counts": counts,
    }


def listing() -> list[dict]:
    """Both naming schemes - backups taken before the rename are still hers."""
    found = list(_dir().glob("learnometry-*.db")) + list(_dir().glob("symbolspan-*.db"))
    return sorted((describe(p) for p in found), key=lambda b: -b["taken_at"])


def prune() -> int:
    files = sorted(
        list(_dir().glob("learnometry-*.db")) + list(_dir().glob("symbolspan-*.db")),
        key=lambda p: -p.stat().st_mtime)
    removed = 0
    for p in files[KEEP:]:
        p.unlink(missing_ok=True)
        removed += 1
    return removed


def auto() -> dict | None:
    """Called at startup. Skips if a recent backup already exists."""
    try:
        existing = listing()
        if existing and time.time() - existing[0]["taken_at"] < MIN_GAP_SECONDS:
            return None
        if not db.q1("SELECT COUNT(*) n FROM attempt")["n"]:
            return None      # nothing worth keeping yet
        return take("auto")
    except Exception:                                  # noqa: BLE001
        # A failed backup must never stop the app starting - she would lose
        # access to the very data this is meant to protect.
        return None


def restore(name: str) -> dict:
    """Swap a backup in, after snapshotting what is there now."""
    src = _dir() / Path(name).name
    if not src.exists():
        raise FileNotFoundError(f"No backup named {name}")

    safety = take("before-restore")
    target = _db_path()

    # Close every thread's handle before overwriting the file underneath them.
    db.close_all()
    shutil.copyfile(src, target)
    for suffix in ("-wal", "-shm"):
        stale = Path(str(target) + suffix)
        stale.unlink(missing_ok=True)
    db.init()

    return {
        "restored": src.name,
        "safety_copy": safety["name"],
        "now": {
            "attempts": db.q1("SELECT COUNT(*) n FROM attempt")["n"],
            "concepts": db.q1("SELECT COUNT(*) n FROM concept")["n"],
        },
    }


def export_json() -> dict:
    """Portable snapshot that does not need this app to be readable."""
    out: dict = {
        "exported_at": time.time(),
        "exported_readable": datetime.now().isoformat(timespec="seconds"),
        "app": "Learnometry",
        "schema_version": (db.q1(
            "SELECT value FROM meta WHERE key = 'schema_version'") or {"value": "?"})["value"],
        "tables": {},
    }
    for table in EXPORT_TABLES:
        try:
            rows = db.q(f"SELECT * FROM {table}")
        except Exception:                              # noqa: BLE001
            continue
        out["tables"][table] = [dict(r) for r in rows]
    out["counts"] = {t: len(rows) for t, rows in out["tables"].items()}
    return out


def export_bytes() -> bytes:
    return json.dumps(export_json(), ensure_ascii=False, indent=1).encode("utf-8")


def db_bytes() -> bytes:
    """The live database, snapshotted first so it is never read mid-write."""
    snap = _dir() / f"_download-{_stamp()}.db"
    target = sqlite3.connect(str(snap))
    try:
        db.conn().backup(target)
    finally:
        target.close()
    try:
        return snap.read_bytes()
    finally:
        snap.unlink(missing_ok=True)
