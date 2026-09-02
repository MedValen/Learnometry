"""
Critiquing her notes.

Two layers, and the split matters:

  MEASURED, offline. Word counts, sentence length, list sizes, table presence,
  copied-prose ratio. Arithmetic over her actual text. No API key, no judgement
  calls, and the numbers are shown so she can check them.

  JUDGED, with Claude. What to change and how, argued from the evidence base
  below plus her own profile, including a rewrite of a short passage so the
  advice is concrete rather than a slogan.

EVIDENCE THIS IS BUILT ON
-------------------------
The framework is Dunlosky et al. (2013), "Improving Students' Learning With
Effective Learning Techniques", which rated ten common study techniques by
utility. It is the honest place to stand because it is explicit about which
techniques are well supported and which are merely popular:

  HIGH utility     practice testing, distributed practice
  MODERATE         elaborative interrogation, self-explanation, interleaving
  LOW              summarisation, highlighting, keyword mnemonics, imagery
                   for text, rereading

Two things the app must NOT claim:

  * The laptop-versus-longhand result (Mueller & Oppenheimer 2014) is widely
    repeated and has not replicated cleanly. We do not tell her to switch to
    paper on that basis.
  * Learning styles have no support. Nothing here says "you're a visual
    learner". The reason to route her through visual material is a measured
    gap between a person's own visual and auditory span - a fact about
    her, not a personality type.

FOR THIS STUDENT SPECIFICALLY
-----------------------------
Live transcription is close to impossible on a low auditory span - notes written while
listening compete for the exact resource she is short of. Notes built AFTER the
lecture from slides, and structured as tables rather than prose, use the channel
that works. Any list longer than about four items is past the
point where she can hold it, so grouping is not tidiness, it is the difference
between usable and not.
"""

from __future__ import annotations

import re
import time
import uuid

from pathlib import Path

from . import claude, db, taxonomy
from . import learner_profile

# Beyond this, a line is likely transcription rather than a note.
LONG_SENTENCE_WORDS = 25
LONG_LINE_WORDS = 35
MAX_COMFORTABLE_LIST = 4


def _sentences(text: str) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]


def measure(text: str) -> dict:
    """Offline structural analysis. Arithmetic only - no opinions."""
    lines = [ln.rstrip() for ln in text.replace("\r\n", "\n").split("\n")]
    nonblank = [ln for ln in lines if ln.strip()]
    words = re.findall(r"[A-Za-z0-9'-]+", text)
    sentences = _sentences(text)

    bullets = [ln for ln in nonblank if re.match(r"^\s*([-*+•·]|\d+[.)])\s+", ln)]
    headings = [ln for ln in nonblank if re.match(r"^\s*#{1,6}\s+", ln)
                or (len(ln.split()) <= 6 and ln.rstrip().endswith(":"))]
    table_rows = [ln for ln in nonblank if ln.count("|") >= 2]
    arrows = len(re.findall(r"(->|→|=>|⇒)", text))

    # Longest unbroken run of list items with no heading between them.
    longest_run, run = 0, 0
    for ln in nonblank:
        if re.match(r"^\s*([-*+•·]|\d+[.)])\s+", ln):
            run += 1
            longest_run = max(longest_run, run)
        elif ln in headings:
            run = 0
    if not bullets:
        longest_run = 0

    long_sentences = [s for s in sentences if len(s.split()) > LONG_SENTENCE_WORDS]
    long_lines = [ln for ln in nonblank if len(ln.split()) > LONG_LINE_WORDS]

    avg_sentence = round(sum(len(s.split()) for s in sentences) / len(sentences), 1) \
        if sentences else 0.0

    # Rough proxy for "wrote it out as prose" vs "compressed it".
    prose_ratio = round(len(long_lines) / len(nonblank), 3) if nonblank else 0.0

    return {
        "words": len(words),
        "lines": len(nonblank),
        "sentences": len(sentences),
        "avg_sentence_words": avg_sentence,
        "long_sentences": len(long_sentences),
        "long_lines": len(long_lines),
        "prose_ratio": prose_ratio,
        "bullets": len(bullets),
        "headings": len(headings),
        "table_rows": len(table_rows),
        "has_table": len(table_rows) >= 2,
        "arrows": arrows,
        "longest_unbroken_list": longest_run,
        "words_per_line": round(len(words) / len(nonblank), 1) if nonblank else 0.0,
    }


def flags(m: dict) -> list[dict]:
    """Structural problems the numbers alone can justify.

    Each carries the evidence strength behind it, because "your lists are too
    long for your span" and "summarising is low-utility" are claims of very
    different weight and she deserves to see which is which.
    """
    out = []

    # Guarded on word count, not line count. Three enormous paragraph-lines is
    # the worst case of over-writing there is, and a >= 5 line guard let it
    # through - exactly backwards.
    if m["prose_ratio"] >= 0.3 and m["words"] >= 60:
        out.append({
            "flag": "over-writing",
            "severity": "high",
            "says": f"{m['long_lines']} of {m['lines']} lines run past "
                    f"{LONG_LINE_WORDS} words. That's transcription, not notes.",
            "why": "Writing full sentences while listening competes for the exact "
                   "resource a lecture is shortest on. It also produces "
                   "text you have to re-read rather than retrieve from.",
            "evidence": "profile + low-utility of rereading (Dunlosky 2013)",
        })

    if m["avg_sentence_words"] > LONG_SENTENCE_WORDS:
        out.append({
            "flag": "long sentences",
            "severity": "medium",
            "says": f"Average sentence is {m['avg_sentence_words']} words.",
            "why": "A long sentence holds a clause open while another resolves. "
                   "One idea per line costs nothing and removes that load.",
            "evidence": "profile",
        })

    if m["longest_unbroken_list"] > MAX_COMFORTABLE_LIST:
        out.append({
            "flag": "unchunked list",
            "severity": "high",
            "says": f"There's a run of {m['longest_unbroken_list']} list items with "
                    f"no grouping.",
            "why": f"Past about {MAX_COMFORTABLE_LIST} items a list stops being "
                   "holdable. Two or three named groups of three is the same "
                   "content in a usable shape.",
            "evidence": "auditory working memory",
        })

    if not m["has_table"] and m["words"] >= 120:
        out.append({
            "flag": "no table",
            "severity": "medium",
            "says": "No table anywhere in these notes.",
            "why": "Your visual working memory is average while your auditory span "
                   "may be the narrower channel. A comparison table uses the other one "
                   "that works; a paragraph uses the one that doesn't.",
            "evidence": "visual vs auditory working memory",
        })

    if m["headings"] == 0 and m["lines"] > 8:
        out.append({
            "flag": "no structure",
            "severity": "medium",
            "says": "No headings or labels.",
            "why": "Unlabelled notes can't be searched or retrieved from — you "
                   "have to read them start to finish to find anything.",
            "evidence": "practical",
        })

    if m["words"] and m["arrows"] == 0 and m["words"] > 200:
        out.append({
            "flag": "no mechanism",
            "severity": "low",
            "says": "No arrows or causal chains.",
            "why": "Notes that record 'X → Y → Z' let "
                   "you rebuild a fact; notes that record the fact alone don't.",
            "evidence": "profile + self-explanation, moderate utility (Dunlosky 2013)",
        })

    return out


# --------------------------------------------------------------- critique

CRITIQUE_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {
            "type": "string",
            "description": "One sentence. Direct. What's the single biggest thing about these notes?",
        },
        "working": {
            "type": "array",
            "description": "What she's already doing well. Be specific and quote her. Empty only if there is genuinely nothing.",
            "items": {"type": "string"},
        },
        "problems": {
            "type": "array",
            "description": "Ordered most important first. At most four - a list of nine is the same mistake this app is telling her not to make.",
            "items": {
                "type": "object",
                "properties": {
                    "problem": {"type": "string"},
                    "quote": {
                        "type": "string",
                        "description": "The exact snippet from her notes that shows it. Must appear verbatim in her text.",
                    },
                    "instead": {"type": "string", "description": "What to do instead. Concrete."},
                    "evidence": {
                        "type": "string",
                        "description": "Why this is worth changing: her profile, a rated technique, or plain practicality. Name which. Do not overstate.",
                    },
                },
                "required": ["problem", "quote", "instead", "evidence"],
                "additionalProperties": False,
            },
        },
        "rewrite": {
            "type": "string",
            "description": "Take ONE short passage of her notes and rewrite it in the better form, as markdown. This is the most useful part of the whole critique - make it a table or an arrow chain, and keep it to what her passage actually said.",
        },
        "rewrite_covers": {
            "type": "string",
            "description": "Which part of her notes the rewrite is based on.",
        },
        "one_habit": {
            "type": "string",
            "description": "The single change worth making next time. One sentence. Not a list.",
        },
        "retrieval_ready": {
            "type": "string",
            "description": "Could these notes be turned into questions as they stand? Say plainly yes or no and why - practice testing is the highest-utility technique there is, and notes that can't become questions can't be practised.",
        },
    },
    "required": ["verdict", "working", "problems", "rewrite", "rewrite_covers",
                 "one_habit", "retrieval_ready"],
    "additionalProperties": False,
}

CRITIQUE_PROMPT = """\
Critique these notes. Be direct and specific — vague encouragement wastes her
time, and she asked for this.

## What you are judging against

Her profile, which is in your system prompt, and the evidence base on study
technique. Use Dunlosky et al. (2013) ratings honestly:

  HIGH utility      practice testing, distributed practice
  MODERATE          elaborative interrogation, self-explanation, interleaving
  LOW               summarisation, highlighting, rereading, keyword mnemonics

Rules you must not break:

- Do NOT tell her to write by hand instead of typing. That finding has not
  replicated cleanly and you would be stating a contested result as fact.
- Do NOT say she is a "visual learner". Learning styles have no support. The
  reason to route her visually is a measured gap between her own scores.
- Do NOT invent a study or a statistic. If a claim is just practical common
  sense, say so — "practical" is an acceptable answer in `evidence`.
- Every `quote` must appear verbatim in her notes. If you cannot quote it, you
  cannot claim it.

## What matters most for her

Notes written live, in sentences, while listening, are the worst case: that
competes directly with a 4th-percentile auditory working memory. Notes rebuilt
afterwards, as tables and arrow chains, use the channel that works.

A list longer than about four items is past what she can hold. Grouping into
two or three named buckets of three is not tidying — it is what makes the
content usable at all.

## The measured facts about this text

{metrics}

Structural flags already computed:
{flags}

Use these numbers rather than re-estimating them, and do not contradict them.

## Her notes

---
{body}
---

The `rewrite` is the part she will actually use. Pick the worst-shaped passage,
and show her the same content as a table or an arrow chain. Do not add medical
content she did not write — this is about form, not about correcting her
medicine.
"""


def review(body: str, *, title: str = "", source: str = "paste",
           asset_id: str | None = None, want_critique: bool = True) -> dict:
    """Measure, then (optionally) critique. Measurement always works offline."""
    body = (body or "").strip()
    if not body:
        raise ValueError("Paste some notes first.")
    if len(body) > 40000:
        raise ValueError("That's very long — review one lecture's notes at a time.")

    rid = f"nr_{uuid.uuid4().hex[:8]}"
    m = measure(body)
    f = flags(m)

    db.run(
        "INSERT INTO note_review (id, ts, source, asset_id, title, body, metrics) "
        "VALUES (?,?,?,?,?,?,?)",
        rid, time.time(), source, asset_id, title.strip(), body, db.js(m),
    )

    result = {"id": rid, "metrics": m, "flags": f, "title": title,
              "critique": None, "critique_error": None}

    if want_critique:
        try:
            result["critique"] = critique(rid)
        except claude.NotConfigured as exc:
            # The measured half is genuinely useful on its own; losing it
            # because there's no API key would be the wrong failure.
            result["critique_error"] = str(exc)
        except Exception as exc:                       # noqa: BLE001
            result["critique_error"] = f"{type(exc).__name__}: {exc}"
    return result


def critique(rid: str) -> dict:
    row = db.q1("SELECT * FROM note_review WHERE id = ?", rid)
    if row is None:
        raise KeyError(f"no such review: {rid}")

    m = db.unjs(row["metrics"], {})
    f = flags(m)
    metric_lines = "\n".join(f"  {k}: {v}" for k, v in m.items())
    flag_lines = "\n".join(f"  - {x['flag']} ({x['severity']}): {x['says']}"
                           for x in f) or "  (none)"

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": CRITIQUE_PROMPT.format(
            metrics=metric_lines, flags=flag_lines, body=row["body"])}],
        schema=CRITIQUE_SCHEMA,
        max_tokens=8000,
        effort="high",
    )
    out = claude.json_of(msg)

    # A quote that isn't in her notes is a fabrication, and this critique's
    # whole credibility rests on being able to point at the actual text.
    haystack = " ".join(row["body"].split()).lower()
    for p in out.get("problems", []):
        q = " ".join((p.get("quote") or "").split()).lower()
        p["quote_verified"] = bool(q) and q in haystack

    db.run("UPDATE note_review SET critique = ? WHERE id = ?", db.js(out), rid)
    return out


def get(rid: str) -> dict:
    row = db.q1("SELECT * FROM note_review WHERE id = ?", rid)
    if row is None:
        raise KeyError(f"no such review: {rid}")
    d = dict(row)
    d["metrics"] = db.unjs(d["metrics"], {})
    d["critique"] = db.unjs(d["critique"], None) if d["critique"] else None
    d["flags"] = flags(d["metrics"])
    return d


def history(limit: int = 25) -> dict:
    rows = db.q(
        "SELECT id, ts, title, metrics, critique IS NOT NULL AS reviewed "
        "FROM note_review ORDER BY ts DESC LIMIT ?", limit)
    out = []
    for r in rows:
        m = db.unjs(r["metrics"], {})
        out.append({"id": r["id"], "ts": r["ts"], "title": r["title"],
                    "words": m.get("words", 0),
                    "words_per_line": m.get("words_per_line", 0),
                    "has_table": m.get("has_table", False),
                    "reviewed": bool(r["reviewed"])})

    # Is her note-taking actually changing? Words-per-line is the cleanest
    # single proxy for over-writing, and it is hers to compare against herself.
    trend = None
    if len(out) >= 4:
        recent = [r["words_per_line"] for r in out[:3] if r["words_per_line"]]
        older = [r["words_per_line"] for r in out[-3:] if r["words_per_line"]]
        if recent and older:
            a, b = sum(recent) / len(recent), sum(older) / len(older)
            trend = {
                "recent": round(a, 1), "earlier": round(b, 1),
                "direction": "tighter" if a < b - 1 else "looser" if a > b + 1 else "steady",
            }
    return {"reviews": out, "trend": trend}


def delete(rid: str) -> None:
    db.run("DELETE FROM note_review WHERE id = ?", rid)


# ------------------------------------------------- reading from a document

def text_from_file(path: Path, filename: str = "") -> str:
    """Pull note text out of a document, offline where possible.

    Reuses the extractors the course-material pipeline already has, so a .docx
    of her notes is read exactly the way a .docx of a lecture is.
    """
    from . import ingest

    name = filename or path.name
    ext = Path(name).suffix.lower()

    if ext in ingest.DOCX_EXT:
        return ingest._extract_docx(path)
    if ext in ingest.PPTX_EXT:
        return ingest._extract_pptx(path)
    if ext in ingest.TEXT_EXT:
        return ingest._extract_plain(path)
    if ext == ".pdf":
        try:
            from pypdf import PdfReader

            pages = [(pg.extract_text() or "") for pg in PdfReader(str(path)).pages]
            text = "\n\n".join(pages).strip()
        except Exception as exc:                      # noqa: BLE001
            raise ValueError(f"Couldn't read that PDF: {exc}")
        if not text:
            raise ValueError(
                "That PDF has no text layer - it's probably a scan. Put it in "
                "the vault and use 'Read it' there, which reads images.")
        return text
    if ext in ingest.IMAGE_EXT:
        raise ValueError(
            "That's an image. Photos of handwritten notes go in the vault, "
            "where 'Read it' can read them.")
    raise ValueError(f"Can't read {ext or 'that file type'} as notes.")


def from_asset(asset_id: str, *, want_critique: bool = True) -> dict:
    """Review a document already sitting in the vault."""
    from . import vault

    row = db.q1("SELECT filename, caption FROM asset WHERE id = ?", asset_id)
    if row is None:
        raise KeyError(f"no such file: {asset_id}")

    path = vault.file_path(asset_id)
    if not path.exists():
        raise ValueError("That file is missing from disk.")

    body = text_from_file(path, row["filename"])
    return review(body, title=row["caption"] or row["filename"],
                  source="asset", asset_id=asset_id, want_critique=want_critique)


def reviewable_assets() -> list[dict]:
    """Vault files that can be read as notes, with why not where they can't."""
    from . import ingest

    readable = ingest.DOCX_EXT | ingest.PPTX_EXT | ingest.TEXT_EXT | {".pdf"}
    out = []
    for r in db.q("SELECT id, filename, caption, kind, added_at FROM asset "
                  "ORDER BY added_at DESC LIMIT 60"):
        ext = Path(r["filename"]).suffix.lower()
        out.append({
            "id": r["id"], "filename": r["filename"],
            "caption": r["caption"], "kind": r["kind"], "added_at": r["added_at"],
            "readable": ext in readable,
            "reason": None if ext in readable
                      else ("Image - use 'Read it' in the vault instead"
                            if ext in ingest.IMAGE_EXT else f"{ext} isn't readable as text"),
        })
    return out
