"""
Validate and import hand-authored lecture material.

Questions are written outside the app - in a chat, by hand, anywhere - and
arrive as JSON. This module is the gate they come through, and it is the only
implementation of that gate: `tools/import_lecture.py` and the Material tab
both call `validate()` and `import_payload()` here, so a rule tightened in one
place cannot be looser in the other.

Validation is driven by generate.ANALYSIS_SCHEMA and generate.QUESTIONS_SCHEMA -
the same dicts the API is instructed to satisfy - so imported material cannot
drift from generated material. On top of the schema sit the invariants a schema
cannot state: a question must point at a concept that exists, an MCQ must have
exactly one correct option, a typed question must have something to type. Those
are the failures that would otherwise appear as a broken item mid-session.

Nothing is written unless every check passes. A partial import is worse than
none, because she would be studying a lecture with holes and no way to see them.
"""

from __future__ import annotations

from . import bank, generate

MCQ_TYPES = {"recognition", "discrimination", "application"}
TYPED_TYPES = {"cued_recall", "visual_map"}


def _type_ok(value, spec) -> bool:
    for n in (spec if isinstance(spec, list) else [spec]):
        if n == "string" and isinstance(value, str):
            return True
        if n == "integer" and isinstance(value, int) and not isinstance(value, bool):
            return True
        if n == "number" and isinstance(value, (int, float)) and not isinstance(value, bool):
            return True
        if n == "boolean" and isinstance(value, bool):
            return True
        if n == "array" and isinstance(value, list):
            return True
        if n == "object" and isinstance(value, dict):
            return True
        if n == "null" and value is None:
            return True
    return False


def check_schema(value, schema: dict, path: str, errs: list[str]) -> None:
    if "type" in schema and not _type_ok(value, schema["type"]):
        errs.append(f"{path}: expected {schema['type']}, got {type(value).__name__}")
        return
    if "enum" in schema and value not in schema["enum"]:
        errs.append(f"{path}: {value!r} is not one of {schema['enum']}")
        return

    if isinstance(value, dict) and "properties" in schema:
        for key in schema.get("required", []):
            if key not in value:
                errs.append(f"{path}: missing required field {key!r}")
        if schema.get("additionalProperties") is False:
            for key in value:
                if key not in schema["properties"]:
                    errs.append(f"{path}: unexpected field {key!r}")
        for key, sub in schema["properties"].items():
            if key in value:
                check_schema(value[key], sub, f"{path}.{key}", errs)

    if isinstance(value, list) and "items" in schema:
        for i, item in enumerate(value):
            check_schema(item, schema["items"], f"{path}[{i}]", errs)


def check_invariants(analysis: dict, questions: list[dict]) -> list[str]:
    errs: list[str] = []

    ids = [c["id"] for c in analysis.get("concepts", [])]
    if len(ids) != len(set(ids)):
        errs.append("analysis: duplicate concept ids")
    known = set(ids)

    qids = [q.get("id") for q in questions]
    if len(qids) != len(set(qids)):
        dupes = sorted({i for i in qids if qids.count(i) > 1})
        errs.append(f"questions: duplicate ids {dupes}")

    for q in questions:
        at = f"question {q.get('id', '?')}"
        if q.get("concept_id") not in known:
            errs.append(f"{at}: concept_id {q.get('concept_id')!r} is not in the analysis")

        kind = q.get("type")
        opts = q.get("options") or []
        if kind in MCQ_TYPES:
            if not 4 <= len(opts) <= 5:
                errs.append(f"{at}: {kind} needs 4-5 options, has {len(opts)}")
            correct = [o for o in opts if o.get("correct")]
            if len(correct) != 1:
                errs.append(f"{at}: needs exactly one correct option, has {len(correct)}")
            for o in opts:
                if not o.get("correct") and not (o.get("why") or "").strip():
                    errs.append(f"{at}: wrong option {o.get('label')!r} has no "
                                "misconception in `why` - a distractor that "
                                "explains nothing teaches nothing")
        elif kind in TYPED_TYPES:
            if opts:
                errs.append(f"{at}: {kind} must have an empty options array")
            if not (q.get("answer_text") or "").strip():
                errs.append(f"{at}: {kind} needs answer_text to type")

        # Her profile's non-negotiables. A missing visual is precisely the
        # failure her report says she cannot compensate for.
        if not (q.get("visual") or "").strip():
            errs.append(f"{at}: `visual` is empty - every item ships with "
                        "something to look at")
        if not (q.get("cue") or "").strip():
            errs.append(f"{at}: `cue` is empty - rung 2 of the retrieval ladder")
        if q.get("difficulty") not in (1, 2, 3, 4):
            errs.append(f"{at}: DOK {q.get('difficulty')!r} is not 1-4")

    covered = {q.get("concept_id") for q in questions}
    for c in analysis.get("concepts", []):
        if c["id"] not in covered:
            errs.append(f"concept {c['id']} ({c['name']!r}) has no questions")

    # Objectives are what the exam is written from, so a question pointing at
    # one that does not exist is a broken link in the only chain that connects
    # practice to the paper.
    obj_ids = [o["id"] for o in analysis.get("objectives", []) if o.get("id")]
    if len(obj_ids) != len(set(obj_ids)):
        errs.append("analysis: duplicate objective ids")
    known_obj = set(obj_ids)
    for q in questions:
        for oid in (q.get("objective_ids") or []):
            if oid not in known_obj:
                errs.append(f"question {q.get('id', '?')}: objective_id {oid!r} "
                            "is not in the analysis")

    return errs


def objective_coverage(analysis: dict, questions: list[dict]) -> dict:
    """Which stated objectives have questions, and which do not.

    This is the report that matters most for exam preparation. The lecture
    tells you what it intends to assess; an objective with no questions is a
    hole in exactly the place the paper will look. It is reported, never
    enforced - some objectives are genuinely covered by another lecture, and
    refusing the import would only teach the author to invent a mapping.
    """
    objectives = analysis.get("objectives", []) or []
    if not objectives:
        return {"stated": 0, "covered": 0, "uncovered": [], "share": None,
                "unmapped_questions": len(questions)}

    hits: dict[str, int] = {o["id"]: 0 for o in objectives}
    unmapped = 0
    for q in questions:
        ids = q.get("objective_ids") or []
        if not ids:
            unmapped += 1
        for oid in ids:
            if oid in hits:
                hits[oid] += 1

    uncovered = [
        {"id": o["id"], "code": o.get("code", ""), "text": o["text"]}
        for o in objectives if hits[o["id"]] == 0
    ]
    covered = len(objectives) - len(uncovered)
    return {
        "stated": len(objectives),
        "covered": covered,
        "uncovered": uncovered,
        "share": round(covered / len(objectives), 3),
        "per_objective": hits,
        "unmapped_questions": unmapped,
    }


def validate(analysis: dict, questions: list[dict]) -> list[str]:
    errs: list[str] = []
    check_schema(analysis, generate.ANALYSIS_SCHEMA, "analysis", errs)
    check_schema({"questions": questions}, generate.QUESTIONS_SCHEMA, "", errs)
    errs.extend(check_invariants(analysis, questions))
    return errs


def summarise(analysis: dict, questions: list[dict]) -> dict:
    by_type: dict[str, int] = {}
    by_dok: dict[str, int] = {}
    for q in questions:
        by_type[q.get("type", "?")] = by_type.get(q.get("type", "?"), 0) + 1
        d = q.get("difficulty")
        if d in (1, 2, 3, 4):
            by_dok[str(d)] = by_dok.get(str(d), 0) + 1

    high = sum(v for k, v in by_dok.items() if int(k) >= 3)
    share = high / len(questions) if questions else 0.0
    return {
        "title": analysis.get("title", ""),
        "concepts": len(analysis.get("concepts", [])),
        "questions": len(questions),
        "by_type": by_type,
        "by_dok": by_dok,
        "dok_labels": {str(k): v for k, v in generate.DOK_LABELS.items()},
        "dok_high": high,
        "dok_high_share": round(share, 3),
        "dok_target": generate.DOK_TARGET_HIGH,
        "dok_on_target": share >= generate.DOK_TARGET_HIGH,
        "objectives": objective_coverage(analysis, questions),
        "flags": analysis.get("flags", []),
    }


def import_payload(payload: dict, *, label: str | None = None,
                   exam_id: str | None = None,
                   upload_id: str | None = None) -> dict:
    """Validate then bank. Raises ValueError listing every problem found.

    `exam_id` attaches every concept this import creates to that exam. Without
    it the material is bankable but not scopeable: she could practise it only
    as part of "everything", never as "what is on Friday's paper".
    """
    analysis = payload.get("analysis") or {}
    questions = payload.get("questions") or []

    errs = validate(analysis, questions)
    if errs:
        raise ValueError("\n".join(errs))

    source_ref = {"label": label or analysis.get("title", "Imported material"),
                  "kind": "lecture"}
    mapping = bank.persist_analysis(analysis, source_ref)
    saved = bank.save_questions(questions, mapping, source_ref=source_ref)

    attached = 0
    if exam_id:
        attached = attach_to_exam(exam_id, list(mapping.values()))

    # Record which file these concepts came out of, so the Library can answer
    # "what did this lecture teach" with a join rather than a scan.
    if upload_id:
        from . import library
        try:
            library.link_concepts(upload_id, list(mapping.values()))
            library.recount(upload_id)
        except Exception:                              # noqa: BLE001
            pass          # the import succeeded; bookkeeping must not undo it

    out = summarise(analysis, questions)
    out.update({"imported_concepts": len(mapping), "imported_questions": len(saved),
                "label": source_ref["label"], "exam_id": exam_id,
                "upload_id": upload_id, "attached_to_exam": attached})
    return out


def attach_to_exam(exam_id: str, concept_ids: list[str]) -> int:
    """Add concepts to an exam's list without disturbing what is already there.

    Union rather than replace: a single exam usually covers several lectures,
    so importing the second one must not erase the first.
    """
    from . import organizer

    exam = organizer.get_exam(exam_id)
    have = set(exam.get("concept_ids") or [])
    merged = sorted(have | {c for c in concept_ids if c})
    if merged != sorted(have):
        organizer.update_exam(exam_id, concept_ids=merged)
    return len(merged) - len(have)


# --------------------------------------------------------------- the spec

SPEC_HEAD = """Produce JSON for a medical study app. Return ONLY the JSON.

{"analysis": {"title","subject_area","overview","orientation_table",
  "concepts":[{"id","name","one_line","yield":"high|medium|low",
               "load_risk","confusable_with"}],
  "count_rationale","flags":[]},
 "questions":[{"id","concept_id","type","stem","premise_table","options",
   "answer_text","accepted_answers","cue","why_right","derive_from","visual",
   "memory_hook","key_clue","takeaway","source_ref","difficulty"}]}
"""

# Written once, here, rather than in the browser. The rules below are the ones
# `check_invariants` actually enforces, and several are generated from the same
# constants it uses - so a rule cannot be tightened in the validator and stay
# stale in the instructions somebody is writing questions against.
SPEC_RULES = """
TYPES
  {mcq} : 4-5 options, exactly ONE correct, options[] required
  {typed} : options MUST be [], answer_text required

EVERY QUESTION NEEDS
  - visual        a markdown table, an ASCII arrow chain (A -> B -> C), or a
                  short indented tree. Never an image or mermaid. Required.
  - cue           a category or first-letter hint that narrows without giving
                  it away. Required.
  - premise_table any fact the stem depends on, so nothing is held in mind.
                  null only if the stem has at most two premises.
  - a `why` on every WRONG option, naming the specific misconception it
    encodes and the one feature that rules it out.
  - accepted_answers: be generous with synonyms and spellings.
  - stems that are self-contained and never refer to an earlier question.

LEARNING OBJECTIVES - do this first
  Most lectures open with numbered objectives, often with an institutional
  code. Copy them VERBATIM into `analysis.objectives`, each with a short local
  id. Then tag every question with the objective(s) it tests, in
  `objective_ids`.

  This matters more than it looks: the exam is written FROM the objectives, so
  an objective with no question is a hole exactly where the paper will look.
  The importer reports that coverage. Aim to cover every objective the lecture
  actually teaches - and if one is covered elsewhere, leave it uncovered and
  say so in `flags` rather than inventing a question to tick it off.

ALSO ENFORCED
  - every concept needs at least one question
  - no duplicate concept ids, no duplicate question ids
  - every concept_id must exist in the analysis
  - every objective_id on a question must exist in the analysis

DEPTH OF KNOWLEDGE  (the `difficulty` field, 1-4)
{dok}
  Her exams are DOK 3-4. At least {target} of the set must be DOK 3 or higher.
  Use DOK 1-2 only as rungs that make a DOK 3 item reachable on a concept she
  has not met - not as filler. A real DOK 4 needs two ideas from different
  parts of the material.

FLAGS
  Record anything in the source that is ambiguous, conflicts with standard
  teaching, or is missing because it lived in an image - then write no
  question that depends on it.
"""


def spec_text(user_id: str | None = None) -> str:
    """The instructions to paste into another chat before authoring.

    Includes her standing notes, because the whole reason those exist is not
    having to repeat them - and a spec that omitted them would send someone off
    to write questions that ignore what the professor stressed.
    """
    dok_lines = "\n".join(
        f"  DOK {k} = {v}" for k, v in sorted(generate.DOK_LABELS.items()))

    rules = SPEC_RULES.format(
        mcq=" | ".join(sorted(MCQ_TYPES)),
        typed=" | ".join(sorted(TYPED_TYPES)),
        dok=dok_lines,
        target=f"{generate.DOK_TARGET_HIGH:.0%}",
    )

    parts = [SPEC_HEAD, rules, _profile_block(user_id)]

    notes = ""
    if user_id:
        try:
            from . import notes_memory
            notes = notes_memory.for_prompt(user_id)
        except Exception:                              # noqa: BLE001
            notes = ""
    if notes:
        parts.append(notes.replace("STANDING NOTES",
                                   "STANDING NOTES (things already known about "
                                   "this student - honour them)"))

    return "\n".join(p for p in parts if p).strip() + "\n"


def _profile_block(user_id: str | None) -> str:
    """The constraints a question has to satisfy, from her actual scores."""
    from . import users

    user = None
    if user_id:
        try:
            user = users.get(user_id)
        except KeyError:
            user = None

    head = "WHO THIS IS FOR"
    if not user or user.get("profile_kind") == "none":
        return (f"{head}\n"
                "  No measured profile on file. Keep every question "
                "self-contained, always include a visual, and never score on "
                "speed.\n")

    from . import learner_profile
    try:
        digest = learner_profile.profile_digest(user)
    except Exception:                                  # noqa: BLE001
        return f"{head}\n  Profile unavailable.\n"

    lines = [head]
    # The caveat names which indices were never derived. An author who does not
    # know that will happily write to a score that was never measured.
    if digest.get("caveat"):
        lines.append(f"  {digest['caveat']}")
    for lever in digest.get("levers", []):
        lines.append(f"  - {lever['finding']} ({lever['score']}): {lever['rule']}")
    lines.append("  Response time is recorded but NEVER scored. There is no "
                 "learning-style claim here - the visual routing is a measured "
                 "within-person gap.")
    return "\n".join(lines) + "\n"
