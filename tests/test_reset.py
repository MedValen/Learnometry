"""
Tests for wiping the database.

Run:  python tests/test_reset.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import (  # noqa: E402
    db, gamify, keys, library, notes_memory, reset, taxonomy, users,
)

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()

    print("\n-- classification --")
    check("every table belongs to exactly one group",
          reset.unclassified() == [], str(reset.unclassified()))
    check("the groups do not overlap",
          len(reset.KEEP + reset.GAME + reset.HISTORY + reset.CONTENT
              + reset.PERSONAL)
          == len(set(reset.KEEP + reset.GAME + reset.HISTORY + reset.CONTENT
                     + reset.PERSONAL)))
    check("identity is never in a wipeable group",
          not (set(reset.KEEP) & set(reset.SCOPES["all"])))
    check("an unknown scope is refused",
          _raises(lambda: reset.preview("everything"), ValueError))

    # --- set up something to destroy -----------------------------------
    user = users.ensure_default()
    # A fresh install ships with no profile, so the test gives itself one -
    # the point of these checks is that a wipe does not take it.
    user = users.update(user["id"], profile={
        "indexes": {"WMI": 75}, "subtests": {"Symbol Span": 10},
        "accommodations": [], "source": "Synthetic fixture.", "notes": "",
    }, profile_kind="report")
    k = keys.add("Main", "sk-ant-test-key-000000000000")
    library.add(b"%PDF kept", "Kept Lecture.pdf")
    notes_memory.add(user["id"], "Professor stressed the toxin table.", kind="emphasis")
    gamify.award(1500)
    db.run("UPDATE progression SET best_streak = 23, unlocked = ? WHERE id = 1",
           '["first_answer", "hundred"]')

    before = gamify.state()
    check("there is a scoreboard to clear", before["level"]["level"] > 1)

    print("\n-- the bug this module exists to fix --")
    # The old seed_demo reset list, reproduced exactly.
    old_list = ["attempt", "review", "mastery", "question_concept", "question",
                "concept_edge", "concept_alias", "concept", "session"]
    check("the old reset list did not include progression",
          "progression" not in old_list)
    check("progression is in the game scope now",
          "progression" in reset.SCOPES["game"])
    check("every scope clears the scoreboard",
          all("progression" in tables for tables in reset.SCOPES.values()))

    print("\n-- preview does not delete --")
    p = reset.preview("all")
    check("preview reports rows to clear", p["rows"] > 0)
    check("preview left the scoreboard alone",
          gamify.state()["level"]["level"] == before["level"]["level"])

    print("\n-- wiping --")
    r = reset.wipe("all")
    check("rows were cleared", r["rows_cleared"] == p["rows"])
    check("a backup was taken first", bool(r["backup"]))

    after = gamify.state()
    check("level is back to 1", after["level"]["level"] == 1)
    check("xp is zero", after["level"]["xp"] == 0)
    check("best streak is forgotten", after["streak"]["best"] == 0)
    check("no achievements remain", after["achievements"]["unlocked"] == 0)
    check("no territories remain", gamify.territories() == [])
    check("no attempts remain", db.q1("SELECT COUNT(*) c FROM attempt")["c"] == 0)

    # --- what has to survive -------------------------------------------
    print("\n-- what a wipe must never take --")
    still = users.get(user["id"])
    check("the account still exists",
          still is not None and still["name"] == user["name"])
    check("the profile survived", still["profile_kind"] == "report")
    check("the scores survived",
          still["profile"]["subtests"]["Symbol Span"] == 10)
    check("the api key survived", keys.get(k["id"])["id"] == k["id"])
    # Uploaded lecture files are source material, not study history. "Start
    # fresh" must not mean "re-upload everything".
    check("standing notes survived",
          len(notes_memory.listing(user["id"])) == 1)
    check("uploaded files survived",
          len(library.listing()) == 1
          and library.listing()[0]["name"] == "Kept Lecture.pdf")
    check("a wipe is not a reinstall",
          all(reset.counts(reset.KEEP)[t] > 0 for t in ("app_user", "api_key")))

    # --- narrower scopes ------------------------------------------------
    print("\n-- narrower scopes --")
    gamify.award(900)
    check("game scope clears xp",
          reset.wipe("game")["rows_cleared"] >= 1
          and gamify.state()["level"]["xp"] == 0)
    check("game scope leaves the user alone", users.get(user["id"]) is not None)

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


def _raises(fn, exc_type):
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    sys.exit(main())
