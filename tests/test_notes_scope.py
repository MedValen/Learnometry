"""
Tests for standing notes and material-level scoping.

Run:  python tests/test_notes_scope.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import (  # noqa: E402
    db, generate, importer, learner_profile, library, notes_memory, scope,
    taxonomy, users,
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
    user = users.ensure_default()

    # ========================== standing notes =========================
    print("\n-- standing notes --")
    check("a fresh user has no notes", notes_memory.listing(user["id"]) == [])

    n1 = notes_memory.add(user["id"], "Professor said the boards weight this differently.",
                          kind="emphasis")
    check("a note is stored", n1["text"].startswith("Professor said"))
    check("its kind is kept", n1["kind"] == "emphasis")
    check("it is active by default", n1["active"] is True)
    check("an emphasis note reaches the prompt", n1["in_prompt"] is True)

    check("an empty note is refused",
          _raises(lambda: notes_memory.add(user["id"], "   "), ValueError))
    odd = notes_memory.add(user["id"], "x", kind="not-a-kind")
    check("an unknown kind falls back rather than failing",
          odd["kind"] == "context")
    notes_memory.remove(odd["id"])

    sched = notes_memory.add(user["id"], "Clinic Thursdays.", kind="schedule")
    check("a scheduling note is stored", sched["active"] is True)
    check("but it is NOT sent to the model", sched["in_prompt"] is False)

    # --- the prompt ----------------------------------------------------
    print("\n-- notes in the prompt --")
    learner_profile.invalidate()
    p = learner_profile.for_user(users.get(user["id"]))
    check("the notes block appears", "STANDING NOTES" in p)
    check("the emphasis note is in it", "boards weight this differently" in p)
    check("the schedule note is not", "Clinic Thursdays" not in p)
    check("notes are framed as fact, not suggestion",
          "not as suggestions" in p)
    check("the profile contract itself survives alongside the notes",
          "NO NAKED LISTS OF FIVE" in p and
          "Do not invent characteristics" in p)

    # --- muting --------------------------------------------------------
    notes_memory.update(n1["id"], active=False)
    learner_profile.invalidate()
    p2 = learner_profile.for_user(users.get(user["id"]))
    check("a muted note leaves the prompt",
          "boards weight this differently" not in p2)
    check("but is still on file",
          any(n["id"] == n1["id"] for n in notes_memory.listing(user["id"])))
    notes_memory.update(n1["id"], active=True)

    learner_profile.invalidate()
    check("unmuting brings it back",
          "boards weight this differently" in
          learner_profile.for_user(users.get(user["id"])))

    # A user with no notes must not gain a stray empty header.
    other = users.create("Note-free")
    check("a user with no notes gets no notes block",
          "STANDING NOTES" not in learner_profile.for_user(other))
    check("for_prompt is empty for them",
          notes_memory.for_prompt(other["id"]) == "")

    # ========================= material scoping ========================
    print("\n-- scoping to specific material --")
    payload = _tiny_lecture("Alpha", "a")
    importer.import_payload(payload, label="Alpha Lecture.pdf")
    f_a = library.add(b"%PDF alpha", "Alpha Lecture.pdf")

    payload_b = _tiny_lecture("Beta", "b")
    importer.import_payload(payload_b, label="Beta Lecture.pdf")
    f_b = library.add(b"%PDF beta", "Beta Lecture.pdf")

    sc_a = scope.Scope.from_dict({"upload_ids": [f_a["id"]]})
    ids_a = scope.allowed(sc_a)
    check("one file scopes to its own concepts", len(ids_a) == 2, str(len(ids_a)))
    check("it excludes the other file's concepts",
          not (ids_a & set(scope.allowed(
              scope.Scope.from_dict({"upload_ids": [f_b["id"]]})))))

    both = scope.allowed(scope.Scope.from_dict(
        {"upload_ids": [f_a["id"], f_b["id"]]}))
    check("two files union their concepts", len(both) == 4, str(len(both)))

    check("a file scope is not 'everything'",
          scope.Scope.from_dict({"upload_ids": [f_a["id"]]}).is_everything is False)
    check("no upload_ids still means everything",
          scope.Scope.from_dict({}).is_everything is True)

    d = scope.describe(sc_a)
    check("the summary names the file", "Alpha Lecture.pdf" in d["summary"], d["summary"])
    check("the count is reported", d["concepts"] == 2)

    # include_unmapped must not smuggle the rest of the bank back in.
    wide = scope.Scope.from_dict(
        {"upload_ids": [f_a["id"]], "include_unmapped": True})
    check("include_unmapped does not widen a file scope",
          len(scope.allowed(wide)) == 2, str(len(scope.allowed(wide))))

    check("a deleted file scopes to nothing rather than crashing",
          scope.allowed(scope.Scope.from_dict({"upload_ids": ["nope"]})) == set())

    # =========================== the spec ==============================
    print("\n-- the authoring spec --")
    users.set_active(user["id"])

    # A fresh install has no profile, so it must not pretend to one.
    blank = importer.spec_text(user["id"])
    check("with no profile the spec says so, rather than inventing scores",
          "No measured profile" in blank)
    check("and still demands the things that do not depend on a profile",
          "self-contained" in blank and "visual" in blank)

    users.update(user["id"], profile=SYNTHETIC_REPORT, profile_kind="report")
    spec = importer.spec_text(user["id"])

    check("the spec states the JSON shape", '"analysis"' in spec and '"questions"' in spec)
    check("it lists the MCQ types from the validator's own set",
          all(t in spec for t in importer.MCQ_TYPES))
    check("it lists the typed types",
          all(t in spec for t in importer.TYPED_TYPES))
    check("it names every DOK level",
          all(lbl in spec for lbl in generate.DOK_LABELS.values()))
    check("the DOK target comes from the constant, not a literal",
          f"{generate.DOK_TARGET_HIGH:.0%}" in spec)
    check("it demands a visual", "visual" in spec and "Required" in spec)
    check("it demands a cue", "cue" in spec)
    check("it demands a why on wrong options", "misconception" in spec)

    check("once a report is entered, its scores are in the spec",
          "Symbol Span" in spec)
    check("the caveat about underived indices is in it",
          "not derived" in spec or "NMI" in spec)
    check("it refuses the learning-style framing",
          "no learning-style claim" in spec)
    check("it says response time is never scored", "NEVER scored" in spec)

    check("standing notes are carried into the spec",
          "boards weight this differently" in spec)
    check("but a scheduling note is not", "Clinic Thursdays" not in spec)

    # A user with no notes and no profile must still get a usable spec.
    bare = importer.spec_text(other["id"])
    check("a profile-less user still gets a spec", '"questions"' in bare)
    check("and it says no profile is on file", "No measured profile" in bare)
    check("and carries no empty notes header", "STANDING NOTES" not in bare)
    check("an unknown user id does not crash",
          '"questions"' in importer.spec_text("nope"))
    check("no user id at all still works", '"questions"' in importer.spec_text(None))

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


# A synthetic report, not a real one. What the assertions are about is its
# SHAPE: visual working memory at the population mean, auditory roughly 1.5 SD
# below it, reasoning intact.
SYNTHETIC_REPORT = {
    "indexes": {"NMI": 97, "VCI": 106, "FRI": 101, "WMI": 80, "AWMI-R": 78},
    "subtests": {
        "Similarities": 12, "Vocabulary": 11, "Matrix Reasoning": 10,
        "Figure Weights": 11, "Visual Puzzles": 8,
        "Digits Forward": 6, "Digit Sequencing": 7, "Running Digits": 7,
        "Symbol Span": 11,
        "Word Reading": 10, "Color Naming": 6,
        "Inhibition": 9, "Inhibition/Switching": 12,
    },
    "accommodations": ["Extended time", "Reduced-distraction testing"],
    "source": "Synthetic fixture, not a real evaluation. Block Design, "
              "Coding and Symbol Search were not administered, so VSI, "
              "PSI and FSIQ are not derived.",
    "notes": "",
}


def _tiny_lecture(title: str, tag: str) -> dict:
    """Two concepts, two questions, valid against the importer."""
    concepts = [
        {"id": f"{tag}1", "name": f"{title} one", "one_line": "x", "yield": "high",
         "load_risk": "x", "confusable_with": "y"},
        {"id": f"{tag}2", "name": f"{title} two", "one_line": "x", "yield": "low",
         "load_risk": "x", "confusable_with": "y"},
    ]
    questions = []
    for i, c in enumerate(concepts):
        questions.append({
            "id": f"{tag}Q{i}", "concept_id": c["id"], "type": "recognition",
            "stem": "Which is correct?", "premise_table": None,
            "options": [
                {"label": "A", "text": "right", "correct": True, "why": ""},
                {"label": "B", "text": "wrong", "correct": False, "why": "m"},
                {"label": "C", "text": "wrong", "correct": False, "why": "m"},
                {"label": "D", "text": "wrong", "correct": False, "why": "m"},
            ],
            "answer_text": None, "accepted_answers": [], "cue": "a hint",
            "why_right": "because", "derive_from": "mechanism",
            "visual": "A -> B", "memory_hook": "picture", "key_clue": "\"which\"",
            "takeaway": "the point", "source_ref": "Slide 1", "difficulty": 3,
            "objective_ids": ["ob1"],
        })
    return {
        "analysis": {
            "title": title, "subject_area": "Test", "overview": "o",
            "orientation_table": "| a |\n|---|", "concepts": concepts,
            "objectives": [{"id": "ob1", "code": "TEST.1",
                            "text": "A stated learning objective."}],
            "count_rationale": "r", "flags": [],
        },
        "questions": questions,
    }


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
