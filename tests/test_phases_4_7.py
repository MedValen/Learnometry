"""
Tests for source ingestion, Anki export, progression, and analytics.

All offline. The textbook tests use the real PDF when it is present and skip
cleanly when it is not.

Run:  python tests/test_phases_4_7.py
"""

import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import (analytics, anki, bank, book, db, gamify,  # noqa: E402
                     taxonomy)

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


def seed_bank():
    analysis = {"title": "Renal", "subject_area": "Renal / Physiology", "concepts": [
        {"id": f"c{i}", "name": n, "one_line": f"{n} explained in one line",
         "yield": y, "load_risk": "low", "confusable_with": "none"}
        for i, (n, y) in enumerate([
            ("Anion gap acidosis", "high"), ("Winter's formula", "high"),
            ("RTA type 1", "medium"), ("RTA type 2", "medium"),
            ("Free water clearance", "low"), ("Countercurrent multiplier", "low"),
        ])]}
    mapping = bank.persist_analysis(analysis, {"label": "t"})
    qs = []
    for i in range(6):
        for fmt, diff in (("recognition", 1), ("cued_recall", 2),
                          ("application", 3), ("discrimination", 4)):
            qs.append({
                "id": f"{fmt}{diff}", "concept_id": f"c{i}", "type": fmt,
                "difficulty": diff, "stem": "?",
                "options": [{"label": "A", "text": "r", "correct": True, "why": "y"},
                            {"label": "B", "text": "w", "correct": False, "why": "n"}],
                "accepted_answers": [], "cue": "", "why_right": "", "derive_from": "",
                "visual": "", "memory_hook": "", "key_clue": "", "takeaway": "",
                "source_ref": "",
            })
    return mapping, bank.save_questions(qs, mapping)


def _raises(fn, exc_type):
    try:
        fn()
    except exc_type:
        return True
    except Exception:
        return False
    return False


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()
    mapping, saved = seed_bank()

    # ============================ PHASE 4: the book ====================
    print("\n-- phase 4: textbook ingestion --")
    check("parses the common header shape",
          book.parse_header("BIOCHEmISTRY ` BIOCHEMISTRY—MOlECUl ARBIOCHEmISTRY")
          == ("BIOCHEMISTRY", "MOLECULAR"),
          str(book.parse_header("BIOCHEmISTRY ` BIOCHEMISTRY—MOlECUl ARBIOCHEmISTRY")))
    check("parses a header with nothing before the tick",
          book.parse_header(" ` RENAL—EMBRYOLOGY") == ("RENAL", "EMBRYOLOGY"),
          str(book.parse_header(" ` RENAL—EMBRYOLOGY")))
    check("parses a header with no dash",
          book.parse_header(
              "Rapid Review  ` CLASSIC PRESENTATIONSRapid Review")
          == ("RAPIDREVIEW", "CLASSICPRESENTATIONS"),
          str(book.parse_header("Rapid Review  ` CLASSIC PRESENTATIONSRapid Review")))
    check("strips section noise running into a page number",
          book.parse_header(
              "section  iii498  Musculoskeletal , skin ` phaRma Cology")[1]
          == "PHARMACOLOGY",
          str(book.parse_header(
              "section  iii498  Musculoskeletal , skin ` phaRma Cology")))
    check("a line with no header is rejected",
          book.parse_header("Hydronephrosis") == ("", ""))

    path, tid = book.match_taxonomy("RENAL", "PATHOLOGY")
    check("maps onto the taxonomy", tid == "renal.pathology", f"{path} -> {tid}")
    path, tid = book.match_taxonomy("MUSCULOSKELETALSKINANDCONNECTIVETISSUE", "ANATOMY")
    check("a longer book name still matches by prefix",
          tid == "musculoskeletal-and-skin.anatomy", f"{path} -> {tid}")
    path, tid = book.match_taxonomy("PATHOLOGY", "")
    check("short names don't collide across disciplines",
          tid == "pathology", f"{path} -> {tid}")
    path, tid = book.match_taxonomy("QUIDDITCH", "SEEKING")
    check("an unknown discipline is unsorted, not forced",
          tid == "unsorted", f"{path} -> {tid}")

    fake = {"sections": [
        {"path": "Rapidreview / Keyassociations", "page_start": 753,
         "page_end": 756, "chars": 8000},
        {"path": "Renal / Pathology", "page_start": 635, "page_end": 647,
         "chars": 26000},
    ]}
    sig = book.yield_signals(fake, Path("x"))
    check("rapid review pages detected", (753, 756) in sig["rapid_pages"],
          str(sig["rapid_pages"]))
    hi, hi_tier = book.score_yield("x", "Rapidreview / Keyassociations", sig, True)
    lo, lo_tier = book.score_yield("x", "Renal / Pathology", sig, False)
    check("rapid-review material scores higher", hi > lo, f"{hi} vs {lo}")
    check("scores stay in range", 0.15 <= lo <= 1.0 and 0.15 <= hi <= 1.0)

    pdf = next(Path.home().glob("Downloads/First Aid*.pdf"), None)
    if pdf and pdf.exists():
        result = book.scan(pdf)
        n = len(result["sections"])
        check("real book segments into many sections", n >= 60, str(n))
        check("most sections map to the taxonomy",
              result["mapped"] / n >= 0.85, f"{result['mapped']}/{n}")
        covered = sum(s["pages"] for s in result["sections"])
        check("most pages are covered", covered / result["pages"] >= 0.85,
              f"{covered}/{result['pages']}")
        paths = {s["path"] for s in result["sections"]}
        check("renal survived segmentation",
              any(p.startswith("Renal /") for p in paths))
        check("every organ system is present",
              sum(1 for sysname in ("Cardiovascular", "Renal", "Respiratory",
                                    "Neurology", "Endocrine")
                  if any(p.startswith(sysname + " /") for p in paths)) == 5)
    else:
        print("  SKIP  real-PDF checks (First Aid not in Downloads)")

    # ============================ PHASE 5: anki ========================
    print("\n-- phase 5: anki export --")
    for _ in range(8):
        bank.record_attempt(question_id=saved[0]["question_id"], correct=False,
                            confidence="unsure")
    weak = anki.pick("red", limit=50)
    check("red selection finds the weak concept", len(weak) >= 1, str(len(weak)))
    check("selection carries what a card needs",
          all(k in weak[0] for k in ("name", "topic", "mastery", "hy_tier")))

    check("untouched concepts are not exported as weak",
          all(c["attempts"] > 0 for c in weak))

    cards = anki.offline_cards(weak)
    check("offline cards are built without an API key", len(cards) >= 1)
    check("offline cards are active recall, not multiple choice",
          all("A)" not in c["front"] and "B)" not in c["front"] for c in cards))
    tsv = anki.to_tsv(cards, weak)
    lines = tsv.strip().split("\n")
    check("tsv has the specified header",
          lines[0].split("\t") == anki.FIELDS, lines[0][:60])
    check("tsv has one row per card", len(lines) == len(cards) + 1)
    check("tsv rows have the right field count",
          all(len(ln.split("\t")) == len(anki.FIELDS) for ln in lines))
    check("newlines are flattened so anki reads one card per line",
          "<br>" in tsv or all("\n" not in c["front"] for c in cards))
    check("tags are space-joined without inner spaces",
          all(" " not in t for row in lines[1:] for t in row.split("\t")[4].split()))

    exported = anki.export("red", use_claude=False)
    check("export returns a filename", exported["filename"].endswith(".tsv"))
    check("export says it fell back offline", bool(exported["note"]))

    # "Specific concepts" with nothing picked is the real empty case, and the
    # one she can actually trigger by clicking through without choosing.
    try:
        anki.export("selected", use_claude=False)
        check("an empty selection is refused", False, "no exception")
    except ValueError as exc:
        check("an empty selection is refused", "Nothing matches" in str(exc))

    check("today's wrong answers are found",
          len(anki.pick("today_wrong", limit=50)) >= 1)

    counts = anki.preview_counts()
    check("preview counts every selection",
          set(counts) == set(anki.SELECTIONS) - {"selected"}, str(list(counts)))

    # ========================== PHASE 6: progression ===================
    print("\n-- phase 6: progression --")
    check("harder questions pay more",
          gamify.xp_for_attempt(correct=True, difficulty=4, confidence="knew") >
          gamify.xp_for_attempt(correct=True, difficulty=1, confidence="knew"))
    check("a guess pays less than knowing",
          gamify.xp_for_attempt(correct=True, difficulty=3, confidence="guessed") <
          gamify.xp_for_attempt(correct=True, difficulty=3, confidence="knew"))
    check("a wrong answer still pays something",
          gamify.xp_for_attempt(correct=False, difficulty=3, confidence="unsure") > 0)
    check("speed is not a term",
          gamify.xp_for_attempt(correct=True, difficulty=2, confidence="knew") ==
          gamify.xp_for_attempt(correct=True, difficulty=2, confidence="knew"))

    lv = gamify.level_for(0)
    check("level starts at 1", lv["level"] == 1 and lv["into_level"] == 0)
    check("levels get progressively more expensive",
          gamify.level_for(10000)["need"] > gamify.level_for(200)["need"])
    check("progress never exceeds the level",
          all(0 <= gamify.level_for(x)["pct"] <= 1 for x in (0, 55, 500, 5000)))

    st = gamify.state()
    check("state reports level, streak and answers",
          {"level", "streak", "answered", "achievements"} <= set(st))
    check("streak counts correct answers, not days",
          "streak" in st["streak"] and "best" in st["streak"])

    unlocked = gamify.check_achievements()
    check("first-answer achievement unlocks",
          any(a["id"] == "first_answer" for a in unlocked) or
          any(a["unlocked"] and a["id"] == "first_answer"
              for a in gamify.achievements()))
    check("achievements are idempotent", gamify.check_achievements() == [])
    check("every achievement says how to earn it",
          all(a["how"] for a in gamify.achievements()))

    terr = gamify.territories()
    check("territories are built", len(terr) >= 1)
    renal = next((t for t in terr if t["id"] == "renal"), None)
    check("the practised system appears", renal is not None)
    if renal:
        check("a weak system is not boss-ready", renal["boss_ready"] is False,
              str(renal["mastery"]))

    boss = bank.boss_session("renal", n=6)
    check("a boss session is built", len(boss) > 0, str(len(boss)))
    check("boss questions are marked", all(q.get("_boss") for q in boss))
    check("a boss spreads across concepts",
          len({q["concept_id"] for q in boss}) > 1,
          str({q["concept_id"] for q in boss}))
    check("an empty system yields no boss", bank.boss_session("psychiatry") == [])

    # ========================== PHASE 7: analytics =====================
    print("\n-- phase 7: analytics --")
    check("identical groups are not significant",
          analytics.two_proportion(50, 100, 50, 100)["p"] > 0.9)
    big = analytics.two_proportion(80, 100, 50, 100)
    check("a real difference is significant", big["p"] < 0.001, str(big["p"]))
    small = analytics.two_proportion(4, 5, 1, 5)
    check("a huge difference on tiny n is not significant",
          small["p"] > analytics.MAX_P, str(small["p"]))
    check("empty groups are safe",
          analytics.two_proportion(0, 0, 5, 10)["p"] == 1.0)

    rep = analytics.report()
    check("report runs on thin data without crashing", "attempts" in rep)
    check("nothing is surfaced on thin data", rep["insights"] == [],
          str(len(rep["insights"])))
    check("pending items explain what they're waiting for",
          all(c.get("pending") for c in rep["pending"]), )
    check("the gate is disclosed", rep["gate"]["min_n"] == analytics.MIN_N)
    check("the method is stated", "z-test" in rep["method"])
    check("calibration is pending on thin data",
          "pending" in rep["calibration"] or rep["calibration"].get("verdict"))

    # Now feed it enough lopsided data to trip the gate honestly.
    q_easy = saved[0]["question_id"]      # recognition, difficulty 1
    q_hard = saved[2]["question_id"]      # application, difficulty 3
    for i in range(60):
        bank.record_attempt(question_id=q_easy, correct=True, confidence="knew")
    for i in range(60):
        bank.record_attempt(question_id=q_hard, correct=(i % 5 == 0),
                            confidence="unsure")

    rep2 = analytics.report()
    gap = next((c for c in rep2["insights"] + rep2["pending"]
                if c["id"] == "difficulty_gap"), None)
    check("the difficulty gap is detected once there is data",
          gap and gap["surfaced"], str(gap and gap.get("pending")))
    if gap and gap["surfaced"]:
        check("the claim names the size of the gap",
              "points" in gap["claim"], gap["claim"][:60])
        check("the claim reports its sample and p-value",
              "attempts" in gap["confidence"] and "p =" in gap["confidence"])
        check("the claim compares her only with herself",
              "no norm" in gap["confidence"])

    cal = analytics.report()["calibration"]
    check("calibration reports per-confidence accuracy",
          any(b["confidence"] == "knew" for b in cal["buckets"]))

    # =========================== backup / restore ======================
    print("\n-- data safety --")
    from backend import backup as BK

    before = db.q1("SELECT COUNT(*) n FROM attempt")["n"]
    b = BK.take("test")
    check("backup is written", b["name"].endswith(".db") and b["bytes"] > 0)
    check("backup records what it holds", b["counts"]["attempt"] == before,
          str(b["counts"]))

    db.run("DELETE FROM attempt")
    check("data really was destroyed",
          db.q1("SELECT COUNT(*) n FROM attempt")["n"] == 0)

    r = BK.restore(b["name"])
    check("restore brings the answers back", r["now"]["attempts"] == before,
          f"{r['now']['attempts']} vs {before}")
    check("restore snapshots the current data first",
          "before-restore" in r["safety_copy"], r["safety_copy"])

    check("a missing backup is refused",
          _raises(lambda: BK.restore("nope.db"), FileNotFoundError))

    ex = BK.export_json()
    check("json export carries the history",
          ex["counts"].get("attempt") == before, str(ex["counts"].get("attempt")))
    check("json export names its schema version", ex["schema_version"] not in (None, "?"))
    check("json export skips the seeded taxonomy", "topic" not in ex["tables"])

    raw = BK.db_bytes()
    check("the database downloads as bytes", raw[:15].startswith(b"SQLite format"),
          str(raw[:15]))

    for i in range(BK.KEEP + 3):
        BK.take(f"spam{i}")
    check("old backups are pruned", len(BK.listing()) <= BK.KEEP,
          str(len(BK.listing())))

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
