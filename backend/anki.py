"""
Anki export.

The point is not to dump her question bank into Anki. A multiple-choice item
makes a bad flashcard - the options do the remembering for you, which is exactly
the cue-dependence that makes recognition feel like knowledge. What goes to Anki
is the *concept*, turned into an active-recall prompt.

Three card shapes, chosen per concept rather than uniformly:

  BASIC     front asks, back answers. The default.
  CLOZE     a sentence with the load-bearing term blanked. Good for facts that
            only make sense in context.
  CLINICAL  a two-line vignette to a one-line answer. For concepts she can
            recite but cannot apply - the difficulty gap the mastery model
            already measures.

Cards are generated with Claude when a key is present, and there is an offline
fallback that builds honest basic cards from what the bank already holds, so an
export is never blocked on the network.

TSV, tab-separated, with a header row Anki can map. Fields follow the spec:
Front, Back, Topic, Subtopic, Tags, Difficulty, HighYield, Source,
MasteryAtExport.
"""

from __future__ import annotations

import csv
import io
import time
import uuid

from . import bank, claude, db, mastery as mastery_math, scope as scope_mod
from . import learner_profile

FIELDS = ["Front", "Back", "Topic", "Subtopic", "Tags", "Difficulty",
          "HighYield", "Source", "MasteryAtExport"]

CARD_KINDS = ["basic", "cloze", "clinical"]

SELECTIONS = {
    "red": "Red only — the weakest concepts",
    "red_orange": "Red and orange — everything below developing",
    "today_wrong": "Everything you got wrong today",
    "high_yield_weak": "High-yield weaknesses",
    "selected": "Specific concepts you pick",
}


# ------------------------------------------------------------- selection

def pick(selection: str, *, limit: int = 60, concept_ids: list[str] | None = None,
         scope: scope_mod.Scope | None = None) -> list[dict]:
    """Which concepts to export, by the named selection."""
    allowed = scope_mod.allowed(scope) if scope is not None else None

    rows = db.q(
        "SELECT c.id, c.name, c.one_line, c.topic_id, c.hy_tier, t.path, "
        "       MIN(1.0, c.high_yield + COALESCE(c.emphasis_boost, 0)) AS high_yield "
        "FROM concept c JOIN topic t ON t.id = c.topic_id WHERE c.retired = 0")

    today_cutoff = time.time() - 24 * 3600
    wrong_today = {r["concept_id"] for r in db.q(
        "SELECT DISTINCT concept_id FROM attempt WHERE correct = 0 AND ts > ?",
        today_cutoff)}

    out = []
    for r in rows:
        if allowed is not None and r["id"] not in allowed:
            continue
        if concept_ids and r["id"] not in concept_ids:
            continue

        m = bank.current(r["id"])
        band = m.band
        keep = False
        if selection == "selected":
            keep = bool(concept_ids)
        elif selection == "red":
            keep = band == "red" and m.attempts > 0
        elif selection == "red_orange":
            keep = band in ("red", "orange") and m.attempts > 0
        elif selection == "today_wrong":
            keep = r["id"] in wrong_today
        elif selection == "high_yield_weak":
            keep = r["high_yield"] >= 0.7 and m.effective < 0.65 and m.attempts > 0
        if not keep:
            continue

        parts = (r["path"] or "").split(" / ")
        out.append({
            "concept_id": r["id"], "name": r["name"],
            "one_line": r["one_line"] or "",
            "topic": parts[0] if parts else "", "subtopic": parts[1] if len(parts) > 1 else "",
            "topic_id": r["topic_id"], "hy_tier": r["hy_tier"],
            "high_yield": round(r["high_yield"], 2),
            "mastery": round(m.effective, 3), "band": band,
            "attempts": m.attempts,
            "difficulty_gap": round(mastery_math.difficulty_gap(m), 3),
        })

    out.sort(key=lambda c: (c["mastery"], -c["high_yield"]))
    return out[:limit]


def preview_counts(scope: scope_mod.Scope | None = None) -> dict:
    """How many concepts each selection would export. Cheap enough to show live."""
    return {key: len(pick(key, limit=9999, scope=scope))
            for key in SELECTIONS if key != "selected"}


# ---------------------------------------------------------- card building

CARDS_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "concept_id": {"type": "string"},
                    "kind": {"type": "string", "enum": CARD_KINDS},
                    "front": {
                        "type": "string",
                        "description": "The prompt. For cloze, the full sentence with the target wrapped as {{c1::term}}.",
                    },
                    "back": {
                        "type": "string",
                        "description": "The answer, plus one short line of why. Never more than three lines total.",
                    },
                    "tags": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Anki tags. Use :: for hierarchy, no spaces inside a tag.",
                    },
                },
                "required": ["concept_id", "kind", "front", "back", "tags"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["cards"],
    "additionalProperties": False,
}

CARDS_PROMPT = """\
Turn these weak concepts into Anki cards. One or two cards each — never more,
because a deck she will not finish is worse than a smaller one she will.

{concepts}

## Rules

- **Active recall, not recognition.** Never write a multiple-choice card. If the
  front can be answered by picking from a list, it is the wrong card.
- **One fact per card.** A card asking two things gets both wrong when she
  misses either.
- **The back is short.** The answer plus at most one line of why. She has to
  read it at 200 cards a day; a paragraph will not get read.
- Choose the shape per concept:
    `basic`    — a direct question. The default.
    `cloze`    — when the fact only makes sense inside a sentence. Wrap the
                 target as {{{{c1::term}}}}.
    `clinical` — a two-line vignette to a one-line answer. Use this where the
                 concept is marked with a difficulty gap, meaning she can recite
                 it but not apply it.
- Tags: hierarchical with `::`, no spaces. Start with `Learnometry::` then the
  topic path. Add `HighYield` where the concept is marked high or very high.

## For this student

Where auditory working memory is the narrow channel and visual working
memory is average. Where a card would otherwise be a list, make the back a small
markdown table instead. Never write a mnemonic longer than three letters — long
first-letter strings are precisely the format she cannot hold.
"""


def build_cards(concepts: list[dict]) -> list[dict]:
    """Generate cards with Claude. Falls back to offline basics on failure."""
    if not concepts:
        return []

    lines = []
    for c in concepts:
        gap = " [knows the fact, struggles to apply it]" if c["difficulty_gap"] > 0.2 else ""
        lines.append(
            f"- id={c['concept_id']} | {c['name']} | {c['topic']} / {c['subtopic']} | "
            f"mastery {c['mastery']:.0%} | {c['hy_tier']} yield{gap}\n"
            f"    what it is: {c['one_line'] or '(no description stored)'}")

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": CARDS_PROMPT.format(
            concepts="\n".join(lines))}],
        schema=CARDS_SCHEMA,
        max_tokens=16000,
        effort="high",
        task="anki_cards",
    )
    cards = claude.json_of(msg)["cards"]

    known = {c["concept_id"] for c in concepts}
    return [c for c in cards if c.get("concept_id") in known]


def offline_cards(concepts: list[dict]) -> list[dict]:
    """Honest basic cards from what the bank already holds.

    Deliberately plain. Without a model we know the concept's name, its
    one-liner, and where it sits - so the card asks for the name from the
    description. That is a real active-recall card, and it does not pretend to
    be more than it is.
    """
    out = []
    for c in concepts:
        if not c["one_line"]:
            continue
        out.append({
            "concept_id": c["concept_id"],
            "kind": "basic",
            "front": f"{c['topic']} — which concept is this?\n\n{c['one_line']}",
            "back": c["name"],
            "tags": _default_tags(c),
        })
    return out


def _default_tags(c: dict) -> list[str]:
    tags = ["Learnometry"]
    if c["topic"]:
        path = c["topic"].replace(" ", "")
        if c["subtopic"]:
            path += "::" + c["subtopic"].replace(" ", "")
        tags.append(f"Learnometry::{path}")
    if c["hy_tier"] in ("high", "very_high"):
        tags.append("HighYield")
    tags.append(f"Band::{c['band']}")
    return tags


# --------------------------------------------------------------- exporting

def to_tsv(cards: list[dict], concepts: list[dict]) -> str:
    """Anki-importable TSV with a header row."""
    by_id = {c["concept_id"]: c for c in concepts}
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter="\t", lineterminator="\n",
                        quoting=csv.QUOTE_MINIMAL)
    writer.writerow(FIELDS)

    for card in cards:
        c = by_id.get(card["concept_id"])
        if c is None:
            continue
        tags = card.get("tags") or _default_tags(c)
        writer.writerow([
            _flatten(card["front"]),
            _flatten(card["back"]),
            c["topic"],
            c["subtopic"],
            " ".join(t.replace(" ", "_") for t in tags),
            card.get("kind", "basic"),
            c["hy_tier"],
            "Learnometry",
            f"{c['mastery']:.0%}",
        ])
    return buf.getvalue()


def _flatten(text: str) -> str:
    """Anki reads a tab-separated line per card, so newlines become <br>."""
    return (text or "").replace("\t", " ").replace("\r\n", "\n").replace("\n", "<br>")


def export(
    selection: str,
    *,
    concept_ids: list[str] | None = None,
    limit: int = 60,
    scope: scope_mod.Scope | None = None,
    use_claude: bool = True,
) -> dict:
    concepts = pick(selection, limit=limit, concept_ids=concept_ids, scope=scope)
    if not concepts:
        raise ValueError(
            f"Nothing matches “{SELECTIONS.get(selection, selection)}”. "
            "Answer some questions first, or pick a wider selection.")

    generated, note = [], None
    if use_claude:
        try:
            generated = build_cards(concepts)
        except claude.NotConfigured as exc:
            note = f"{exc} Falling back to plain cards built from your bank."
        except Exception as exc:                       # noqa: BLE001
            note = (f"Card generation failed ({type(exc).__name__}). "
                    "Falling back to plain cards built from your bank.")

    if not generated:
        generated = offline_cards(concepts)
        if note is None and not use_claude:
            note = "Plain cards built offline from your concept descriptions."

    if not generated:
        raise ValueError(
            "Couldn't build any cards - these concepts have no descriptions "
            "stored, and there's no API key to write them.")

    eid = f"ank_{uuid.uuid4().hex[:8]}"
    return {
        "id": eid,
        "selection": selection,
        "label": SELECTIONS.get(selection, selection),
        "concepts": len(concepts),
        "cards": generated,
        "tsv": to_tsv(generated, concepts),
        "note": note,
        "filename": f"learnometry-{selection}-{time.strftime('%Y%m%d')}.tsv",
        "concept_list": concepts,
    }


def rebuild_tsv(cards: list[dict], concept_list: list[dict]) -> str:
    """Re-render after she edits the cards in the preview."""
    return to_tsv(cards, concept_list)
