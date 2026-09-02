"""
Ingesting a textbook - First Aid specifically, but the shape is general.

The book is 849 pages and 257 MB. It cannot be uploaded, cannot fit in a
context window, and does not need to: everything structural is extractable
locally, and the only thing worth asking a model for is the concept inventory
of one section at a time.

THE PIPELINE
------------
  1. SEGMENT locally with pypdf. Every First Aid page carries a running header
     with its section breadcrumb - "PHARMACOLOGY-AUTONOMIC DRUGS" - which is a
     far more reliable section signal than the PDF outline, whose titles are
     duplicated and inconsistently cased.
  2. MAP those section paths onto the existing topic tree.
  3. SCORE high-yield from structural signals alone (below).
  4. EXTRACT concept names per section with Claude, one section per call.
  5. STORE names, topic paths, page ranges, and yield scores.

WHAT IS NEVER STORED
--------------------
No prose, no tables, no figures, no First Aid mnemonics. Section text lives in
memory for the duration of one extraction call and is discarded. What persists
is a concept name, where it sits in the taxonomy, and which pages of HER copy
to look at. The app cites; it does not reproduce.

That is also the pedagogically correct call: First Aid's mnemonics are long
first-letter strings, which is precisely the format the learner profile rules
out in favour of visual and spatial hooks.
"""

from __future__ import annotations

import re
import time
import uuid
from collections import Counter
from pathlib import Path

from . import claude, db, taxonomy
from . import learner_profile

# A First Aid running header looks like:
#
#   BIOCHEmISTRY ` BIOCHEMISTRY—MOlECUl ARBIOCHEmISTRY ` ... SECTION II
#
# discipline, a backtick, then "DISCIPLINE—SUBSECTION" - the whole thing
# duplicated and the case scrambled by letter-spacing in the source. Trying to
# reconstruct readable text from that is a losing game, so we do not: we reduce
# it to bare letters and match it against the taxonomy we already have. That
# yields a clean display path and the topic id in one step.

SECTION_NOISE = re.compile(
    r"\bSEC\s?TI?o?N\s+[IVXivx]+\d*|\bNOTES\b|\bHIGH[- ]?YIELD\b|\d+\s*$", re.I)

DASHES = "\u2014\u2013-"


def _letters(text: str) -> str:
    return re.sub(r"[^A-Za-z]", "", text or "").upper()


def parse_header(first_line: str) -> tuple[str, str]:
    """(discipline_letters, subsection_letters) from a running header.

    The book uses four shapes and all of them turn up:

        DISCIPLINE ` DISCIPLINE—SUBSECTION...     the common case
                   ` DISCIPLINE—SUBSECTION       Renal: nothing before the tick
        DISCIPLINE ` SUBSECTION...               MSK, Rapid Review: no dash
        section iii498 DISCIPLINE ` SUBSECTION   the noise runs into a page number
    """
    line = SECTION_NOISE.sub(" ", first_line or "")
    parts = line.split("`")
    if len(parts) < 2:
        return "", ""

    head = _letters(parts[0])
    tail = parts[1]
    sub_raw = tail

    for d in DASHES:
        if d in tail:
            before, sub_raw = tail.split(d, 1)
            # Renal's header carries the discipline only after the backtick.
            if not head:
                head = _letters(before)
            break

    if not head:
        return "", ""

    sub = _letters(sub_raw)
    # The header repeats itself, so the discipline is glued onto the end of the
    # subsection. Strip it by letter count, not by string match - the spacing
    # between the two copies is unreliable.
    if sub.endswith(head) and len(sub) > len(head):
        sub = sub[: len(sub) - len(head)]
    return head, sub


_TAXONOMY_CACHE: dict | None = None


def _taxonomy_index() -> dict:
    """{discipline_letters: {id, name, children: {sub_letters: {id, name}}}}"""
    global _TAXONOMY_CACHE
    if _TAXONOMY_CACHE is not None:
        return _TAXONOMY_CACHE

    index: dict = {}
    for row in db.q("SELECT id, name FROM topic WHERE depth = 0"):
        index[_letters(row["name"])] = {
            "id": row["id"], "name": row["name"], "children": {}}
    for row in db.q("SELECT id, name, parent_id FROM topic WHERE depth = 1"):
        for entry in index.values():
            if entry["id"] == row["parent_id"]:
                entry["children"][_letters(row["name"])] = {
                    "id": row["id"], "name": row["name"]}
    _TAXONOMY_CACHE = index
    return index


def _common_prefix(a: str, b: str) -> str:
    out = []
    for x, y in zip(a, b):
        if x != y:
            break
        out.append(x)
    return "".join(out)


def match_taxonomy(discipline: str, subsection: str) -> tuple[str, str]:
    """Map scrambled header letters onto a real topic. Returns (path, topic_id).

    Matching is on bare letters, so "MOlECUl AR" and "Molecular" are the same
    string by the time they are compared. A discipline that matches nothing
    still returns a readable path, so the section shows up as unmapped rather
    than being silently dropped.
    """
    index = _taxonomy_index()

    entry = index.get(discipline)
    if entry is None:
        for key, e in index.items():
            if discipline.startswith(key) or key.startswith(discipline):
                entry = e
                break
    if entry is None:
        # The book names systems more fully than we do. A long shared prefix is
        # a safe match; a short one would collide (Pathology / Pharmacology).
        best, best_len = None, 0
        for key, e in index.items():
            n = len(_common_prefix(discipline, key))
            if n >= 8 and n > best_len:
                best, best_len = e, n
        entry = best
    if entry is None:
        path = f"{discipline.title()} / {subsection.title()}" if subsection \
            else discipline.title()
        return path, "unsorted"

    if not subsection:
        return entry["name"], entry["id"]

    child = entry["children"].get(subsection)
    if child is None:
        for key, c in entry["children"].items():
            if subsection.startswith(key) or key.startswith(subsection):
                child = c
                break
    if child is None:
        return f"{entry['name']} / {subsection.title()}", entry["id"]
    return f"{entry['name']} / {child['name']}", child["id"]


# First Aid's own distillation at the back of the book. A concept appearing in
# these pages has been singled out by the book's editors, which is a stronger
# high-yield signal than anything we could infer from page counts.
RAPID_REVIEW_TITLES = [
    "Pathophysiology of Important Diseases", "Classic Presentations",
    "Classic Labs Findings", "Key Associations", "Equation Review",
    "Easily Confused Medications",
]

MIN_SECTION_PAGES = 2
MAX_EXTRACT_CHARS = 60_000


# --------------------------------------------------------------- segmenting

def scan(pdf_path: Path, progress=None) -> dict:
    """Walk the PDF once and build a section map. Local, no network."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    total = len(reader.pages)

    pages: list[dict] = []
    for i, page in enumerate(reader.pages):
        try:
            text = page.extract_text() or ""
        except Exception:                              # noqa: BLE001
            text = ""
        head, topic_id = "", "unsorted"
        if text:
            first = text.split(chr(10), 1)[0][:200]
            disc, sub = parse_header(first)
            if disc:
                head, topic_id = match_taxonomy(disc, sub)
        pages.append({"n": i + 1, "header": head, "topic_id": topic_id,
                      "chars": len(text)})
        if progress and i % 50 == 0:
            progress(i + 1, total)

    # Collapse consecutive pages sharing a header into one section.
    sections: list[dict] = []
    for p in pages:
        if not p["header"]:
            if sections:
                sections[-1]["page_end"] = p["n"]
                sections[-1]["chars"] += p["chars"]
            continue
        if sections and sections[-1]["path"] == p["header"]:
            sections[-1]["page_end"] = p["n"]
            sections[-1]["chars"] += p["chars"]
        else:
            sections.append({"path": p["header"], "topic_id": p["topic_id"],
                             "page_start": p["n"], "page_end": p["n"],
                             "chars": p["chars"]})

    sections = [s for s in sections
                if s["page_end"] - s["page_start"] + 1 >= MIN_SECTION_PAGES]
    for s in sections:
        s["pages"] = s["page_end"] - s["page_start"] + 1

    return {
        "pages": total,
        "sections": sections,
        "mapped": sum(1 for s in sections if s["topic_id"] != "unsorted"),
        "unmapped": [s["path"] for s in sections if s["topic_id"] == "unsorted"][:20],
    }


def page_text(pdf_path: Path, start: int, end: int) -> str:
    """Text of one page range. Held in memory only for the extraction call."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    out = []
    for i in range(start - 1, min(end, len(reader.pages))):
        try:
            out.append(reader.pages[i].extract_text() or "")
        except Exception:                              # noqa: BLE001
            continue
    return "\n".join(out)[:MAX_EXTRACT_CHARS]


# ------------------------------------------------------------- high yield

def yield_signals(scan_result: dict, pdf_path: Path) -> dict:
    """Structural high-yield signals, computed without a model.

    Three independent signals, all from the book's own structure:

      rapid_review  the term appears in First Aid's Rapid Review distillation
      density       how much space the book spends on that section
      recurrence    the section's discipline recurs across organ systems
    """
    sections = scan_result["sections"]
    if not sections:
        return {"rapid_pages": [], "density": {}, "recurrence": {}}

    rapid_pages = []
    rapid_keys = [_letters(t) for t in RAPID_REVIEW_TITLES]
    for s in sections:
        path_letters = _letters(s["path"])
        if path_letters.startswith("RAPIDREVIEW") or any(
                k and k in path_letters for k in rapid_keys):
            rapid_pages.append((s["page_start"], s["page_end"]))

    chars = [s["chars"] for s in sections if s["chars"]]
    median = sorted(chars)[len(chars) // 2] if chars else 1
    density = {s["path"]: round(min(2.0, s["chars"] / max(1, median)), 3)
               for s in sections}

    disciplines = Counter(s["path"].split(" / ")[-1] for s in sections)
    recurrence = {d: n for d, n in disciplines.items() if n > 1}

    return {"rapid_pages": rapid_pages, "density": density,
            "recurrence": recurrence}


def score_yield(name: str, section_path: str, signals: dict,
                in_rapid_review: bool = False) -> tuple[float, str]:
    """Combine the structural signals into a 0-1 score and a tier."""
    score = 0.5
    if in_rapid_review:
        score += 0.30     # the book's own editors singled it out
    score += 0.10 * (signals["density"].get(section_path, 1.0) - 1.0)
    discipline = section_path.split(" / ")[-1]
    if signals["recurrence"].get(discipline, 0) > 3:
        score += 0.05     # a discipline the book returns to across systems

    score = max(0.15, min(1.0, score))
    tier = ("very_high" if score >= 0.85 else "high" if score >= 0.7
            else "medium" if score >= 0.45 else "low")
    return round(score, 3), tier


# --------------------------------------------------------------- extraction

CONCEPTS_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "description": "Discrete testable concepts this section covers. Names and one-liners only - never the book's own wording, tables, figures or mnemonics.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {
                        "type": "string",
                        "description": "The concept's standard medical name, as a clinician would say it. Not the book's heading verbatim if that differs.",
                    },
                    "one_line": {
                        "type": "string",
                        "description": "One short line, in your own words, on what it is. Never copied from the page.",
                    },
                    "yield": {"type": "string", "enum": ["high", "medium", "low"]},
                    "confusable_with": {"type": "string"},
                    "page": {"type": "integer", "description": "Best-guess page within the given range."},
                },
                "required": ["name", "one_line", "yield", "confusable_with", "page"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["concepts"],
    "additionalProperties": False,
}

EXTRACT_PROMPT = """\
Below is the raw text of pages {start}-{end} of a medical textbook, section
"{path}".

Build a concept inventory for it: the discrete, testable ideas this section
covers. A concept is the size of one exam item — split anything larger.

## Copyright constraint, and it is not negotiable

Return concept NAMES and one-line descriptions **in your own words**. Do not
reproduce the book's sentences, tables, figures, or mnemonics. Do not quote it.
The output is an index into her own copy, not a substitute for it. If a concept
can only be described by copying the page, give it a plain clinical name and a
generic one-liner instead.

## Also

- Skip anything that is navigation, a page header, an image credit, or an
  artefact of text extraction rather than content.
- `yield` is your read of how heavily this is tested on USMLE Step 1.
- `confusable_with` is what she will most likely mix it up with; "none" is a
  valid answer.
- If the text is too garbled to read reliably, return an empty list rather
  than guessing at concepts that may not be there.

---
{text}
---
"""


def extract_section(pdf_path: Path, section: dict, signals: dict,
                    source_id: str) -> dict:
    """Pull concepts out of one section and persist them. One API call."""
    text = page_text(pdf_path, section["page_start"], section["page_end"])
    if len(text.strip()) < 400:
        return {"section": section["path"], "concepts": 0,
                "skipped": "not enough readable text"}

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": EXTRACT_PROMPT.format(
            start=section["page_start"], end=section["page_end"],
            path=section["path"], text=text)}],
        schema=CONCEPTS_SCHEMA,
        max_tokens=12000,
        task="book_section",
        effort="medium",
    )
    found = claude.json_of(msg)["concepts"]

    in_rapid = any(section["page_start"] >= a and section["page_end"] <= b
                   for a, b in signals["rapid_pages"])
    topic_id = section["topic_id"]
    made = 0

    for c in found:
        score, tier = score_yield(c["name"], section["path"], signals, in_rapid)
        # The model's own read and the structural signal both count; the
        # structural one is the book's editorial judgement and gets the edge.
        if c.get("yield") == "high":
            score = min(1.0, score + 0.1)
        elif c.get("yield") == "low":
            score = max(0.15, score - 0.1)

        cid = taxonomy.resolve_concept(
            c["name"], topic_id=topic_id, one_line=c.get("one_line", ""),
            yield_tier=tier,
            source_refs=[{
                "source_id": source_id, "label": "First Aid",
                "section": section["path"], "page": c.get("page"),
            }],
        )
        db.run("UPDATE concept SET high_yield = ?, hy_tier = ? WHERE id = ?",
               score, tier, cid)

        other = (c.get("confusable_with") or "").strip()
        if other and other.lower() not in ("none", "n/a"):
            taxonomy.link(cid, taxonomy.resolve_concept(other, topic_id=topic_id))
        made += 1

    db.run(
        "INSERT OR REPLACE INTO source_section (id, source_id, section_path, "
        "topic_id, page_start, page_end, ingested_at) VALUES (?,?,?,?,?,?,?)",
        f"sec_{uuid.uuid4().hex[:8]}", source_id, section["path"], topic_id,
        section["page_start"], section["page_end"], time.time(),
    )
    return {"section": section["path"], "concepts": made,
            "pages": f"{section['page_start']}-{section['page_end']}",
            "rapid_review": in_rapid}


def register(pdf_path: Path, title: str, pages: int) -> str:
    sid = f"src_{uuid.uuid4().hex[:8]}"
    db.run(
        "INSERT INTO source (id, title, kind, filename, pages, added_at) "
        "VALUES (?,?,?,?,?,?)",
        sid, title, "textbook", pdf_path.name, pages, time.time(),
    )
    return sid


def ingested(source_id: str) -> list[str]:
    return [r["section_path"] for r in db.q(
        "SELECT section_path FROM source_section WHERE source_id = ?", source_id)]


def sources() -> list[dict]:
    out = []
    for r in db.q("SELECT * FROM source WHERE kind = 'textbook' ORDER BY added_at DESC"):
        d = dict(r)
        d["sections_done"] = db.q1(
            "SELECT COUNT(*) n FROM source_section WHERE source_id = ?", r["id"])["n"]
        d["concepts"] = db.q1(
            "SELECT COUNT(*) n FROM concept WHERE source_refs LIKE ?",
            f'%"{r["id"]}"%')["n"]
        out.append(d)
    return out
