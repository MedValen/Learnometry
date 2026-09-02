"""
Pre-reading: Adler's inspectional level, applied to a DLA or a lecture.

Mortimer Adler's *How to Read a Book* separates four levels. The second,
INSPECTIONAL reading, is the one this implements: a systematic skim whose
purpose is to find out what the material is, how it is organised, and what
questions it answers - BEFORE reading it properly. Adler's point is that
skipping this step makes the analytical read slower, not faster, because you
spend it building the map you could have had in ten minutes.

That fits this app's constraints almost exactly. A learner with low auditory
working memory cannot hold structure in mind while also decoding detail; the
orientation table this app already puts in front of every concept set is, in
Adler's terms, the product of an inspectional read. So this is not a new idea
bolted on - it is the same idea, named, and applied one level up: to the whole
document rather than to a single concept.

What is taken from Adler, concretely:

  * CLASSIFY the work before reading it. Kind and subject, stated first.
  * State its UNITY in a single sentence. If that cannot be done, the material
    has not been understood yet.
  * Enumerate the MAJOR PARTS in order and relation - the structure, not a
    summary.
  * COME TO TERMS with the author: the words that carry the argument and must
    mean the same thing to reader and writer. This matters doubly here, since
    slow naming makes unfamiliar vocabulary expensive.
  * Identify the QUESTIONS the material is answering, which Adler frames as
    finding the problems the author is trying to solve.

What is deliberately NOT taken: Adler's third and fourth levels, analytical
and syntopical reading. Those are the actual studying, and the rest of this
app is that. A pre-read that tried to also teach the content would defeat its
own purpose, which is to be short.

The text is extracted locally and sent as text, not as a PDF through the Files
API - it is cheaper, it needs no file upload, and it works when no Files API
beta is enabled.
"""

from __future__ import annotations

from . import claude, learner_profile

# Roughly 40k characters keeps a long DLA inside a cheap single call. Adler
# would approve of the truncation: an inspectional read is explicitly NOT
# obliged to look at every page.
MAX_CHARS = 40_000

SCHEMA = {
    "type": "object",
    "properties": {
        "classify": {
            "type": "object",
            "description": "Adler's first rule: know what kind of thing you are reading before you read it.",
            "properties": {
                "kind": {"type": "string",
                         "description": "e.g. 'directed learning activity', 'lecture slides', 'review article'"},
                "subject": {"type": "string"},
                "purpose": {"type": "string",
                            "description": "What this document is FOR - what it is trying to make the reader able to do."},
            },
            "required": ["kind", "subject", "purpose"],
            "additionalProperties": False,
        },
        "unity": {
            "type": "string",
            "description": "Adler's rule of unity: the whole material in ONE sentence. Not a list. If it needs a list, it is not a unity.",
        },
        "parts": {
            "type": "array",
            "description": "The major parts in order, with how they relate. Structure, not summary. Aim for 3-7 - more than that is not a structure, it is a table of contents.",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "covers": {"type": "string", "description": "One line."},
                    "relation": {"type": "string",
                                 "description": "How this part relates to the others: sets up, contrasts with, applies, concludes."},
                    "where": {"type": "string", "description": "Page or slide range if identifiable, else empty."},
                },
                "required": ["name", "covers", "relation", "where"],
                "additionalProperties": False,
            },
        },
        "terms": {
            "type": "array",
            "description": "Adler's 'coming to terms': the words that carry the argument, which the reader must understand the same way the author does. Include only words whose meaning is technical or load-bearing here - not general vocabulary.",
            "items": {
                "type": "object",
                "properties": {
                    "term": {"type": "string"},
                    "plain": {"type": "string", "description": "In ordinary words, one line."},
                    "matters": {"type": "string", "description": "Why the argument depends on it."},
                },
                "required": ["term", "plain", "matters"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "description": "The questions this material answers - Adler's 'what problems is the author trying to solve'. Phrase them as questions a reader would actually ask.",
            "items": {"type": "string"},
        },
        "orientation_table": {
            "type": "string",
            "description": "A GitHub-flavored markdown table giving the whole document at a glance. This is the single thing to look at before reading.",
        },
        "read_closely": {
            "type": "array",
            "description": "The parts that repay a slow, analytical read, and why.",
            "items": {"type": "string"},
        },
        "skim": {
            "type": "array",
            "description": "Parts that can be read fast, and why. Be honest - saying everything is essential is useless advice.",
            "items": {"type": "string"},
        },
        "assumed": {
            "type": "array",
            "description": "Prior knowledge the material takes for granted. If a reader lacks these, the document will not make sense and that is not their fault.",
            "items": {"type": "string"},
        },
        "minutes": {
            "type": "object",
            "properties": {
                "inspect": {"type": "integer", "description": "Minutes for the skim this describes."},
                "close_read": {"type": "integer", "description": "Realistic minutes for the full analytical read."},
            },
            "required": ["inspect", "close_read"],
            "additionalProperties": False,
        },
        "flags": {
            "type": "array",
            "description": "Anything unclear, internally inconsistent, or that appears to be missing because it lived in an image. Do not invent content to fill a gap.",
            "items": {"type": "string"},
        },
    },
    "required": ["classify", "unity", "parts", "terms", "questions",
                 "orientation_table", "read_closely", "skim", "assumed",
                 "minutes", "flags"],
    "additionalProperties": False,
}

PROMPT = """You are performing an INSPECTIONAL READ in Mortimer Adler's sense,
from *How to Read a Book*: a systematic skim to establish what this material
is, how it is put together, and what questions it answers - so that the real
read afterwards is faster and better aimed.

Follow Adler's rules in this order:

1. CLASSIFY the material before anything else. What kind of thing is it, on
   what subject, and what is it FOR?
2. State its UNITY in a single sentence. If you cannot, you have not grasped
   it yet - work at the sentence until it is true and specific. "It covers
   several topics" is a failure, not an answer.
3. Enumerate the MAJOR PARTS in order, and say how each relates to the others.
   This is an outline of structure, not a summary of content.
4. COME TO TERMS with the author: identify the words that carry the argument
   and would cause a misreading if taken in their everyday sense.
5. Identify the QUESTIONS the material is answering - the problems its author
   set out to solve.

Then, going beyond Adler because this is study material rather than a book:
say what repays a close read, what can be skimmed, and what prior knowledge is
assumed. Be honest about the skim list. Telling a reader that everything is
essential is the same as telling them nothing.

Do NOT teach the content. This is a map, not the territory - the analytical
read comes later and is not your job here. Keep every entry short.

If the extracted text is thin or garbled in places, say so in `flags` rather
than inventing content to cover the gap.

--- MATERIAL ---
{text}
--- END MATERIAL ---
"""


def run(text: str, *, title: str = "") -> dict:
    """Inspectional read of already-extracted text. One cheap call."""
    body = (text or "").strip()
    if not body:
        raise ValueError(
            "No text could be extracted from that file, so there is nothing to "
            "pre-read. A slide deck of scanned images will do this.")

    truncated = len(body) > MAX_CHARS
    if truncated:
        body = body[:MAX_CHARS]

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": [
            {"type": "text",
             "text": PROMPT.format(text=body) +
                     (f"\n\nTitle: {title}" if title else "")},
        ]}],
        schema=SCHEMA,
        max_tokens=8000,
        effort="medium",
        task="preread",
    )
    out = claude.json_of(msg)
    out["truncated"] = truncated
    out["title"] = title
    out["usage"] = claude.usage_of(msg)
    if truncated:
        out.setdefault("flags", []).append(
            f"Only the first {MAX_CHARS:,} characters were read. An "
            "inspectional read does not require every page, but a part late in "
            "a very long document may be under-represented here.")
    return out


def as_markdown(d: dict) -> str:
    """The pre-read as a file worth keeping.

    Built from the payload already in hand rather than by re-running the read -
    downloading something should never cost another API call.
    """
    L: list[str] = []
    add = L.append
    c = d.get("classify", {})

    add(f"# Pre-read: {d.get('title') or 'material'}")
    add("")
    add(f"*{c.get('kind', '')} - {c.get('subject', '')}*")
    add("")
    add(f"{c.get('purpose', '')}")
    add("")
    m = d.get("minutes", {})
    add(f"**{m.get('inspect', '?')} min skim - {m.get('close_read', '?')} min to "
        "read properly**")
    add("")
    add("> An inspectional read in Mortimer Adler's sense: what this is and how")
    add("> it is built, so the real read is aimed. It does not teach the content.")
    add("")
    add("## In one sentence")
    add("")
    add(d.get("unity", ""))
    add("")
    add("## The whole thing at a glance")
    add("")
    add(d.get("orientation_table", ""))
    add("")
    add("## How it is built")
    add("")
    for i, p_ in enumerate(d.get("parts", []), 1):
        where = f" ({p_['where']})" if p_.get("where") else ""
        add(f"{i}. **{p_.get('name', '')}**{where} - {p_.get('covers', '')}")
        add(f"   - *{p_.get('relation', '')}*")
    add("")
    add("## Come to terms first")
    add("")
    add("| Term | In plain words | Why it matters |")
    add("|---|---|---|")
    for t in d.get("terms", []):
        add(f"| **{t.get('term','')}** | {t.get('plain','')} | {t.get('matters','')} |")
    add("")
    for heading, key in (("Questions this answers", "questions"),
                         ("Read closely", "read_closely"),
                         ("Safe to skim", "skim"),
                         ("Assumes you already know", "assumed"),
                         ("Flags", "flags")):
        items = d.get(key) or []
        if not items:
            continue
        add(f"## {heading}")
        add("")
        for i in items:
            add(f"- {i}")
        add("")
    add("---")
    add("")
    add("*Generated by Learnometry. Method after Mortimer J. Adler, "
        "*How to Read a Book*, level 2: inspectional reading.*")
    return "\n".join(L) + "\n"
