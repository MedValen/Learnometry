"""
Reading the question: separating the ask from the padding.

NBME-style vignettes are long on purpose. Most of the length is context that
either narrows the differential or is there to be discarded, and the actual
question is almost always the last sentence. Reading top-to-bottom and trying to
hold the whole thing is the expensive way to do it - and it is especially
expensive at a 4th-percentile auditory working memory, because a long stem read
straight through has to be held while the options are considered.

The strategy below - read the ask first, then mine the stem for what answers it -
is standard test-taking advice, not a research finding, and the app says so. What
IS well supported is the underlying reason it helps her: reducing how much has to
be held at once.

`dissect()` runs offline on heuristics alone. `explain()` adds Claude when a key
is present.
"""

from __future__ import annotations

import re

from . import claude, db
from . import learner_profile

# Phrases that mark the actual question rather than the setup.
ASK_MARKERS = [
    "which of the following", "what is the most likely", "the most likely",
    "which one of the following", "most appropriate", "best explains",
    "most likely cause", "next best step", "most likely diagnosis",
    "is most likely", "would most likely", "best initial", "definitive",
]

# Numbers with units, ranges, or lab-shaped tokens: rarely decoration.
# Order matters: compound forms first, so a blood pressure is marked as one
# value rather than being chopped into "94 mm" with the systolic left bare.
VALUE_RE = re.compile(
    r"\b\d{2,3}\s*/\s*\d{2,3}\s*mm\s?Hg\b"                  # 158/94 mm Hg
    r"|\b\d{1,3}(?:\.\d+)?\s*°?\s?[CF]\b(?!\w)"             # 37.0 C, 98.6 F
    r"|\b\d+(?:\.\d+)?\s?(?:mg/dL|mmol/L|mEq/L|ng/mL|mmHg|mg|g|kg|mL|L|"
    r"%|bpm|/min|cm|mm|units?|IU|mcg|µg)\b",
    re.I)
AGE_RE = re.compile(r"\b(\d{1,3})[- ]?(?:year|yr|month|week|day)s?[- ]?old\b", re.I)
SEX_RE = re.compile(r"\b(man|woman|male|female|boy|girl|gentleman|lady)\b", re.I)

# Time is almost never padding in a vignette - acute vs chronic changes the answer.
TIME_RE = re.compile(
    r"\b(?:\d+\s*(?:minute|hour|day|week|month|year)s?|sudden(?:ly)?|acute(?:ly)?|"
    r"gradual(?:ly)?|chronic|intermittent|progressive|abrupt|for the past|"
    r"since|over the last)\b", re.I)

NEGATION_RE = re.compile(
    r"\b(?:not|except|least|unlikely|contraindicated|inappropriate|avoid)\b", re.I)

# Common openings that carry no discriminating information on their own.
FILLER_RE = re.compile(
    r"\b(?:comes to the (?:clinic|office|emergency department)|is brought to|"
    r"presents to|is evaluated|physical examination shows|on examination|"
    r"laboratory studies show|vital signs are|he is|she is|the patient is)\b", re.I)


def _sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+", (text or "").strip())
    return [p.strip() for p in parts if p.strip()]


def dissect(stem: str) -> dict:
    """Split a vignette into ask / signal / context. Heuristics only, no API.

    Deliberately conservative: when unsure, a sentence is called `context`
    rather than `filler`. Telling her to ignore a line that mattered is a much
    worse error than leaving one line unclassified.
    """
    sentences = _sentences(stem)
    if not sentences:
        return {"ask": "", "lines": [], "demographics": None, "negated": False,
                "counts": {}}

    # The ask is the last sentence carrying a question marker, else the last one.
    ask_index = len(sentences) - 1
    for i in range(len(sentences) - 1, -1, -1):
        low = sentences[i].lower()
        if "?" in sentences[i] or any(mk in low for mk in ASK_MARKERS):
            ask_index = i
            break

    ask = sentences[ask_index]
    negated = bool(NEGATION_RE.search(ask))

    lines = []
    for i, s in enumerate(sentences):
        if i == ask_index:
            lines.append({"text": s, "role": "ask", "marks": []})
            continue

        marks = []
        if AGE_RE.search(s) or SEX_RE.search(s):
            marks.append("who")
        if TIME_RE.search(s):
            marks.append("when")
        if VALUE_RE.search(s):
            marks.append("numbers")

        stripped = FILLER_RE.sub("", s).strip(" ,.;")
        informative = len(re.findall(r"[A-Za-z]+", stripped)) >= 4

        if marks:
            role = "signal"
        elif not informative:
            role = "filler"
        else:
            role = "context"
        lines.append({"text": s, "role": role, "marks": marks})

    demo = None
    age = AGE_RE.search(stem)
    sex = SEX_RE.search(stem)
    if age or sex:
        demo = " ".join(x for x in [age.group(0) if age else None,
                                    sex.group(1) if sex else None] if x)

    counts = {}
    for ln in lines:
        counts[ln["role"]] = counts.get(ln["role"], 0) + 1

    for ln in lines:
        ln["segments"] = segment(ln["text"])

    out = {
        "ask": ask,
        "ask_index": ask_index,
        "negated": negated,
        "demographics": demo,
        "lines": lines,
        "counts": counts,
        "values": VALUE_RE.findall(stem)[:12],
        "how_to_read": _reading_order(lines, ask, negated),
        "legend": [{"kind": k, "label": v} for k, v in SPAN_LABELS.items()],
    }
    out["advice"] = advise(out)
    return out


def _reading_order(lines, ask, negated) -> list[str]:
    """The order to actually read it in, generated from what was found."""
    steps = [f"Read the last line first — that's the real question: “{ask}”"]
    if negated:
        steps.append("⚠ This one is negated (not / except / least). You're "
                     "looking for the odd one out, not the best fit.")
    signal = [ln for ln in lines if ln["role"] == "signal"]
    if signal:
        steps.append(f"{len(signal)} line(s) carry who / when / numbers. Those "
                     "are what narrow it — read those next.")
    filler = [ln for ln in lines if ln["role"] == "filler"]
    if filler:
        steps.append(f"{len(filler)} line(s) look like setup with nothing "
                     "discriminating in them. Skim those.")
    steps.append("Answer in your head before you look at the options, so the "
                 "distractors can't pull you.")
    return steps


# ---------------------------------------------------- inline highlighting

# Findings usually follow one of these lead-ins, which is the only reliable
# offline way to spot them without a clinical lexicon.
FINDING_LEAD_RE = re.compile(
    r"(?:physical examination (?:shows|reveals|is notable for)|on examination|"
    r"examination shows|auscultation reveals|laboratory studies show|"
    r"laboratory results show|imaging shows|x-ray shows|ecg shows|"
    r"ct scan shows|mri shows|biopsy shows|urinalysis shows)[^.;]*",
    re.I)

HISTORY_RE = re.compile(
    r"(?:has a (?:history|past medical history) of|is being treated for|"
    r"takes|is taking|medications include|denies|reports a history of|"
    r"smokes|drinks|family history of)[^.;]*", re.I)

# Highest priority wins where spans overlap. Negation first: missing a NOT is
# the single most expensive misread there is.
SPAN_PRIORITY = ["negation", "value", "when", "who", "finding", "history", "fluff"]

SPAN_LABELS = {
    "negation": "flips the question",
    "value": "number - write it down",
    "when": "timing",
    "who": "who",
    "finding": "finding",
    "history": "background",
    "fluff": "skim",
}


def _spans_for(text: str) -> list[tuple[int, int, str]]:
    found: list[tuple[int, int, str]] = []
    for regex, kind in (
        (NEGATION_RE, "negation"),
        (VALUE_RE, "value"),
        (TIME_RE, "when"),
        (AGE_RE, "who"),
        (SEX_RE, "who"),
        (FINDING_LEAD_RE, "finding"),
        (HISTORY_RE, "history"),
        (FILLER_RE, "fluff"),
    ):
        for m in regex.finditer(text):
            found.append((m.start(), m.end(), kind))

    # Resolve overlaps by priority, then by length - a longer match of equal
    # priority carries more of the phrase and is the more useful highlight.
    found.sort(key=lambda x: (SPAN_PRIORITY.index(x[2]), -(x[1] - x[0])))
    kept: list[tuple[int, int, str]] = []
    for start, end, kind in found:
        if any(start < k_end and end > k_start for k_start, k_end, _ in kept):
            continue
        kept.append((start, end, kind))
    kept.sort(key=lambda x: x[0])
    return kept


def segment(text: str) -> list[dict]:
    """Split one line into marked and unmarked pieces, in order.

    The frontend just walks this and wraps the marked pieces - it never has to
    do any matching itself, so the highlighting and the classification can
    never disagree.
    """
    spans = _spans_for(text)
    out: list[dict] = []
    cursor = 0
    for start, end, kind in spans:
        if start > cursor:
            out.append({"text": text[cursor:start], "kind": None})
        out.append({"text": text[start:end], "kind": kind,
                    "label": SPAN_LABELS.get(kind, kind)})
        cursor = end
    if cursor < len(text):
        out.append({"text": text[cursor:], "kind": None})
    return out


def advise(d: dict) -> list[dict]:
    """Advice for THIS stem, derived from what was actually found in it.

    Everything here is conditional on the dissection - a stem with no numbers
    never gets told to write the numbers down, and a lean stem is not lectured
    about padding it doesn't have.
    """
    tips: list[dict] = []
    counts = d.get("counts", {})
    values = d.get("values", [])
    total_lines = len(d.get("lines", []))

    if d.get("negated"):
        tips.append({
            "kind": "warn",
            "text": "This one is negated. You're hunting the option that does "
                    "NOT fit — the three that look right are the wrong answers.",
        })

    if len(values) >= 3:
        tips.append({
            "kind": "act",
            "text": f"{len(values)} numbers in this stem. Put them in a column on "
                    f"paper before you reason. Holding them is the expensive "
                    f"part, and it's entirely avoidable with a pen.",
        })
    elif values:
        tips.append({
            "kind": "act",
            "text": f"Only {len(values)} number(s) here — this one turns on the "
                    "description more than the labs.",
        })
    else:
        tips.append({
            "kind": "note",
            "text": "No lab values at all. This is a pattern-recognition item, "
                    "not a calculation.",
        })

    if d.get("demographics"):
        tips.append({
            "kind": "note",
            "text": f"“{d['demographics']}” — age and sex narrow the differential "
                    "before you read a single symptom. Start there.",
        })

    signal = counts.get("signal", 0)
    filler = counts.get("filler", 0)
    if total_lines >= 4 and signal and signal <= total_lines / 2:
        tips.append({
            "kind": "note",
            "text": f"{total_lines} sentences, {signal} carrying signal. Most of "
                    "this stem is framing — length here is a time cost, not "
                    "difficulty.",
        })
    if filler:
        tips.append({
            "kind": "skip",
            "text": f"{filler} line(s) are standard setup phrasing with nothing "
                    "discriminating in them. Skim those.",
        })

    tips.append({
        "kind": "act",
        "text": "Answer from the stem before you look at the options. You can "
                "only resist a plausible wrong answer if you have committed to "
                "something first.",
    })
    return tips


# --------------------------------------------------------------- guidance

PLAYBOOK = [
    {
        "title": "Read the last line first",
        "body": "The stem is written to be read top-down, but the question is at "
                "the bottom. Reading the ask first turns the vignette from "
                "something you have to hold into something you can search.",
        "why_you": "This is the single biggest load reduction available to you. "
                   "You stop holding the whole case and start looking for two or "
                   "three specific things.",
        "status": "standard test-taking strategy, not a research finding",
    },
    {
        "title": "Answer before you look at the options",
        "body": "Commit to an answer from the stem alone, then find it in the "
                "list. Distractors are written to be plausible; reading them "
                "first is inviting them to talk you out of it.",
        "why_you": "Resisting a plausible-but-wrong option is inhibitory "
                   "control. Where that is a relative strength for you, this "
                   "plays to it — check your own profile.",
        "status": "standard strategy",
    },
    {
        "title": "Three things narrow almost every vignette",
        "body": "Who (age, sex, risk factors) · When (acute, chronic, how long) · "
                "Numbers (labs, vitals, doses). Everything else is usually "
                "framing. Find those three and most cases collapse.",
        "why_you": "Three items is inside what you can hold. The full paragraph "
                   "is not.",
        "status": "practical",
    },
    {
        "title": "Write the numbers down",
        "body": "The moment a stem gives you more than two values, put them on "
                "paper in a column before you reason.",
        "why_you": "Holding four lab values while reasoning about them is the "
                   "expensive part of the question, and it is entirely "
                   "avoidable with a pen.",
        "status": "load reduction",
    },
    {
        "title": "Watch for the flip",
        "body": "NOT, EXCEPT, LEAST, and CONTRAINDICATED invert the whole "
                "question. Circle them. They are the most common source of "
                "losing a question you actually knew.",
        "why_you": "Nothing profile-specific here — this one costs everyone marks.",
        "status": "practical",
    },
    {
        "title": "Long stem, short answer",
        "body": "Stem length has nothing to do with difficulty. A half-page "
                "vignette often resolves to one buzzword. Length is there to "
                "cost you time, not to signal complexity.",
        "why_you": "Worth knowing precisely because you have extended time — the "
                   "length is designed to pressure people who don't.",
        "status": "practical",
    },
]


EXPLAIN_SCHEMA = {
    "type": "object",
    "properties": {
        "the_ask": {"type": "string", "description": "What is actually being asked, in plain words."},
        "keep": {
            "type": "array",
            "description": "The specific phrases in the stem that change the answer. Quote them.",
            "items": {
                "type": "object",
                "properties": {
                    "phrase": {"type": "string"},
                    "does": {"type": "string", "description": "What this phrase rules in or out."},
                },
                "required": ["phrase", "does"],
                "additionalProperties": False,
            },
        },
        "skip": {
            "type": "array",
            "description": "Phrases that look important and are not. Empty if the stem is genuinely lean - do not invent padding.",
            "items": {"type": "string"},
        },
        "trap": {"type": "string", "description": "How this item is built to catch someone. One or two lines."},
        "in_one_line": {"type": "string", "description": "The whole vignette compressed to one sentence."},
    },
    "required": ["the_ask", "keep", "skip", "trap", "in_one_line"],
    "additionalProperties": False,
}


def explain(question_id: str) -> dict:
    """Ask Claude to separate signal from padding in one stored question."""
    row = db.q1("SELECT stem, premise_table, options FROM question WHERE id = ?",
                question_id)
    if row is None:
        raise KeyError(f"unknown question: {question_id}")

    stem = row["stem"]
    if row["premise_table"]:
        stem += "\n\n" + row["premise_table"]

    prompt = (
        "Show her how to read this question — not how to answer it.\n\n"
        "Separate what actually changes the answer from what is there to take up "
        "time. Quote the stem exactly. If the stem is already lean, return an "
        "empty `skip` list rather than inventing padding to criticise.\n\n"
        "Do not reveal or hint at which option is correct. This is about reading "
        "the stem.\n\n"
        f"---\n{stem}\n---"
    )
    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": prompt}],
        schema=EXPLAIN_SCHEMA,
        max_tokens=4000,
        effort="medium",
        task="question_tactics",
    )
    return claude.json_of(msg)


# ------------------------------------------------------------------ timing

# NBME-style pacing. Step 1 allows 60 minutes for 40 items.
BASE_SECONDS_PER_QUESTION = 90

TIMER_PRESETS = [
    {"id": "off", "label": "No timer", "seconds": None,
     "note": "The default. Extended time is a formal accommodation — untimed is "
             "your normal working condition, not a concession."},
    {"id": "extended2", "label": "Double time (180s)", "seconds": 180,
     "note": "2× standard. If your accommodation is double time, this is the "
             "pace you'll actually sit the exam at."},
    {"id": "extended15", "label": "Time and a half (135s)", "seconds": 135,
     "note": "1.5× standard — the most common extended-time allowance."},
    {"id": "standard", "label": "Standard NBME (90s)", "seconds": 90,
     "note": "What an unaccommodated candidate gets. Useful to know where you "
             "are, not a target you owe anyone."},
]


def timing_guidance(seconds: int | None) -> dict:
    if seconds is None:
        return {
            "mode": "untimed",
            "headline": "No clock.",
            "body": "This is your normal working condition. Nothing here is "
                    "scored on speed, and the timer never affects your mastery.",
        }
    ratio = seconds / BASE_SECONDS_PER_QUESTION
    return {
        "mode": "timed",
        "seconds": seconds,
        "ratio": round(ratio, 2),
        "headline": f"{seconds}s per question ({ratio:g}× standard).",
        "body": (
            "The clock counts up to your limit and then keeps going — it will not "
            "cut you off mid-question. Going over is information, not a failure, "
            "and pace is never folded into your mastery score."
        ),
    }
