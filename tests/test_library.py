"""
Tests for the persistent upload library and the hand-authored import path.

Run:  python tests/test_library.py
"""

import copy
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, generate, importer, library, taxonomy  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()

    # ============================== library =============================
    print("\n-- library --")
    check("an empty library lists nothing", library.listing() == [])

    a = library.add(b"%PDF-1.4 lecture one", "Lecture A.pdf")
    check("a file is recorded", a["name"] == "Lecture A.pdf")
    check("it reports its size", a["bytes"] == len(b"%PDF-1.4 lecture one"))
    check("it is present on disk", a["present"] is True)

    # The bug that made three copies of one lecture pile up on disk.
    again = library.add(b"%PDF-1.4 lecture one", "Lecture A (1).pdf")
    check("the same bytes do not create a second row",
          again["id"] == a["id"] and len(library.listing()) == 1)

    b_ = library.add(b"%PDF-1.4 lecture two", "Lecture B.pdf")
    check("different bytes do create a second row", len(library.listing()) == 2)
    check("ids are content hashes, so they differ", a["id"] != b_["id"])

    # Survives a restart: this is the whole point of the table.
    db.configure(tmp / "t.db")
    check("the library survives reconnecting to the database",
          len(library.listing()) == 2)

    # A row whose file vanished must say so rather than fail later.
    library.path_of(b_["id"]).unlink()
    check("a missing file is reported, not hidden",
          library.get(b_["id"])["present"] is False)
    check("and it is named in prune_missing",
          "Lecture B.pdf" in library.prune_missing())

    # Orphan adoption - files on disk with no row.
    (library._dir() / "abcd1234_Stray Lecture.pdf").write_bytes(b"%PDF stray")
    n = library.adopt_orphans()
    check("an untracked file on disk is adopted", n == 1)
    names = {f["name"] for f in library.listing()}
    check("the random upload prefix is stripped from the name",
          "Stray Lecture.pdf" in names, str(names))

    # A duplicate copy under a different name should be removed, not recorded.
    (library._dir() / "ffff0000_Stray Lecture copy.pdf").write_bytes(b"%PDF stray")
    before = len(library.listing())
    library.adopt_orphans()
    check("a duplicate copy on disk is not adopted twice",
          len(library.listing()) == before)

    text = library.add(b"line one\nline two", "notes.txt")
    got = library.extract_text(text["id"])
    check("text extraction works locally, with no API call",
          "line one" in got["text"] and got["chars"] > 0)

    removed = library.remove(a["id"])
    check("removing a file drops the row", removed["name"] == "Lecture A.pdf")
    check("and the file is gone from disk",
          not (library._dir() / f"{a['id']}_Lecture A.pdf").exists())

    # ============================== importer ============================
    print("\n-- importer --")
    payload = json.loads(
        (Path(__file__).resolve().parent.parent / "lectures" / "ftcm26.json")
        .read_text(encoding="utf-8"))

    errs = importer.validate(payload["analysis"], payload["questions"])
    check("the authored lecture validates clean", errs == [], str(errs[:3]))

    s = importer.summarise(payload["analysis"], payload["questions"])
    check("the summary counts concepts", s["concepts"] == 16)
    check("the summary counts questions", s["questions"] == 26)
    check("DOK levels are labelled", s["dok_labels"]["3"] == "Strategic Thinking")
    check("the DOK 3-4 share is computed",
          s["dok_high"] == sum(v for k, v in s["by_dok"].items() if int(k) >= 3))

    # --- each invariant, one at a time ---------------------------------
    def broken(mutate):
        p = copy.deepcopy(payload)
        mutate(p)
        return importer.validate(p["analysis"], p["questions"])

    def has(errs, fragment):
        return any(fragment in e for e in errs)

    check("a dangling concept_id is caught",
          has(broken(lambda p: p["questions"][0].__setitem__("concept_id", "zz")),
              "is not in the analysis"))
    check("an MCQ with no correct option is caught",
          has(broken(lambda p: [o.__setitem__("correct", False)
                                for o in p["questions"][3]["options"]]),
              "exactly one correct option"))
    check("an MCQ with two correct options is caught",
          has(broken(lambda p: p["questions"][3]["options"][1]
                     .__setitem__("correct", True)),
              "exactly one correct option"))
    check("a distractor with no misconception is caught",
          has(broken(lambda p: p["questions"][3]["options"][1]
                     .__setitem__("why", "  ")),
              "explains nothing teaches nothing"))
    check("an empty visual is caught",
          has(broken(lambda p: p["questions"][0].__setitem__("visual", "")),
              "every item ships with"))
    check("an empty cue is caught",
          has(broken(lambda p: p["questions"][0].__setitem__("cue", "")),
              "retrieval ladder"))
    check("a bad DOK level is caught",
          has(broken(lambda p: p["questions"][0].__setitem__("difficulty", 9)),
              "is not 1-4"))
    check("an unknown question type is caught",
          has(broken(lambda p: p["questions"][0].__setitem__("type", "essay")),
              "is not one of"))
    check("a duplicate question id is caught",
          has(broken(lambda p: p["questions"][1]
                     .__setitem__("id", p["questions"][0]["id"])),
              "duplicate ids"))
    check("a concept with no questions is caught",
          has(broken(lambda p: p["analysis"]["concepts"].append(
              {"id": "zz", "name": "Orphan", "one_line": "x", "yield": "low",
               "load_risk": "x", "confusable_with": "x"})),
              "has no questions"))
    check("a typed question with options is caught",
          has(broken(lambda p: p["questions"][0]
                     .__setitem__("options", [{"label": "A", "text": "x",
                                               "correct": True, "why": "x"}])),
              "empty options array"))
    check("a missing required field is caught",
          has(broken(lambda p: p["questions"][0].pop("takeaway")),
              "missing required field"))

    # --- importing actually banks it ------------------------------------
    before_q = db.q1("SELECT COUNT(*) c FROM question")["c"]
    out = importer.import_payload(payload)
    after_q = db.q1("SELECT COUNT(*) c FROM question")["c"]
    check("importing writes questions", after_q > before_q)
    check("it reports what it wrote", out["imported_questions"] == 26)

    # A payload with any error must write nothing at all.
    bad = copy.deepcopy(payload)
    bad["questions"][0]["visual"] = ""
    count_before = db.q1("SELECT COUNT(*) c FROM question")["c"]
    raised = False
    try:
        importer.import_payload(bad)
    except ValueError:
        raised = True
    check("an invalid payload raises", raised)
    check("and writes nothing at all",
          db.q1("SELECT COUNT(*) c FROM question")["c"] == count_before)

    # --- DOK ------------------------------------------------------------
    print("\n-- DOK --")
    check("DOK 1-4 are all labelled", set(generate.DOK_LABELS) == {1, 2, 3, 4})
    check("DOK 3 is Strategic Thinking",
          generate.DOK_LABELS[3] == "Strategic Thinking")
    check("DOK 4 is Extended Thinking",
          generate.DOK_LABELS[4] == "Extended Thinking")
    check("the target asks for at least half at DOK 3+",
          generate.DOK_TARGET_HIGH >= 0.5)
    check("the schema tells the generator her exams are DOK 3-4",
          "DOK 3 AND 4" in json.dumps(generate.QUESTIONS_SCHEMA))

    low = copy.deepcopy(payload)
    for q in low["questions"]:
        q["difficulty"] = 1
    s_low = importer.summarise(low["analysis"], low["questions"])
    check("an all-DOK-1 set is flagged as off target",
          s_low["dok_on_target"] is False and s_low["dok_high"] == 0)

    high = copy.deepcopy(payload)
    for q in high["questions"]:
        q["difficulty"] = 3
    s_high = importer.summarise(high["analysis"], high["questions"])
    check("an all-DOK-3 set is on target", s_high["dok_on_target"] is True)
    check("a DOK-heavy set still imports (DOK is guidance, not a gate)",
          importer.validate(high["analysis"], high["questions"]) == [])

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
