"""
Tests for the Phase 3 layer: terms, exams, vault, pins, emphasis, plans.

Anything needing the Claude API is skipped - these cover the parts that must
work offline, which is most of it.

Run:  python tests/test_organizer.py
"""

import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import bank, coach, db, organizer, pinboard, planner, taxonomy, vault  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" — {detail}" if detail and not cond else ""))


def iso(days_from_now):
    return (date.today() + timedelta(days=days_from_now)).strftime("%Y-%m-%d")


def seed_concepts():
    """A small bank so exams have something to map onto."""
    analysis = {
        "title": "Acid-base", "subject_area": "Renal / Physiology",
        "concepts": [
            {"id": "c1", "name": "Anion gap metabolic acidosis", "one_line": "x",
             "yield": "high", "load_risk": "low", "confusable_with": "none"},
            {"id": "c2", "name": "Winter's formula", "one_line": "x",
             "yield": "high", "load_risk": "low", "confusable_with": "none"},
            {"id": "c3", "name": "Renal tubular acidosis", "one_line": "x",
             "yield": "medium", "load_risk": "low", "confusable_with": "none"},
        ],
    }
    mapping = bank.persist_analysis(analysis, {"label": "test"})
    qs = []
    for i in range(3):
        for fmt, diff in (("recognition", 1), ("application", 3)):
            qs.append({
                "id": f"{fmt}{diff}", "concept_id": f"c{i + 1}", "type": fmt,
                "difficulty": diff, "stem": "?", "options": [
                    {"label": "A", "text": "r", "correct": True, "why": "y"},
                    {"label": "B", "text": "w", "correct": False, "why": "n"}],
                "accepted_answers": [], "cue": "", "why_right": "", "derive_from": "",
                "visual": "", "memory_hook": "", "key_clue": "", "takeaway": "",
                "source_ref": "",
            })
    saved = bank.save_questions(qs, mapping)
    return mapping, saved


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "test.db")
    taxonomy.seed()
    mapping, saved = seed_concepts()

    # --- terms & courses -------------------------------------------------
    term = organizer.create_term("Term 4", iso(-30), iso(60))
    check("term created", term["name"] == "Term 4" and term["active"] == 1)

    t2 = organizer.create_term("Term 5")
    check("only one term active at a time",
          organizer.get_term(term["id"])["active"] == 0 and t2["active"] == 1)
    organizer.set_active_term(term["id"])

    course = organizer.create_course(term["id"], "Renal & Genitourinary", "REN401")
    check("course belongs to term", course["term_id"] == term["id"])
    check("courses listed under term",
          len(organizer.list_courses(term["id"])) == 1)

    # --- exams ------------------------------------------------------------
    exam = organizer.create_exam(
        "Renal Midterm", iso(12), term_id=term["id"], course_id=course["id"],
        kind="midterm", topic_ids=["renal.physiology"])
    check("exam days_left computed", exam["days_left"] == 12, str(exam["days_left"]))
    check("exam urgency between 0 and 1", 0 < exam["urgency"] < 1, str(exam["urgency"]))
    check("exam knows its course", exam["course"] == "Renal & Genitourinary")

    past = organizer.create_exam("Old quiz", iso(-5))
    check("past exams excluded from upcoming",
          all(e["id"] != past["id"] for e in organizer.list_exams(upcoming_only=True)))

    concepts = organizer.exam_concepts(exam["id"])
    check("topic reference pulls in concepts", len(concepts) == 3, str(len(concepts)))

    # --- readiness --------------------------------------------------------
    r = organizer.readiness(exam["id"])
    check("readiness computed", 0 <= r["readiness"] <= 1, str(r.get("readiness")))
    check("untested concepts counted", r["concepts_untested"] == 3,
          str(r["concepts_untested"]))
    check("readiness carries its caveat", "not a predicted score" in r["caveat"])

    for _ in range(6):
        bank.record_attempt(question_id=saved[0]["question_id"], correct=True,
                            confidence="knew")
    r2 = organizer.readiness(exam["id"])
    check("readiness rises after correct answers", r2["readiness"] > r["readiness"],
          f"{r['readiness']:.3f} -> {r2['readiness']:.3f}")
    check("high risk list is populated", len(r2["high_risk"]) > 0)

    empty_exam = organizer.create_exam("Unmapped", iso(5))
    check("unmapped exam reports empty, not zero",
          organizer.readiness(empty_exam["id"])["empty"] is True)

    # --- vault ------------------------------------------------------------
    img = tmp / "whiteboard.png"
    img.write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 200)
    asset = vault.add(img, original_name="whiteboard.png", kind="whiteboard",
                      caption="acid-base brain dump",
                      links=[{"kind": "exam", "target_id": exam["id"]}])
    check("file stored", asset["filename"] == "whiteboard.png")
    check("stored path never leaves the server", "stored_path" not in asset)
    check("image detected", asset["is_image"] is True)
    check("linked to exam", any(l["target_id"] == exam["id"] for l in asset["links"]))
    check("findable by link",
          len(vault.listing(link_kind="exam", target_id=exam["id"])) == 1)

    bad = tmp / "notes.exe"
    bad.write_bytes(b"x")
    try:
        vault.add(bad, original_name="notes.exe")
        check("unsupported type rejected", False, "no exception")
    except vault.Rejected:
        check("unsupported type rejected", True)

    # --- pinboard ---------------------------------------------------------
    pin = pinboard.create(kind="mnemonic", title="Winter's formula",
                          body="1.5 x HCO3 + 8", tags=["renal", "formula"],
                          exam_id=exam["id"], starred=True)
    check("pin created", pin["title"] == "Winter's formula" and pin["starred"])
    check("pin tags round-trip", pin["tags"] == ["renal", "formula"])
    check("pin knows its exam", pin["exam_name"] == "Renal Midterm")
    check("filter by tag", len(pinboard.listing(tag="renal")) == 1)
    check("filter by wrong tag is empty", len(pinboard.listing(tag="cardio")) == 0)
    pinboard.update(pin["id"], archived=True)
    check("archived pins hidden by default", len(pinboard.listing()) == 0)
    check("archived pins findable on request",
          len(pinboard.listing(include_archived=True)) == 1)

    # --- emphasis ---------------------------------------------------------
    note = coach.add_note("Dr. Nassar said acid-base is heavily tested",
                          exam_id=exam["id"], said_by="professor",
                          strength="stressed", auto_link=False)
    check("note stored", note["text"].startswith("Dr. Nassar"))
    check("note not applied by default", note["applied"] is False)
    check("boost is proposed, not applied", note["proposed_boost"] > 0)

    cid = mapping["c1"]
    db.run("UPDATE emphasis SET concept_ids = ? WHERE id = ?",
           db.js([{"concept_id": cid, "confidence": "high", "why": "test"}]), note["id"])

    before = db.q1("SELECT emphasis_boost FROM concept WHERE id = ?", cid)["emphasis_boost"]
    coach.apply_note(note["id"])
    after = db.q1("SELECT emphasis_boost FROM concept WHERE id = ?", cid)["emphasis_boost"]
    check("applying a note raises the boost", after > before, f"{before} -> {after}")
    check("note marked applied", coach.get_note(note["id"])["applied"] is True)

    coach.apply_note(note["id"], apply=False)
    reverted = db.q1("SELECT emphasis_boost FROM concept WHERE id = ?", cid)["emphasis_boost"]
    check("un-applying restores exactly", abs(reverted - before) < 1e-9,
          f"{before} -> {reverted}")

    coach.apply_note(note["id"])
    coach.delete_note(note["id"])
    cleaned = db.q1("SELECT emphasis_boost FROM concept WHERE id = ?", cid)["emphasis_boost"]
    check("deleting an applied note removes its boost", abs(cleaned - before) < 1e-9,
          f"{cleaned}")

    # Emphasis must actually reach the selector, or capturing it is theatre.
    db.run("UPDATE concept SET emphasis_boost = 0.3 WHERE id = ?", cid)
    cands = {c.concept_id: c for c in bank.candidates()}
    plain = db.q1("SELECT high_yield FROM concept WHERE id = ?", cid)["high_yield"]
    check("boost reaches the question selector",
          cands[cid].high_yield > plain,
          f"selector sees {cands[cid].high_yield}, base is {plain}")
    db.run("UPDATE concept SET emphasis_boost = 0 WHERE id = ?", cid)

    # --- study plan -------------------------------------------------------
    plan = planner.build(exam["id"], minutes_per_day=45)
    check("plan covers every day until the exam", plan["study_days"] == 13,
          str(plan["study_days"]))
    check("plan has days", len(plan["days"]) == 13)
    check("plan never exceeds stated time",
          all(d["minutes"] <= 45 for d in plan["days"]),
          str([d["minutes"] for d in plan["days"]]))
    check("last day is review only",
          plan["days"][-1]["blocks"][0]["kind"] == "review")
    check("plan warns about untested concepts",
          any("never been practised" in w for w in plan["warnings"]))
    check("plan persisted", planner.latest(exam["id"]) is not None)

    # Genuinely short: tomorrow, 3 minutes a day. Capacity cannot cover it.
    crunch = organizer.create_exam("Tomorrow", iso(1), topic_ids=["renal.physiology"])
    tight = planner.build(crunch["id"], minutes_per_day=3)
    check("tight plan drops concepts and says so",
          tight["concepts_dropped"] and
          any("isn't enough time" in w for w in tight["warnings"]),
          f"dropped={len(tight['concepts_dropped'])}, "
          f"capacity={tight['capacity_questions']}")
    check("dropped concepts are named, not just counted",
          all("name" in c for c in tight["concepts_dropped"]))
    check("tight plan still respects the time limit",
          all(d["minutes"] <= 3 for d in tight["days"]),
          str([d["minutes"] for d in tight["days"]]))
    for mins in (3, 10, 45, 120):
        pl = planner.build(exam["id"], minutes_per_day=mins)
        over = [d["minutes"] for d in pl["days"] if d["minutes"] > mins]
        check(f"never overruns {mins} min/day", not over, str(over))

    roomy = planner.build(exam["id"], minutes_per_day=240)
    check("plan says when there is more time than material",
          any("more time than mapped material" in w for w in roomy["warnings"]),
          str(roomy["warnings"])[:120])
    check("a full plan does not claim spare capacity",
          not any("more time than mapped material" in w for w in tight["warnings"]))

    planner.build(exam["id"], minutes_per_day=5)
    check("newer plan supersedes older",
          planner.latest(exam["id"])["minutes_per_day"] == 5)

    try:
        planner.build(past["id"], minutes_per_day=60)
        check("plan for a past exam refused", False, "no exception")
    except ValueError as exc:
        check("plan for a past exam refused", "days ago" in str(exc))

    try:
        planner.build(empty_exam["id"], minutes_per_day=60)
        check("plan with nothing mapped refused", False, "no exception")
    except ValueError as exc:
        check("plan with nothing mapped refused", "Nothing is mapped" in str(exc))

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
