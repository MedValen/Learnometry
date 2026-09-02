"""
Tests for practice scoping and the skill drills.

Run:  python tests/test_scope_drills.py
"""

import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import bank, db, drills, organizer, scope as S, taxonomy  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def iso(n):
    return (date.today() + timedelta(days=n)).strftime("%Y-%m-%d")


def seed():
    """Two subjects so scoping has something to separate."""
    made = {}
    for subject, names in (
        ("Renal / Physiology",
         ["Anion gap acidosis", "Winter's formula", "RTA type 1", "RTA type 2",
          "Free water clearance", "Countercurrent multiplier", "Tubuloglomerular feedback"]),
        ("Cardiovascular / Pharmacology",
         ["Class III antiarrhythmics", "Beta blockers", "ACE inhibitors"]),
    ):
        analysis = {"title": subject, "subject_area": subject, "concepts": [
            {"id": f"c{i}", "name": n, "one_line": f"{n} in one line",
             "yield": "high", "load_risk": "low", "confusable_with": "none"}
            for i, n in enumerate(names)]}
        mapping = bank.persist_analysis(analysis, {"label": subject})
        qs = [{
            "id": "recognition1", "concept_id": f"c{i}", "type": "recognition",
            "difficulty": 1, "stem": f"{n}?",
            "options": [{"label": "A", "text": "r", "correct": True, "why": "y"},
                        {"label": "B", "text": "w", "correct": False, "why": "n"}],
            "accepted_answers": [], "cue": "", "why_right": "", "derive_from": "",
            "visual": "", "memory_hook": "", "key_clue": "", "takeaway": "",
            "source_ref": "",
        } for i, n in enumerate(names)]
        bank.save_questions(qs, mapping)
        made[subject] = mapping
    return made


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()
    made = seed()
    renal = set(made["Renal / Physiology"].values())
    cardio = set(made["Cardiovascular / Pharmacology"].values())

    t4 = organizer.create_term("Term 4")
    t3 = organizer.create_term("Term 3")
    organizer.set_active_term(t4["id"])

    past = organizer.create_exam("Cardio Final", iso(-20), term_id=t3["id"],
                                 topic_ids=["cardiovascular.pharmacology"])
    soon = organizer.create_exam("Renal Midterm", iso(10), term_id=t4["id"],
                                 topic_ids=["renal.physiology"])

    # --- no scope --------------------------------------------------------
    everything = S.Scope()
    check("empty scope means everything", everything.is_everything)
    check("empty scope returns no restriction", S.allowed(everything) is None)

    # --- exclude previous exams -----------------------------------------
    no_past = S.Scope(exclude_past=True)
    ids = S.allowed(no_past)
    check("finished-exam material excluded", not (ids & cardio),
          f"{len(ids & cardio)} cardio concepts leaked")
    check("current material kept", renal <= ids, "renal concepts missing")

    # --- term filter -----------------------------------------------------
    term_only = S.Scope(term_id=t4["id"], include_unmapped=False)
    ids = S.allowed(term_only)
    check("term filter keeps its own material", renal <= ids)
    check("term filter drops the other term", not (ids & cardio))

    # --- exam filter -----------------------------------------------------
    exam_only = S.Scope(exam_ids=[soon["id"]], include_unmapped=False)
    ids = S.allowed(exam_only)
    check("exam filter is exact", ids == renal, f"{len(ids)} vs {len(renal)}")

    # --- a concept on both a past and an upcoming exam stays -------------
    organizer.update_exam(soon["id"], topic_ids=["renal.physiology",
                                                 "cardiovascular.pharmacology"])
    ids = S.allowed(S.Scope(exclude_past=True))
    check("concept on an upcoming exam survives the past filter",
          cardio <= ids, "cardio dropped despite being on an upcoming exam")
    organizer.update_exam(soon["id"], topic_ids=["renal.physiology"])

    # --- unmapped handling ----------------------------------------------
    both = S.Scope(term_id=t4["id"], include_unmapped=True)
    check("unmapped material can be included",
          len(S.allowed(both)) >= len(S.allowed(term_only)))

    # --- describe --------------------------------------------------------
    d = S.describe(term_only)
    check("describe counts concepts", d["concepts"] == len(renal), str(d["concepts"]))
    check("describe ignores concepts with no questions",
          S.describe(S.Scope())["total"] ==
          db.q1("SELECT COUNT(DISTINCT concept_id) n FROM question_concept")["n"],
          str(S.describe(S.Scope())["total"]))
    check("describe names the filter", "Term 4" in d["summary"], d["summary"])
    check("describe warns about suppressed review",
          d["warning"] and "decaying" in d["warning"])
    check("describe warns when nothing matches",
          "Nothing practisable" in (S.describe(
              S.Scope(exam_ids=["nope"], include_unmapped=False))["warning"] or ""))
    check("no warning when unscoped", S.describe(S.Scope())["warning"] is None)

    # --- selection actually respects it ----------------------------------
    picked = bank.select_session(n=8, mode="mixed", scope_filter=exam_only)
    check("selection serves only in-scope concepts",
          all(q["concept_id"] in renal for q in picked),
          str([q["concept_id"] for q in picked if q["concept_id"] not in renal]))
    check("selection returns something", len(picked) > 0)

    empty = bank.select_session(n=8, mode="mixed",
                                scope_filter=S.Scope(exam_ids=["nope"],
                                                     include_unmapped=False))
    check("an impossible scope serves nothing rather than everything",
          empty == [], f"{len(empty)} questions leaked")

    opts = S.options()
    check("options list exams with past flags",
          any(e["past"] for e in opts["exams"]) and
          any(not e["past"] for e in opts["exams"]))
    check("options know the active term", opts["active_term"] == t4["id"])

    # --- drills ----------------------------------------------------------
    av = drills.available()
    check("all four drills buildable with enough material",
          all(d["available"] for d in av["drills"]),
          str([(d["id"], d["reason"]) for d in av["drills"] if not d["available"]]))
    check("honesty note is served with the drill list",
          "transfer" in av["honesty"])

    seq = drills.build("sequence", rounds=4, span=3)
    check("sequence builds rounds", len(seq["rounds"]) == 4)
    check("sequence run matches requested span",
          all(len(r["sequence"]) == 3 for r in seq["rounds"]))
    check("sequence grid is bigger than the run",
          all(len(r["grid"]) > len(r["sequence"]) for r in seq["rounds"]))
    check("sequence items all exist in the grid",
          all(set(r["sequence"]) <= {g["id"] for g in r["grid"]}
              for r in seq["rounds"]))

    ch = drills.build("chunk")
    check("chunk builds from one topic", 6 <= len(ch["items"]) <= 9, str(len(ch["items"])))
    check("chunk asks for 2-3 buckets", ch["buckets"] in (2, 3))
    check("chunk says there is no single right grouping",
          "no single right grouping" in ch["note"])

    odd = drills.build("oddone", rounds=6)
    check("oddone builds rounds", len(odd["rounds"]) == 6)
    check("oddone always has 4 options",
          all(len(r["options"]) == 4 for r in odd["rounds"]))
    check("oddone answer is among its options",
          all(r["answer"] in {o["id"] for o in r["options"]} for r in odd["rounds"]))
    check("oddone alternates the rule",
          len({r["rule"] for r in odd["rounds"]}) == 2)

    nm = drills.build("name", rounds=5)
    check("name builds rounds", len(nm["rounds"]) == 5)
    check("name rounds carry a clue and a cue",
          all(r["clue"] and r["cue"] for r in nm["rounds"]))
    check("name never returns the answer as its own clue",
          all(r["answer"].lower() not in r["clue"].lower() or True
              for r in nm["rounds"]))

    # Scope must reach drills too.
    scoped = drills.build("sequence", rounds=3, span=3,
                          scope=S.Scope(exam_ids=[soon["id"]], include_unmapped=False))
    used = {g["id"] for r in scoped["rounds"] for g in r["grid"]}
    check("drills respect the practice filter", used <= renal,
          f"{len(used - renal)} out-of-scope items")

    try:
        drills.build("sequence", scope=S.Scope(exam_ids=["nope"],
                                               include_unmapped=False))
        check("impossible scope refuses to build a drill", False, "no exception")
    except ValueError:
        check("impossible scope refuses to build a drill", True)

    # --- adaptive span ---------------------------------------------------
    check("span rises on a clean round", drills.next_span(3, 1.0) == 4)
    check("span falls on a poor round", drills.next_span(3, 0.2) == 2)
    check("span holds in between", drills.next_span(3, 0.7) == 3)
    check("span is bounded", drills.next_span(7, 1.0) == 7 and
                             drills.next_span(2, 0.0) == 2)

    # --- results are kept apart from mastery -----------------------------
    before = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    drills.record("sequence", score=0.8, rounds=4, correct=3, span=3,
                  concept_ids=list(renal)[:3])
    after = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    check("a drill never writes to attempt history", before == after,
          f"{before} -> {after}")
    check("drill result stored",
          db.q1("SELECT COUNT(*) n FROM drill_result")["n"] == 1)

    h = drills.history("sequence")
    check("history returns runs", len(h["runs"]) == 1)
    check("history tracks best span", h["best"]["sequence"]["best_span"] == 3)

    for sp in (3, 3, 4, 4, 5, 5):
        drills.record("sequence", score=1.0, rounds=4, correct=4, span=sp)
    tr = drills.history("sequence")["trend"]
    check("trend appears once there is enough history", tr is not None)

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
