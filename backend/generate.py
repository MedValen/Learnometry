"""
The two generation passes.

Pass 1  analyze()   -> concept map + the *derived* question count
Pass 2  questions() -> items for a batch of concepts

Splitting them is what makes "the necessary amount of questions" a real number
instead of a guess: the model first inventories what is actually testable in the
uploaded material and tags each concept's yield, then the count falls out of a
fixed coverage rule (below). She sees the arithmetic and can override it.
"""

from __future__ import annotations

from . import claude
from .ingest import Source
from . import learner_profile

# Coverage rule -> how many items each concept earns.
# high yield gets the full retrieval ladder; low yield gets one recognition item.
COVERAGE = {"high": 3, "medium": 2, "low": 1}

BATCH_SIZE = 5  # concepts per generation call

# Depth of Knowledge. The `difficulty` field on a question IS its DOK level.
DOK_LABELS = {
    1: "Recall",
    2: "Skills & Concepts",
    3: "Strategic Thinking",
    4: "Extended Thinking",
}

# Her exams sit at DOK 3-4, so a set that never gets there has not prepared her
# for them however many questions it contains. DOK 1-2 items are not filler -
# they are the rungs that make a DOK 3 item reachable on a concept she has not
# met - but they are the approach, not the destination.
DOK_TARGET_HIGH = 0.50      # share of a set that should be DOK 3 or 4

QUESTION_TYPES = [
    "recognition",      # MCQ. Lowest retrieval demand - the ladder's first rung.
    "cued_recall",      # Produce the term with a category/first-letter cue.
    "discrimination",   # Two look-alikes side by side. Plays to set-shifting.
    "application",      # Short vignette -> reasoning. Plays to fluid reasoning.
    "visual_map",       # Complete a table / place an item on a map. Plays to visual WM.
]


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------

ANALYSIS_SCHEMA = {
    "type": "object",
    "properties": {
        "title": {"type": "string"},
        "subject_area": {"type": "string"},
        "overview": {
            "type": "string",
            "description": "3-5 short lines, one idea per line, on what this material covers.",
        },
        "orientation_table": {
            "type": "string",
            "description": "A GitHub-flavored markdown table giving the whole topic at a glance. This is the single page she looks at before anything else.",
        },
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "name": {"type": "string"},
                    "one_line": {"type": "string"},
                    "yield": {"type": "string", "enum": ["high", "medium", "low"]},
                    "load_risk": {
                        "type": "string",
                        "description": "Why this concept is heavy for a 4th-percentile auditory working memory (e.g. 'a 7-item list', 'three interacting variables'), and the chunking you used to fix it.",
                    },
                    "confusable_with": {"type": "string"},
                },
                "required": ["id", "name", "one_line", "yield", "load_risk", "confusable_with"],
                "additionalProperties": False,
            },
        },
        "objectives": {
            "type": "array",
            "description": (
                "The lecture's stated learning objectives, copied VERBATIM - "
                "these are what the exam is written from, so paraphrasing them "
                "loses the thing that makes them useful. Include the "
                "institutional code when the slide carries one. Empty array only "
                "if the material genuinely states none."
            ),
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string",
                           "description": "Short local id used by questions, e.g. 'o1'."},
                    "code": {"type": "string",
                             "description": "The institutional code if present, e.g. 'SOM-MKII.PCM1.3.FTCM.16.MICR.8'. Empty string if none."},
                    "text": {"type": "string",
                             "description": "The objective as written, verbatim."},
                },
                "required": ["id", "code", "text"],
                "additionalProperties": False,
            },
        },
        "count_rationale": {"type": "string"},
        "flags": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Anything unclear, conflicting with standard teaching, or missing from the material.",
        },
    },
    "required": ["title", "subject_area", "overview", "orientation_table",
                 "concepts", "objectives", "count_rationale", "flags"],
    "additionalProperties": False,
}

QUESTIONS_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "concept_id": {"type": "string"},
                    "type": {"type": "string", "enum": QUESTION_TYPES},
                    "stem": {
                        "type": "string",
                        "description": "Self-contained. Every premise needed to answer is restated here or in premise_table. Never refers back to an earlier question.",
                    },
                    "premise_table": {
                        "type": ["string", "null"],
                        "description": "Markdown table holding any facts/values the question depends on, so nothing has to be held in mind. Null only if the stem has no more than two premises.",
                    },
                    "options": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "text": {"type": "string"},
                                "correct": {"type": "boolean"},
                                "why": {
                                    "type": "string",
                                    "description": "For a wrong option: the specific misconception it represents, and the one feature that rules it out.",
                                },
                            },
                            "required": ["label", "text", "correct", "why"],
                            "additionalProperties": False,
                        },
                        "description": "4-5 options for recognition/discrimination/application. Empty array for cued_recall and visual_map.",
                    },
                    "answer_text": {
                        "type": ["string", "null"],
                        "description": "The typed answer for cued_recall / visual_map. Null for MCQ types.",
                    },
                    "accepted_answers": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Other spellings/synonyms counted correct. Be generous - word-finding speed is never what is being tested.",
                    },
                    "cue": {
                        "type": "string",
                        "description": "Rung 2 of the retrieval ladder: a category or first-letter hint that narrows without giving it away.",
                    },
                    "why_right": {"type": "string"},
                    "derive_from": {
                        "type": "string",
                        "description": "The mechanism that lets her REBUILD this answer instead of storing it.",
                    },
                    "visual": {
                        "type": "string",
                        "description": "REQUIRED. A GitHub-flavored markdown table, an ASCII arrow chain (A -> B -> C), or a short indented tree. No mermaid, no image links.",
                    },
                    "memory_hook": {
                        "type": "string",
                        "description": "Visual or spatial only. No rhymes, no mnemonics longer than 3 letters.",
                    },
                    "key_clue": {
                        "type": "string",
                        "description": "The single phrase in the stem that gives it away, quoted. What she should have noticed.",
                    },
                    "takeaway": {
                        "type": "string",
                        "description": "The one high-yield line worth carrying out of this item. Two sentences maximum.",
                    },
                    "objective_ids": {
                        "type": "array",
                        "description": (
                            "Which stated objective(s) this question tests, by "
                            "the analysis's objective ids. An exam is written "
                            "from the objectives, so a question that maps to "
                            "none is a question the exam probably will not ask. "
                            "Empty array only when the material states no "
                            "objectives at all."
                        ),
                        "items": {"type": "string"},
                    },
                    "source_ref": {"type": "string"},
                    "difficulty": {
                        "type": "integer",
                        "enum": [1, 2, 3, 4],
                        "description": (
                            "Depth of Knowledge (DOK), tracked SEPARATELY from mastery. "
                            "DOK 1 = Recall: a fact, definition, or single lookup. "
                            "DOK 2 = Skills/Concepts: compare, interpret, or apply one "
                            "concept to a scenario. "
                            "DOK 3 = Strategic Thinking: multi-step reasoning, "
                            "discriminating between plausible answers, justifying a "
                            "choice from several pieces of information. "
                            "DOK 4 = Extended Thinking: synthesis across systems or "
                            "topics, or a problem that needs several linked inferences. "
                            "HER EXAMS ARE DOK 3 AND 4. A set that is mostly DOK 1-2 "
                            "has not prepared her for them. Aim for at least half the "
                            "set at DOK 3 or above, using DOK 1-2 only as the rungs "
                            "that make a DOK 3 item reachable for a given concept."
                        ),
                    },
                },
                "required": ["id", "concept_id", "type", "stem", "premise_table",
                             "options", "answer_text", "accepted_answers", "cue",
                             "why_right", "derive_from", "visual", "memory_hook",
                             "key_clue", "takeaway", "objective_ids", "source_ref",
                             "difficulty"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["questions"],
    "additionalProperties": False,
}

SHEET_SCHEMA = {
    "type": "object",
    "properties": {
        "markdown": {
            "type": "string",
            "description": "The whole one-page sheet as GitHub-flavored markdown. Tables only, no prose paragraphs.",
        },
    },
    "required": ["markdown"],
    "additionalProperties": False,
}


# ---------------------------------------------------------------------------
# Pass 1: analyze
# ---------------------------------------------------------------------------

ANALYZE_PROMPT = """\
Read the attached course material and build a concept inventory for it.

A "concept" is one discrete testable idea - the size of a single exam item, not
a whole lecture. Split anything bigger. For a typical 40-60 slide lecture expect
somewhere between 12 and 30 concepts; do not pad and do not compress. Only
include what the uploaded material actually covers.

For each concept:
- `yield`: how heavily this is tested on USMLE Step 1 / Step 2 CK. Be honest -
  most material is medium, and a lecture usually has only a handful of highs.
- `load_risk`: name the working-memory trap in this concept for the profile
  described above, and state the chunking you would use instead. If there is no
  trap, say "low - fits in 2-3 elements".
- `confusable_with`: the thing this is most likely to be mixed up with. Say
  "none" only if there genuinely is nothing.

Also write:
- `orientation_table`: ONE markdown table that puts the entire topic on a single
  screen. It is the first thing looked at, and wherever visual working memory
  outruns auditory working memory it is the highest-value artifact in the whole
  app. Choose columns that make the contrasts visible. Aim for 6-14 rows.
- `count_rationale`: two or three sentences on how many questions this material
  warrants and why, given that high-yield concepts get 3 items, medium 2, and
  low 1.
- `flags`: anything ambiguous, internally contradictory, at odds with standard
  teaching, or conspicuously missing.
"""


def analyze(sources: list[Source]) -> dict:
    content: list[dict] = []
    for s in sources:
        content.extend(s.as_content_blocks())
    content.append({"type": "text", "text": ANALYZE_PROMPT})

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": content}],
        schema=ANALYSIS_SCHEMA,
        max_tokens=24000,
        effort="high",
    )
    data = claude.json_of(msg)
    data["planned_counts"] = plan_counts(data["concepts"])
    data["usage"] = claude.usage_of(msg)
    return data


def plan_counts(concepts: list[dict]) -> dict:
    """The derived question count. This is 'the necessary amount'."""
    by_yield = {"high": 0, "medium": 0, "low": 0}
    for c in concepts:
        by_yield[c.get("yield", "medium")] += 1
    total = sum(by_yield[y] * COVERAGE[y] for y in by_yield)
    return {
        "by_yield": by_yield,
        "coverage_rule": COVERAGE,
        "total": total,
        "breakdown": (
            f"{by_yield['high']} high x3 + {by_yield['medium']} medium x2 + "
            f"{by_yield['low']} low x1 = {total} questions"
        ),
    }


# ---------------------------------------------------------------------------
# Pass 2: questions
# ---------------------------------------------------------------------------

QUESTIONS_PROMPT = """\
Write exam questions for exactly these concepts from the attached material, and
no others.

{concept_block}

Item budget for this batch: {budget}. Distribute it across the listed concepts
in proportion to their yield (high = 3, medium = 2, low = 1). Hit the budget
exactly.

## Which type to use

Where a concept gets more than one item, walk the retrieval ladder rather than
asking the same thing twice:

  rung 1  `recognition`     - she picks it out. Lowest word-finding demand.
  rung 2  `cued_recall`     - she produces it, with a cue available.
  rung 3  `application`     - short vignette, reason to the answer.

Use `discrimination` whenever `confusable_with` is not "none" - two look-alikes
in one table, one feature separating them. Where set-shifting is a strength
these are both easier and higher yield. Use `visual_map` where the concept is
genuinely spatial or tabular - the student completes a cell in a table you
provide.

## Non-negotiables for every item

1. `stem` is self-contained. It never says "in the case above" or "from the
   previous question". Where immediate verbal registration is low, anything
   that has to be held in mind is a question failed for the wrong reason.
2. Any item with more than two premises MUST put them in `premise_table`. Lab
   values, drug lists, timelines, patient parameters - into the table, on the
   screen, where they can be looked at.
3. Never more than 4-5 options and never an option longer than one line.
4. `visual` is required and must be genuinely useful - the thing a student
   would redraw from memory. Markdown table, ASCII arrow chain, or indented
   tree.
5. `why` on EVERY option, right and wrong. For wrong options, name the specific
   misconception and the one feature that rules it out. This is where most of
   the learning happens.
6. `derive_from` must let the answer be rebuilt from mechanism rather than
   recalled. Derivation survives a bad night; a memorised list does not.
7. `memory_hook` is visual or spatial. No rhymes. No mnemonic longer than three
   letters.
8. `accepted_answers` for typed items should be generous - accept synonyms,
   British spellings, abbreviations, and near-misses. Word-finding speed is
   never the thing being tested.
9. Board-level difficulty. Do not soften the medicine.

## Difficulty spread - required

`difficulty` is the cognitive level and is tracked separately from how well she
knows the concept. She can know Level 1 facts cold and still fail Level 3, and
the whole point of measuring them apart is to catch that.

Where a concept gets 2 or more items, the set MUST span at least two levels.
Never write three Level 1 items for the same concept - a concept practiced only
at Level 1 cannot register as mastered, and that is deliberate.

Reserve Level 4 for genuine cross-system integration. When you write one, the
3-4 element ceiling still applies: put every premise in `premise_table`.
"""


def questions(sources: list[Source], concepts: list[dict], budget: int) -> list[dict]:
    lines = []
    for c in concepts:
        lines.append(
            f"- id={c['id']} | {c['name']} | yield={c.get('yield','medium')}\n"
            f"    what: {c.get('one_line','')}\n"
            f"    load risk: {c.get('load_risk','')}\n"
            f"    confusable with: {c.get('confusable_with','none')}"
        )
    prompt = QUESTIONS_PROMPT.format(
        concept_block="\n".join(lines), budget=budget
    )

    content: list[dict] = []
    for s in sources:
        content.extend(s.as_content_blocks())
    content.append({"type": "text", "text": prompt})

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": content}],
        schema=QUESTIONS_SCHEMA,
        max_tokens=48000,
        effort="high",
    )
    return claude.json_of(msg)["questions"]


def batches(concepts: list[dict], target_total: int) -> list[tuple[list[dict], int]]:
    """Split concepts into generation batches with a per-batch item budget."""
    weights = [COVERAGE[c.get("yield", "medium")] for c in concepts]
    total_weight = sum(weights) or 1

    out: list[tuple[list[dict], int]] = []
    assigned = 0
    for i in range(0, len(concepts), BATCH_SIZE):
        chunk = concepts[i:i + BATCH_SIZE]
        chunk_weight = sum(COVERAGE[c.get("yield", "medium")] for c in chunk)
        is_last = i + BATCH_SIZE >= len(concepts)
        if is_last:
            budget = max(1, target_total - assigned)
        else:
            budget = max(1, round(target_total * chunk_weight / total_weight))
        assigned += budget
        out.append((chunk, budget))
    return out


# ---------------------------------------------------------------------------
# Study sheet
# ---------------------------------------------------------------------------

SHEET_PROMPT = """\
Build the one-page visual study sheet for this material.

Hard constraints:
- Tables and arrow chains only. No paragraphs of prose anywhere.
- It must fit on one screen she can keep open while doing questions.
- Lead with the single table that carries the most contrast.
- Group every list into named buckets of 2-3. Never leave a bare list of five.
- End with a short "most confusable pairs" table.

This sheet is the externalised working memory for the whole topic. What is on
the page is what can actually be used while working, so put the load here
rather than asking for it to be held in mind.
"""


def study_sheet(sources: list[Source], focus: str | None = None) -> str:
    prompt = SHEET_PROMPT
    if focus:
        prompt += f"\n\nNarrow the sheet to this focus: {focus}"

    content: list[dict] = []
    for s in sources:
        content.extend(s.as_content_blocks())
    content.append({"type": "text", "text": prompt})

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": content}],
        schema=SHEET_SCHEMA,
        max_tokens=16000,
        effort="high",
    )
    return claude.json_of(msg)["markdown"]


# ---------------------------------------------------------------------------
# Post-quiz coaching
# ---------------------------------------------------------------------------

REVIEW_SCHEMA = {
    "type": "object",
    "properties": {
        "verdict": {"type": "string"},
        "patterns": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string"},
                    "evidence": {"type": "string"},
                    "fix": {"type": "string"},
                },
                "required": ["pattern", "evidence", "fix"],
                "additionalProperties": False,
            },
        },
        "next_session": {"type": "string"},
        "repair_table": {"type": "string"},
    },
    "required": ["verdict", "patterns", "next_session", "repair_table"],
    "additionalProperties": False,
}


def review(results: list[dict]) -> dict:
    lines = []
    for r in results:
        mark = "correct" if r["correct"] else "MISSED"
        lines.append(
            f"[{mark}] ({r['type']}, difficulty {r['difficulty']}) "
            f"{r['concept_id']}: {r['stem'][:160]}\n"
            f"    she answered: {r.get('given', '(blank)')}\n"
            f"    used cue: {r.get('used_cue', False)}"
        )

    prompt = (
        "Here is how the session went. Find the PATTERN, not the score.\n\n"
        + "\n".join(lines)
        + "\n\n"
        "Separate three different failure modes, because they need different "
        "fixes and they look identical on a score report:\n"
        "  (a) she did not know the content;\n"
        "  (b) she knew it but the item overloaded working memory - long stem, "
        "several premises, a list to hold;\n"
        "  (c) she knew it but could not produce the word (used the cue, or "
        "answered with a near-synonym).\n\n"
        "Only (a) means studying it again. (b) means restructure the material. "
        "(c) means she actually knows it - say so plainly, because a raw score "
        "will make her think otherwise, and that misreading is the single most "
        "demoralizing thing about this profile.\n\n"
        "`repair_table` is a markdown table: what to redo, why, and in what form."
    )

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": prompt}],
        schema=REVIEW_SCHEMA,
        max_tokens=12000,
        effort="high",
    )
    return claude.json_of(msg)
