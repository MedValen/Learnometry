"""
Tests for the note critique and the question-reading tactics.

Everything here runs offline - the measured half of the note check and the whole
of the heuristic dissector need no API key.

Run:  python tests/test_notes_tactics.py
"""

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import db, notes, tactics, taxonomy  # noqa: E402

checks = []


def check(label, cond, detail=""):
    checks.append(bool(cond))
    print(f"  {'PASS' if cond else 'FAIL'}  {label}" +
          (f" -- {detail}" if detail and not cond else ""))


OVERWRITTEN = """\
The renal tubular acidoses are a group of disorders that are characterised by a \
normal anion gap metabolic acidosis which occurs in the setting of a relatively \
preserved glomerular filtration rate and they are classified into several types \
depending on the location of the defect within the nephron.
Type 1 renal tubular acidosis is also known as distal renal tubular acidosis and \
it occurs because of a defect in the alpha intercalated cells of the collecting \
duct which are normally responsible for secreting hydrogen ions into the lumen.
Type 2 renal tubular acidosis is also called proximal renal tubular acidosis and \
it is caused by a defect in bicarbonate reabsorption in the proximal convoluted \
tubule which leads to bicarbonate wasting in the urine until the serum level falls.
"""

TIDY = """\
## RTA types

| Type | Defect | Urine pH | K+ |
|---|---|---|---|
| 1 distal | H+ secretion | > 5.5 | low |
| 2 proximal | HCO3 reabsorption | < 5.5 | low |
| 4 | aldosterone | < 5.5 | high |

Mechanism
- distal -> can't secrete H+ -> urine stays alkaline
- proximal -> wastes HCO3 -> acid urine once serum drops
"""

LONG_LIST = """\
Causes
- diabetic ketoacidosis
- lactic acidosis
- uraemia
- methanol
- salicylates
- ethylene glycol
- propylene glycol
- iron
"""

VIGNETTE = (
    "A 62-year-old man comes to the emergency department because of crushing "
    "substernal chest pain that began 2 hours ago while he was mowing the lawn. "
    "He has a history of hypertension and smokes one pack of cigarettes daily. "
    "He is accompanied by his wife, who is very anxious. His temperature is "
    "37.0 C, pulse is 104/min, and blood pressure is 158/94 mm Hg. Physical "
    "examination shows diaphoresis. Which of the following is the most likely "
    "diagnosis?"
)

NEGATED = (
    "A 30-year-old woman is started on lithium. Which of the following is NOT "
    "an expected adverse effect?"
)


def main():
    tmp = Path(tempfile.mkdtemp())
    db.configure(tmp / "t.db")
    taxonomy.seed()

    # --- measurement --------------------------------------------------
    m = notes.measure(OVERWRITTEN)
    check("counts words", m["words"] > 100, str(m["words"]))
    check("detects long lines", m["long_lines"] >= 3, str(m["long_lines"]))
    check("prose ratio high for transcription", m["prose_ratio"] >= 0.9,
          str(m["prose_ratio"]))
    check("no table found in prose", m["has_table"] is False)

    m2 = notes.measure(TIDY)
    check("detects a table", m2["has_table"] is True, str(m2["table_rows"]))
    check("detects headings", m2["headings"] >= 1, str(m2["headings"]))
    check("detects arrows", m2["arrows"] >= 3, str(m2["arrows"]))
    check("tidy notes have a low prose ratio", m2["prose_ratio"] < 0.2,
          str(m2["prose_ratio"]))

    m3 = notes.measure(LONG_LIST)
    check("finds the unbroken list", m3["longest_unbroken_list"] == 8,
          str(m3["longest_unbroken_list"]))

    # --- flags ---------------------------------------------------------
    f = {x["flag"] for x in notes.flags(notes.measure(OVERWRITTEN))}
    check("over-writing flagged", "over-writing" in f, str(f))
    check("missing table flagged", "no table" in f, str(f))

    f2 = {x["flag"] for x in notes.flags(notes.measure(TIDY))}
    check("tidy notes are not flagged for over-writing", "over-writing" not in f2, str(f2))
    check("tidy notes are not flagged for a missing table", "no table" not in f2, str(f2))

    f3 = {x["flag"] for x in notes.flags(notes.measure(LONG_LIST))}
    check("unchunked list flagged", "unchunked list" in f3, str(f3))

    # Regression: a wall of three paragraph-length lines is the worst case of
    # over-writing, and a line-count guard used to let it through.
    wall = " ".join(["word"] * 40) + ".\n" + " ".join(["word"] * 40) + "."
    check("a two-line wall of text still flags over-writing",
          "over-writing" in {x["flag"] for x in notes.flags(notes.measure(wall))},
          str({x["flag"] for x in notes.flags(notes.measure(wall))}))
    check("a short scrap is not flagged",
          not notes.flags(notes.measure("RTA type 1: distal.")),
          str(notes.flags(notes.measure("RTA type 1: distal."))))

    all_flags = notes.flags(notes.measure(OVERWRITTEN))
    check("every flag states its basis", all(x["evidence"] for x in all_flags))
    check("no flag cites laptop-vs-longhand",
          not any("longhand" in x["why"].lower() or "handwrit" in x["why"].lower()
                  for x in all_flags))

    # --- review persists and survives having no API key ----------------
    r = notes.review(OVERWRITTEN, title="RTA lecture", want_critique=False)
    check("review stored", r["id"].startswith("nr_"))
    check("review returns measurements offline", r["metrics"]["words"] > 100)
    check("review returns flags offline", len(r["flags"]) >= 2)
    check("no critique when not asked", r["critique"] is None)

    got = notes.get(r["id"])
    check("review round-trips", got["metrics"]["words"] == r["metrics"]["words"])

    r2 = notes.review(TIDY, title="RTA tables", want_critique=True)
    check("missing API key does not lose the review",
          r2["id"] and r2["metrics"]["has_table"] is True)
    check("missing API key is reported, not swallowed",
          r2["critique"] is None and r2["critique_error"])

    try:
        notes.review("   ")
        check("empty notes refused", False, "no exception")
    except ValueError:
        check("empty notes refused", True)

    h = notes.history()
    check("history lists reviews", len(h["reviews"]) == 2)

    # --- dissection ----------------------------------------------------
    d = tactics.dissect(VIGNETTE)
    check("finds the actual question",
          d["ask"].startswith("Which of the following"), d["ask"][:50])
    check("reads demographics", d["demographics"] and "62" in d["demographics"],
          str(d["demographics"]))
    check("marks lines that carry numbers",
          any("numbers" in ln["marks"] for ln in d["lines"]))
    check("marks lines that carry timing",
          any("when" in ln["marks"] for ln in d["lines"]))
    check("extracts values", len(d["values"]) >= 2, str(d["values"]))
    check("not flagged as negated", d["negated"] is False)
    check("gives a reading order", len(d["how_to_read"]) >= 3)
    check("reading order leads with the ask",
          "last line first" in d["how_to_read"][0].lower())

    dn = tactics.dissect(NEGATED)
    check("detects a negated stem", dn["negated"] is True)
    check("negation is called out in the reading order",
          any("negated" in s.lower() for s in dn["how_to_read"]))

    check("empty stem is safe", tactics.dissect("")["ask"] == "")
    check("single sentence is safe", tactics.dissect("What is the answer?")["ask"])

    # Conservative classification: never call an informative line filler.
    roles = {ln["role"] for ln in d["lines"]}
    check("roles are drawn from the known set",
          roles <= {"ask", "signal", "context", "filler"}, str(roles))
    check("exactly one line is the ask",
          sum(1 for ln in d["lines"] if ln["role"] == "ask") == 1)

    # --- timing guidance ------------------------------------------------
    g = tactics.timing_guidance(None)
    check("untimed guidance says nothing is scored on speed",
          g["mode"] == "untimed" and "speed" in g["body"])
    g2 = tactics.timing_guidance(180)
    check("timed guidance reports the ratio", g2["ratio"] == 2.0, str(g2["ratio"]))
    check("timed guidance promises no cut-off", "not cut you off" in g2["body"])
    check("timer defaults to off", tactics.TIMER_PRESETS[0]["seconds"] is None)
    check("extended-time presets exist",
          {p["seconds"] for p in tactics.TIMER_PRESETS} >= {135, 180})

    # --- playbook honesty -----------------------------------------------
    check("every playbook entry declares its status",
          all(p.get("status") for p in tactics.PLAYBOOK))
    check("playbook does not claim research it doesn't have",
          any("not a research finding" in p["status"] for p in tactics.PLAYBOOK))


    # --- inline highlighting -------------------------------------------
    kinds = {seg["kind"] for ln in d["lines"] for seg in ln["segments"] if seg["kind"]}
    check("marks who", "who" in kinds, str(kinds))
    check("marks timing", "when" in kinds, str(kinds))
    check("marks values", "value" in kinds, str(kinds))
    check("marks findings", "finding" in kinds, str(kinds))
    check("marks history", "history" in kinds, str(kinds))

    for ln in d["lines"]:
        joined = "".join(seg["text"] for seg in ln["segments"])
        if joined != ln["text"]:
            check("segments reassemble to the original line", False, ln["text"][:40])
            break
    else:
        check("segments reassemble to the original line", True)

    check("every marked segment carries a label",
          all(seg.get("label") for ln in d["lines"] for seg in ln["segments"]
              if seg["kind"]))
    check("marks never overlap",
          all(len(ln["segments"]) == len(set(id(x) for x in ln["segments"]))
              for ln in d["lines"]))

    neg_kinds = {seg["kind"] for ln in dn["lines"] for seg in ln["segments"]
                 if seg["kind"]}
    check("negation is marked inline", "negation" in neg_kinds, str(neg_kinds))

    # --- per-question advice -------------------------------------------
    check("advice is generated", len(d["advice"]) >= 3, str(len(d["advice"])))
    texts = " ".join(a["text"] for a in d["advice"])
    check("advice mentions this stem's demographics", "62-year-old" in texts)
    check("advice is specific, not generic",
          any(str(len(d["values"])) in a["text"] for a in d["advice"]))

    lean = tactics.dissect("Which enzyme is deficient in PKU?")
    lean_text = " ".join(a["text"] for a in lean["advice"])
    check("a lean stem is not lectured about padding",
          "framing" not in lean_text and "Skim" not in lean_text, lean_text[:80])
    check("a stem with no numbers says so",
          "No lab values" in lean_text, lean_text[:80])

    neg_advice = " ".join(a["text"] for a in dn["advice"])
    check("negated stems get a warning first",
          dn["advice"][0]["kind"] == "warn", dn["advice"][0]["kind"])

    check("legend only describes real kinds",
          {l["kind"] for l in d["legend"]} == set(tactics.SPAN_LABELS))

    # --- reading a document --------------------------------------------
    doc = tmp / "notes.txt"
    doc.write_text(OVERWRITTEN, encoding="utf-8")
    body = notes.text_from_file(doc, "notes.txt")
    check("reads a text document", len(body) > 100, str(len(body)))

    img = tmp / "photo.png"
    img.write_bytes(b"x")
    try:
        notes.text_from_file(img, "photo.png")
        check("images are refused with a pointer to the vault", False, "no exception")
    except ValueError as exc:
        check("images are refused with a pointer to the vault", "vault" in str(exc))

    weird = tmp / "notes.xyz"
    weird.write_text("x", encoding="utf-8")
    try:
        notes.text_from_file(weird, "notes.xyz")
        check("unknown types refused", False, "no exception")
    except ValueError:
        check("unknown types refused", True)

    failed = len([c for c in checks if not c])
    print(f"\n{len(checks) - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
