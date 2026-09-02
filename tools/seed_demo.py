"""
Load fake study history so you can see the engine work without an API key.

This exists to make the app reviewable. It writes plausible concepts, questions,
and ~120 answered attempts across five organ systems, with deliberately uneven
skill so the mastery map has something to show: strong cardiology, weak renal
and autonomic pharm.

    python tools\\seed_demo.py           # add demo data
    python tools\\seed_demo.py --reset   # wipe the database first

The questions are placeholders, not real teaching material - the point is the
mastery math and selection, not the medicine. Clear it before real study:

    python tools\\seed_demo.py --reset --no-seed
"""

import argparse
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend import bank, db, taxonomy  # noqa: E402

DB_PATH = ROOT / "data" / "symbolspan.db"

# name, yield tier, what it gets confused with
TOPICS = {
    "Cardiovascular / Pharmacology": [
        ("Class III antiarrhythmics", "high", "Class IA antiarrhythmics"),
        ("Beta blockers", "high", "Calcium channel blockers"),
    ],
    # Deliberately deep: Chunk It needs six concepts under one topic, and a
    # single shallow topic everywhere would make that drill unbuildable.
    "Renal / Physiology": [
        ("Anion gap metabolic acidosis", "high", "Non-anion gap metabolic acidosis"),
        ("Winter's formula", "high", "none"),
        ("Renal tubular acidosis type 1", "medium", "Renal tubular acidosis type 2"),
        ("Renal tubular acidosis type 2", "medium", "Renal tubular acidosis type 1"),
        ("Free water clearance", "medium", "none"),
        ("Countercurrent multiplier", "medium", "none"),
        ("Tubuloglomerular feedback", "high", "none"),
    ],
    "Neurology / Anatomy": [
        ("CN III palsy", "high", "CN VI palsy"),
        ("Brachial plexus lesions", "medium", "none"),
    ],
    "Pharmacology / Autonomic Drugs": [
        ("Muscarinic antagonists", "high", "Nicotinic antagonists"),
    ],
    "Biochemistry / Metabolism": [
        ("Glycogen storage diseases", "low", "none"),
    ],
}

# Four variants per concept, so variant rotation and difficulty escalation have
# somewhere to go.
CELLS = [("recognition", 1), ("cued_recall", 2), ("discrimination", 3), ("application", 3)]

# Uneven on purpose: the map is boring if everything is the same colour.
SKILL = {
    "cardiovascular": 0.90,
    "biochemistry": 0.70,
    "neurology": 0.55,
    "pharmacology": 0.30,
    "renal": 0.25,
}

def reset():
    """Clear demo data.

    This used to keep its own table list, which omitted `progression` - so a
    reset database still showed Level 8 and five achievements above an empty
    mastery map. backend.reset owns the list now, and it fails loudly if a new
    table goes unclassified.
    """
    from backend import reset as reset_mod

    r = reset_mod.wipe("all")
    print(f"database cleared - {r['rows_cleared']} rows")
    print(f"backup saved as {r['backup']}")


def seed():
    qmap = {}
    for subject, concepts in TOPICS.items():
        analysis = {
            "title": subject,
            "subject_area": subject,
            "concepts": [
                {"id": f"c{i}", "name": name, "one_line": f"{name} - core idea",
                 "yield": tier, "load_risk": "demo data", "confusable_with": conf}
                for i, (name, tier, conf) in enumerate(concepts)
            ],
        }
        mapping = bank.persist_analysis(analysis, {"label": f"{subject} (demo)"})

        questions = []
        for i, (name, _, _) in enumerate(concepts):
            for fmt, difficulty in CELLS:
                mcq = fmt != "cued_recall"
                questions.append({
                    "id": f"{fmt}{difficulty}",
                    "concept_id": f"c{i}",
                    "type": fmt,
                    "difficulty": difficulty,
                    "stem": f"[demo · {fmt} · level {difficulty}] {name}?",
                    "options": [
                        {"label": "A", "text": "correct option", "correct": True,
                         "why": "This is demo data, not real teaching material."},
                        {"label": "B", "text": "wrong option", "correct": False,
                         "why": "This is demo data, not real teaching material."},
                    ] if mcq else [],
                    "answer_text": None if mcq else name,
                    "accepted_answers": [],
                    "cue": "demo cue",
                    "why_right": "Demo data. Build a real question set from the Library.",
                    "derive_from": "Demo data.",
                    "visual": "| column | column |\n|---|---|\n| demo | data |",
                    "memory_hook": "Demo data.",
                    "key_clue": "demo",
                    "takeaway": "Demo data.",
                    "source_ref": f"{subject} (demo)",
                })

        for row in bank.save_questions(questions, mapping,
                                       source_ref={"label": f"{subject} (demo)"}):
            qmap[row["question_id"]] = row["concept_id"]

    rng = random.Random(7)
    attempts = 0
    for qid, cid in qmap.items():
        p = SKILL.get(cid.split(".")[0], 0.5)
        for _ in range(rng.randint(2, 5)):
            correct = rng.random() < p
            if correct:
                confidence = "knew" if rng.random() < 0.7 else "unsure"
            else:
                confidence = "guessed" if rng.random() < 0.3 else "unsure"
            bank.record_attempt(question_id=qid, correct=correct,
                                confidence=confidence,
                                rt_ms=rng.randint(3000, 40000),
                                session_id="demo")
            attempts += 1

    print(f"concepts:  {db.q1('SELECT COUNT(*) n FROM concept')['n']}")
    print(f"questions: {db.q1('SELECT COUNT(*) n FROM question')['n']}")
    print(f"attempts:  {attempts}")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reset", action="store_true", help="wipe existing data first")
    ap.add_argument("--no-seed", action="store_true", help="only wipe, don't add demo data")
    args = ap.parse_args()

    db.configure(DB_PATH)
    taxonomy.seed()

    if args.reset:
        reset()
    if not args.no_seed:
        seed()
        print("\nStart the app and open the Mastery map tab.")


if __name__ == "__main__":
    main()
