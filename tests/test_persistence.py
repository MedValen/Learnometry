"""
End-to-end test of the Phase 1 persistence layer.

Uses a throwaway database, so it never touches real study history.
Run:  python tests/test_persistence.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, taxonomy, bank  # noqa: E402

ANALYSIS = {
    "title": "Antiarrhythmics",
    "subject_area": "Cardiovascular / Pharmacology",
    "concepts": [
        {"id": "c1", "name": "Class III antiarrhythmics", "one_line": "K+ channel blockers",
         "yield": "high", "load_risk": "five drugs", "confusable_with": "Class IA antiarrhythmics"},
        {"id": "c2", "name": "Torsades de pointes", "one_line": "Polymorphic VT with long QT",
         "yield": "high", "load_risk": "low", "confusable_with": "none"},
    ],
}

QUESTIONS = [
    {"id": "q1", "concept_id": "c1", "type": "recognition", "difficulty": 1,
     "stem": "Which class blocks K+ channels?",
     "options": [{"label": "A", "text": "III", "correct": True, "why": "yes"},
                 {"label": "B", "text": "IB", "correct": False, "why": "no"}],
     "cue": "phase 3", "why_right": "K+ efflux", "derive_from": "AP phases",
     "visual": "| c | i |", "memory_hook": "hill", "key_clue": "K+",
     "takeaway": "III = K+", "source_ref": "slide 4", "accepted_answers": []},
    {"id": "q2", "concept_id": "c1", "type": "application", "difficulty": 3,
     "stem": "Patient on sotalol develops QT prolongation. Mechanism?",
     "options": [{"label": "A", "text": "K+ block", "correct": True, "why": "yes"},
                 {"label": "B", "text": "Na+ block", "correct": False, "why": "no"}],
     "cue": "phase 3", "why_right": "slowed repolarization", "derive_from": "AP",
     "visual": "| c | i |", "memory_hook": "hill", "key_clue": "QT",
     "takeaway": "K+ block lengthens QT", "source_ref": "slide 5", "accepted_answers": []},
    {"id": "q3", "concept_id": "c2", "type": "cued_recall", "difficulty": 2,
     "stem": "Name the arrhythmia caused by long QT.",
     "options": [], "answer_text": "torsades de pointes",
     "accepted_answers": ["torsades"], "cue": "starts with T",
     "why_right": "polymorphic VT", "derive_from": "long QT -> EAD",
     "visual": "a -> b", "memory_hook": "twist", "key_clue": "long QT",
     "takeaway": "long QT -> torsades", "source_ref": "slide 6"},
    {"id": "q4", "concept_id": "cX", "type": "recognition", "difficulty": 1,
     "stem": "orphan question with an unmappable concept",
     "options": [], "accepted_answers": [], "cue": "", "why_right": "",
     "derive_from": "", "visual": "", "memory_hook": "", "key_clue": "",
     "takeaway": "", "source_ref": ""},
]

checks = []


def check(label, cond, detail=""):
    checks.append((label, bool(cond), detail))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" + (f" — {detail}" if detail and not cond else ""))


def main():
    tmp = Path(tempfile.mkdtemp()) / "test.db"
    db.configure(tmp)
    n_topics = taxonomy.seed()
    check("taxonomy seeds", n_topics > 60, f"got {n_topics}")
    check("seed is idempotent", taxonomy.seed() and
          db.q1("SELECT COUNT(*) n FROM topic")["n"] == n_topics)

    # --- concept identity -------------------------------------------------
    mapping = bank.persist_analysis(ANALYSIS, {"label": "Cardio lecture 4"})
    check("both concepts persisted", len(mapping) == 2, str(mapping))
    cid1, cid2 = mapping["c1"], mapping["c2"]

    check("topic resolved to real node", not cid1.startswith("unsorted"), cid1)

    again = bank.persist_analysis(ANALYSIS, {"label": "Cardio lecture 4"})
    check("re-analysis reuses concept ids", again["c1"] == cid1 and again["c2"] == cid2)
    check("no duplicate concepts",
          db.q1("SELECT COUNT(*) n FROM concept WHERE name = 'Torsades de pointes'")["n"] == 1)

    # Alias resolution: a different phrasing must land on the same concept.
    alias_id = taxonomy.resolve_concept("class III antiarrhythmics",
                                        topic_id="cardiovascular.pharmacology")
    check("alias matching reuses identity", alias_id == cid1, f"{alias_id} != {cid1}")

    edges = db.q("SELECT dst FROM concept_edge WHERE src = ?", cid1)
    check("confusable_with became a graph edge", len(edges) >= 1)

    # --- question bank ----------------------------------------------------
    saved_rows = bank.save_questions(QUESTIONS, mapping, source_ref={"label": "Cardio lecture 4"})
    saved = [r["question_id"] for r in saved_rows]
    check("3 of 4 questions saved", len(saved) == 3, f"got {len(saved)}")
    check("local ids returned for mapping",
          {r["local_id"] for r in saved_rows} == {"q1", "q2", "q3"},
          str([r["local_id"] for r in saved_rows]))
    check("orphan question dropped, not stored",
          db.q1("SELECT COUNT(*) n FROM question WHERE stem LIKE 'orphan%'")["n"] == 0)

    loaded = bank.load_questions(saved)
    check("round-trips through the bank", len(loaded) == 3)
    check("options survive JSON round-trip",
          loaded[0]["options"] and loaded[0]["options"][0]["correct"] is True)
    check("difficulty preserved", {q["difficulty"] for q in loaded} == {1, 3, 2})
    check("format preserved as `type`", loaded[0]["type"] == "recognition")

    # --- attempts + mastery ----------------------------------------------
    start = bank.current(cid1)
    check("untouched concept starts at prior", start.attempts == 0 and start.band == "red")

    r = bank.record_attempt(question_id=saved[0], correct=True, confidence="knew",
                            rt_ms=4200, session_id="s1")
    check("attempt returns before/after", r["concepts"][0]["after"] >= r["concepts"][0]["before"])
    check("delta reported", "delta" in r["concepts"][0])

    for _ in range(9):
        bank.record_attempt(question_id=saved[1], correct=True, confidence="knew",
                            session_id="s1")
    m = bank.current(cid1)
    check("mastery rises with sustained correct answers", m.effective > 0.6,
          f"{m.effective:.3f} band={m.band}")
    check("attempt history retained", m.attempts == 10, f"got {m.attempts}")
    check("streak tracked", m.streak == 10)

    # Confidently wrong should bite harder than a hedged wrong answer.
    before = bank.current(cid1).effective
    bank.record_attempt(question_id=saved[1], correct=False, confidence="knew",
                        session_id="s1")
    after_confident = bank.current(cid1).effective
    check("confidently wrong lowers mastery", after_confident < before,
          f"{before:.3f} -> {after_confident:.3f}")

    # --- cue capping ------------------------------------------------------
    bank.record_attempt(question_id=saved[2], correct=True, confidence="knew",
                        used_cue=True, session_id="s1")
    row = db.q1("SELECT confidence, used_cue FROM attempt WHERE concept_id = ? "
                "ORDER BY id DESC LIMIT 1", cid2)
    check("cue use downgrades a 'knew' claim to 'unsure'",
          row["confidence"] == "unsure" and row["used_cue"] == 1, dict(row))

    # --- response time is stored but inert -------------------------------
    rts = db.q("SELECT rt_ms FROM attempt WHERE rt_ms IS NOT NULL")
    check("response time is stored", len(rts) >= 1)

    # --- rebuild ----------------------------------------------------------
    snapshot = bank.current(cid1).mastery
    bank.rebuild_all()
    check("rebuild from history is stable",
          abs(bank.current(cid1).mastery - snapshot) < 1e-9)

    # --- append-only ------------------------------------------------------
    total = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    check("every attempt kept", total == 12, f"got {total}")

    failed = [c for c in checks if not c[1]]
    print(f"\n{len(checks) - len(failed)} passed, {len(failed)} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
