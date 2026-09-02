"""
Starting over.

This is a module rather than a DELETE statement in a script for two reasons.

The first is a bug it fixes. `tools/seed_demo.py` had its own reset list that
did not include `progression`, so a "cleared" database still reported Level 8,
a best streak of 23 and five unlocked achievements sitting on top of an empty
mastery map. A wipe that leaves the scoreboard up is worse than no wipe, because
the numbers now describe work that no longer exists anywhere.

The second is that the interesting part of a wipe is what SURVIVES it. Her
account, her photo, the WAIS-5 profile every prompt is built from, and the API
keys are not study data. Losing them turns "start fresh" into "reinstall", so
they are listed explicitly and never touched.

Every table in the database has to appear in exactly one group below. A new
table that nobody classified would otherwise be silently immortal - it would
survive every wipe and nobody would find out until stale rows turned up in a
supposedly clean install.
"""

from __future__ import annotations

from . import db

# Who she is, how the app talks to Claude, and the files she supplied.
# Never cleared by any scope.
#
# `upload` is here rather than in PERSONAL on purpose. A wipe clears what she
# DID, not the source material she brought - making "start fresh" mean
# "re-upload every lecture" would be a punishment, not a reset. The library has
# a per-file delete for the case where she actually wants a file gone. Clearing
# the rows here would also be ineffective: the files stay on disk and
# adopt_orphans() would hand them straight back at the next start.
KEEP = ["app_user", "api_key", "screener_run", "meta", "upload", "user_note"]
# `user_note` is here for the same reason as `upload`: standing notes are things
# she TOLD us, not things she did. A wipe clears study history; making her retype
# "the professor said the boards weight this differently" would defeat the point
# of writing it down once. Individual notes can be muted or deleted in Profile.

# The scoreboard.
GAME = ["progression"]

# Everything that records what she did and what it implied about her.
HISTORY = ["attempt", "review", "mastery", "session",
           "drill_result", "note_review", "insight"]

# The material: concepts, questions, the taxonomy and where it all came from.
# `upload_concept` is CONTENT rather than KEEP even though `upload` is kept: it
# points at concepts, so surviving a content wipe would leave it pointing at
# rows that no longer exist. The file stays, its concept links go, and
# library.reconcile() rebuilds them the moment material is imported again.
CONTENT = ["question_concept", "question", "concept_edge", "concept_alias",
           "upload_concept", "concept", "source_section", "source", "emphasis",
           "topic", "course", "term"]

# Things she made herself, as opposed to things the engine derived.
PERSONAL = ["exam", "study_plan", "message", "conversation",
            "pin", "asset_link", "asset"]

SCOPES: dict[str, list[str]] = {
    "game": GAME,
    "history": GAME + HISTORY,
    "all": GAME + HISTORY + CONTENT + PERSONAL,
}


def tables() -> list[str]:
    return [r["name"] for r in db.q(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name")]


def unclassified() -> list[str]:
    """Tables no group claims. Should always be empty; see the module docstring."""
    known = set(KEEP + GAME + HISTORY + CONTENT + PERSONAL)
    return sorted(set(tables()) - known)


def counts(names: list[str] | None = None) -> dict[str, int]:
    out = {}
    present = set(tables())
    for t in (names if names is not None else tables()):
        if t in present:
            out[t] = db.q1(f'SELECT COUNT(*) c FROM "{t}"')["c"]
    return out


def preview(scope: str = "all") -> dict:
    """What a wipe would remove, without removing it."""
    if scope not in SCOPES:
        raise ValueError(f"Unknown scope: {scope}. One of {sorted(SCOPES)}.")
    clearing = counts(SCOPES[scope])
    return {
        "scope": scope,
        "clearing": clearing,
        "rows": sum(clearing.values()),
        "keeping": counts(KEEP),
        "unclassified": unclassified(),
    }


def wipe(scope: str = "all") -> dict:
    """Clear one scope. Takes a backup first, because this cannot be undone.

    Foreign keys are deferred rather than the tables being carefully ordered:
    the constraints are still checked, but at COMMIT, so a genuine dangling
    reference still fails loudly instead of being hidden by delete order.
    """
    before = preview(scope)

    from . import backup
    snapshot = backup.take(f"before wipe ({scope})")

    con = db.conn()
    try:
        con.execute("PRAGMA defer_foreign_keys = ON")
        with con:
            for t in SCOPES[scope]:
                con.execute(f'DELETE FROM "{t}"')
    finally:
        con.execute("PRAGMA defer_foreign_keys = OFF")

    # The files survive, but their cached concept and question counts described
    # material that has just been deleted. Marking them stale is enough:
    # library.reconcile() recomputes on the next start, and the Library falls
    # back to computing on the fly until then.
    if scope != "game":
        try:
            from . import library
            library.invalidate()
        except Exception:                              # noqa: BLE001
            pass

    return {
        "scope": scope,
        "cleared": before["clearing"],
        "rows_cleared": before["rows"],
        "kept": counts(KEEP),
        "remaining": {t: n for t, n in counts().items() if n},
        "backup": snapshot["name"],
    }
