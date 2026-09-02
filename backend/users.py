"""
Users, and the cognitive profile that shapes every prompt for each of them.

A profile arrives one of three ways:

  report    scores from a real neuropsychological evaluation. Best evidence
            there is, and the reason this path exists at all.
  screener  the in-app tasks. Within-person only - see screener.py for what
            that does and does not mean.
  none      no profile. The app still works; it just applies the general
            principles rather than anything about this person.

The contract handed to Claude is generated from whichever of those is present,
using the same structure in every case. `learner_profile.py` holds the canonical
worked example and the parts that are true for everyone.
"""

from __future__ import annotations

import shutil
import time
import uuid
from pathlib import Path

from . import db, learner_profile

AVATAR_TYPES = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_AVATAR_BYTES = 8 * 1024 * 1024


def _avatar_dir() -> Path:
    d = db.path().parent / "avatars"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ------------------------------------------------------------------ CRUD

def create(name: str, *, profile: dict | None = None,
           profile_kind: str = "none", make_active: bool = True) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("Give yourself a name — it's how the app greets you.")

    uid = f"usr_{uuid.uuid4().hex[:8]}"
    if make_active:
        db.run("UPDATE app_user SET active = 0")
    db.run(
        "INSERT INTO app_user (id, name, active, created_at, profile, profile_kind) "
        "VALUES (?,?,?,?,?,?)",
        uid, name, 1 if make_active else 0, time.time(),
        db.js(profile or {}), profile_kind,
    )
    return get(uid)


def get(uid: str) -> dict:
    row = db.q1("SELECT * FROM app_user WHERE id = ?", uid)
    if row is None:
        raise KeyError(f"no such user: {uid}")
    d = dict(row)
    d["profile"] = db.unjs(d["profile"], {})
    d["active"] = bool(d["active"])
    d["has_photo"] = bool(d["photo"])
    return d


def listing() -> list[dict]:
    return [get(r["id"]) for r in db.q(
        "SELECT id FROM app_user ORDER BY active DESC, created_at")]


def active() -> dict | None:
    row = db.q1("SELECT id FROM app_user WHERE active = 1 LIMIT 1")
    if row:
        return get(row["id"])
    any_user = db.q1("SELECT id FROM app_user ORDER BY created_at LIMIT 1")
    return get(any_user["id"]) if any_user else None


def set_active(uid: str) -> dict:
    db.run("UPDATE app_user SET active = 0")
    db.run("UPDATE app_user SET active = 1 WHERE id = ?", uid)
    learner_profile.invalidate()
    return get(uid)


def update(uid: str, **fields) -> dict:
    sets, vals = [], []
    if "name" in fields and (fields["name"] or "").strip():
        sets.append("name = ?")
        vals.append(fields["name"].strip())
    if "profile" in fields:
        sets.append("profile = ?")
        vals.append(db.js(fields["profile"] or {}))
    if "profile_kind" in fields:
        sets.append("profile_kind = ?")
        vals.append(fields["profile_kind"])
    if sets:
        db.run(f"UPDATE app_user SET {', '.join(sets)} WHERE id = ?", *vals, uid)
    learner_profile.invalidate()
    return get(uid)


def remove(uid: str) -> None:
    """Delete the account. Study history is deliberately left alone.

    Attempts are not scoped per user - this install has one shared bank - so
    deleting a person must never delete answers. Losing a year of history to a
    mis-click on the wrong screen is not a recoverable mistake.
    """
    u = get(uid)
    if u["photo"]:
        (_avatar_dir() / u["photo"]).unlink(missing_ok=True)
    db.run("DELETE FROM app_user WHERE id = ?", uid)
    remaining = db.q1("SELECT id FROM app_user ORDER BY created_at LIMIT 1")
    if remaining:
        set_active(remaining["id"])
    learner_profile.invalidate()


# ---------------------------------------------------------------- photo

def set_photo(uid: str, src: Path, original_name: str) -> dict:
    ext = Path(original_name).suffix.lower()
    if ext not in AVATAR_TYPES:
        raise ValueError(f"{ext or 'That file'} isn't an image. Use PNG or JPG.")
    if src.stat().st_size > MAX_AVATAR_BYTES:
        raise ValueError("That image is over 8 MB — pick a smaller one.")

    u = get(uid)
    if u["photo"]:
        (_avatar_dir() / u["photo"]).unlink(missing_ok=True)

    name = f"{uid}{ext}"
    shutil.copyfile(src, _avatar_dir() / name)
    db.run("UPDATE app_user SET photo = ? WHERE id = ?", name, uid)
    return get(uid)


def photo_path(uid: str) -> Path:
    u = get(uid)
    if not u["photo"]:
        raise KeyError("That user has no photo.")
    return _avatar_dir() / u["photo"]


def clear_photo(uid: str) -> dict:
    u = get(uid)
    if u["photo"]:
        (_avatar_dir() / u["photo"]).unlink(missing_ok=True)
    db.run("UPDATE app_user SET photo = NULL WHERE id = ?", uid)
    return get(uid)


# --------------------------------------------------------------- profile

# The index and subtest names a report can carry. Free-form values, because a
# report may use different subtests and forcing them into our list would lose
# the ones we did not anticipate.
REPORT_FIELDS = {
    "indexes": ["FSIQ", "GAI", "NMI", "VCI", "VSI", "FRI", "WMI", "PSI",
                "AWMI-R", "Other"],
    "subtests": [
        "Similarities", "Vocabulary", "Information", "Comprehension",
        "Block Design", "Visual Puzzles", "Matrix Reasoning", "Figure Weights",
        "Digit Span", "Digits Forward", "Digits Backward", "Digit Sequencing",
        "Running Digits", "Symbol Span", "Letter-Number Sequencing",
        "Coding", "Symbol Search", "Cancellation",
        "Word Reading", "Color Naming", "Inhibition", "Inhibition/Switching",
    ],
    "note": ("Enter only what your report actually contains. Blank is better "
             "than guessed — the app reasons from these numbers, so an invented "
             "one propagates."),
}


def profile_summary(user: dict | None) -> dict:
    """What the UI shows about whichever profile is in force."""
    if not user or user["profile_kind"] == "none" or not user["profile"]:
        return {
            "kind": "none", "name": user["name"] if user else None,
            "headline": "No profile set",
            "detail": ("The app is using general principles. Add a "
                       "neuropsych report or run the screener to have it "
                       "shaped around you."),
            "levers": [],
            "why_table": why_table("none", {}),
        }

    p = user["profile"]
    if user["profile_kind"] == "report":
        return {
            "kind": "report", "name": user["name"],
            "headline": "Built from a neuropsychological report",
            "detail": p.get("source", "Scores entered from a formal evaluation."),
            "levers": learner_profile.levers_from(p),
            "indexes": p.get("indexes", {}),
            "subtests": p.get("subtests", {}),
            "why_table": why_table("report", p),
        }

    settings = p.get("settings", {})
    return {
        "kind": "screener", "name": user["name"],
        "headline": "Built from the in-app screener",
        "detail": screener_detail(settings),
        "levers": learner_profile.levers_from(p),
        "contrasts": p.get("contrasts", []),
        "tasks": p.get("tasks", {}),
        "caveat": ("A screener result, not a clinical assessment. If you have "
                   "a real evaluation, entering it will give the app better "
                   "evidence to work from."),
        "why_table": why_table("screener", p),
    }


def why_table(kind: str, profile: dict) -> str:
    """The one line above the summary table on the Analysis screen.

    It used to be hard-coded to one person's Symbol Span score, which was fine
    while there was one person. Now it has to say something true about whoever
    is signed in - and say nothing at all when nothing is known.
    """
    if kind == "report":
        v = learner_profile._num((profile.get("subtests") or {}).get("Symbol Span"))
        if v is not None:
            band = {"low": "is below average", "mid": "is average",
                    "high": "is a strength"}[learner_profile._band(v, 8, 12)]
            return (f"Your visual working memory {band} (Symbol Span = {v}). "
                    "This table is the version of the material you can actually "
                    "hold onto.")
        return ("Built from your report: one screen, so nothing has to be held "
                "in your head while you read the rest.")
    if kind == "screener":
        route = (profile.get("settings") or {}).get("route")
        if route == "verbal":
            return ("Your screener put the written channel ahead of the visual "
                    "one, so the table is a summary - the explanation below it "
                    "is the main version.")
        if route == "visual":
            return ("Your screener put the visual channel ahead of the spoken "
                    "one. This table is the version of the material you can "
                    "most easily hold onto.")
    return ("The whole topic on one screen, so nothing has to be held in your "
            "head while you read the rest.")


def screener_detail(settings: dict) -> str:
    route = settings.get("route", "balanced")
    chunk = settings.get("chunk_at", 4)
    if route == "visual":
        lead = "Leading with tables and diagrams"
    elif route == "verbal":
        lead = "Leading with written explanation"
    else:
        lead = "Mixing formats"
    return f"{lead}, grouping anything longer than {chunk} items."


# -------------------------------------------------------- first-run seed

DEFAULT_NAME = "You"


def ensure_default() -> dict | None:
    """Create an empty account on a database that has none.

    Deliberately profile-less. Shipping a filled-in profile would mean shipping
    either an invented person or a real one, and the app would then be teaching
    to characteristics nobody measured - which is the single thing it is built
    not to do. The Profile screen prompts for a report or the screener, and
    until one of those happens every prompt uses the generic profile.

    Rename it on the Profile screen; the name is only how the app greets you.
    """
    if db.q1("SELECT COUNT(*) n FROM app_user")["n"]:
        return None
    return create(DEFAULT_NAME, profile=None, profile_kind="none")
