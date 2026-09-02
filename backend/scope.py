"""
Scoping: deciding which slice of the bank the engine is allowed to draw from.

Without this, practice pulls from everything she has ever studied, so material
from a finished Term 3 exam competes with the block she is actually sitting in
two weeks. That is the right default for long-term retention and the wrong one
for a student with a midterm on Friday - so it becomes a choice rather than an
assumption.

One thing worth stating plainly, because it is a real trade: narrowing scope
suppresses spaced repetition for everything outside it. Old material keeps
decaying while it is filtered out; it does not stop existing. `describe()`
returns that consequence as text so the UI can say it rather than hide it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from . import db


@dataclass
class Scope:
    term_id: str | None = None
    course_id: str | None = None
    exam_ids: list[str] = field(default_factory=list)
    topic_ids: list[str] = field(default_factory=list)
    # Specific uploaded files - "just this lecture". The narrowest scope there
    # is, and the one she reaches for when a single deck is the problem.
    upload_ids: list[str] = field(default_factory=list)
    # Drop concepts whose only exam links are exams that have already happened.
    exclude_past: bool = False
    # Concepts not attached to any exam at all - most of the bank, usually.
    include_unmapped: bool = True

    @classmethod
    def from_dict(cls, d: dict | None) -> "Scope":
        d = d or {}
        return cls(
            term_id=d.get("term_id") or None,
            course_id=d.get("course_id") or None,
            exam_ids=[e for e in (d.get("exam_ids") or []) if e],
            topic_ids=[t for t in (d.get("topic_ids") or []) if t],
            upload_ids=[u for u in (d.get("upload_ids") or []) if u],
            exclude_past=bool(d.get("exclude_past")),
            include_unmapped=bool(d.get("include_unmapped", True)),
        )

    @property
    def is_everything(self) -> bool:
        return not (self.term_id or self.course_id or self.exam_ids
                    or self.topic_ids or self.upload_ids or self.exclude_past
                    or not self.include_unmapped)


def _is_past(iso_date: str | None) -> bool:
    if not iso_date:
        return False
    try:
        return datetime.strptime(iso_date, "%Y-%m-%d").date() < date.today()
    except (ValueError, TypeError):
        return False


def _concepts_of_exam(row) -> set[str]:
    """Concepts an exam covers, directly or through a topic subtree."""
    ids: set[str] = set(db.unjs(row["concept_ids"], []))
    for tid in db.unjs(row["topic_ids"], []):
        for r in db.q(
            "SELECT id FROM concept WHERE retired = 0 AND (topic_id = ? OR topic_id IN "
            "(SELECT id FROM topic WHERE parent_id = ?))", tid, tid,
        ):
            ids.add(r["id"])
    return ids


def _concepts_of_topics(topic_ids: list[str]) -> set[str]:
    ids: set[str] = set()
    for tid in topic_ids:
        for r in db.q(
            "SELECT id FROM concept WHERE retired = 0 AND (topic_id = ? OR topic_id IN "
            "(SELECT id FROM topic WHERE parent_id = ?))", tid, tid,
        ):
            ids.add(r["id"])
    return ids


def _concepts_of_uploads(upload_ids: list[str]) -> set[str]:
    """Concepts whose questions came from these files.

    Resolved through the same slug match the library uses for its question
    counts, because a question records its origin as a free-text label rather
    than a file id - the API path wrote a prefixed filename, an import writes
    the analysis title, and both must resolve to the same lecture.
    """
    from . import library

    ids: set[str] = set()
    for uid in upload_ids:
        try:
            ids |= set(library.concept_ids_from(uid))
        except KeyError:
            continue                      # file deleted; ignore rather than fail
    return ids


def allowed(scope: Scope) -> set[str] | None:
    """The concept ids this scope permits. None means no restriction."""
    if scope.is_everything:
        return None

    exams = db.q("SELECT * FROM exam")
    mapped: set[str] = set()          # every concept attached to any exam
    in_scope: set[str] = set()        # concepts attached to an in-scope exam
    past_only: set[str] = set()       # candidates for the "previous exams" filter
    current: set[str] = set()

    for e in exams:
        concepts = _concepts_of_exam(e)
        if not concepts:
            continue
        mapped |= concepts

        if _is_past(e["date"]):
            past_only |= concepts
        else:
            current |= concepts

        if scope.exam_ids:
            hit = e["id"] in scope.exam_ids
        elif scope.course_id:
            hit = e["course_id"] == scope.course_id
        elif scope.term_id:
            hit = e["term_id"] == scope.term_id
        else:
            hit = True
        if hit:
            in_scope |= concepts

    # A concept sitting on both a finished exam and an upcoming one is not
    # "previous material" - the upcoming exam wins.
    past_only -= current

    if scope.exam_ids or scope.course_id or scope.term_id:
        result = set(in_scope)
    else:
        result = set(
            r["id"] for r in db.q("SELECT id FROM concept WHERE retired = 0"))

    if scope.topic_ids:
        topical = _concepts_of_topics(scope.topic_ids)
        result = (result & topical) if result else topical

    # Narrowing to a file is an intersection, so combining it with an exam
    # means "this lecture, as examined there" rather than one or the other.
    if scope.upload_ids:
        from_files = _concepts_of_uploads(scope.upload_ids)
        result = (result & from_files) if result else from_files
        # A file names its own concepts exactly, so "everything unattached to
        # an exam" must not smuggle the rest of the bank back in.
        return result

    if scope.include_unmapped:
        unmapped = {r["id"] for r in db.q(
            "SELECT id FROM concept WHERE retired = 0")} - mapped
        result |= unmapped
    else:
        result -= ({r["id"] for r in db.q(
            "SELECT id FROM concept WHERE retired = 0")} - mapped)

    if scope.exclude_past:
        result -= past_only

    return result


def describe(scope: Scope) -> dict:
    """Human-readable summary of what a scope does, including its cost."""
    ids = allowed(scope)

    # Count only concepts that actually have questions. A concept with none
    # cannot be served, so including it would promise practice that the engine
    # then fails to deliver - and the number would disagree with the pool count
    # shown right beside it.
    servable = {r["concept_id"] for r in db.q(
        "SELECT DISTINCT qc.concept_id FROM question_concept qc "
        "JOIN question q ON q.id = qc.question_id WHERE q.retired = 0")}
    total = len(servable)
    count = total if ids is None else len(ids & servable)

    parts: list[str] = []
    if scope.exam_ids:
        names = [db.q1("SELECT name FROM exam WHERE id = ?", e) for e in scope.exam_ids]
        parts.append("only " + ", ".join(n["name"] for n in names if n))
    elif scope.course_id:
        c = db.q1("SELECT name FROM course WHERE id = ?", scope.course_id)
        parts.append(f"only {c['name']}" if c else "one course")
    elif scope.term_id:
        t = db.q1("SELECT name FROM term WHERE id = ?", scope.term_id)
        parts.append(f"only {t['name']}" if t else "one term")
    if scope.topic_ids:
        parts.append(f"{len(scope.topic_ids)} topic(s)")
    if scope.upload_ids:
        from . import library
        names = []
        for uid in scope.upload_ids:
            try:
                names.append(library.get(uid)["name"])
            except KeyError:
                pass
        parts.append("only " + ", ".join(names) if names else "selected files")
    if scope.exclude_past:
        parts.append("nothing from finished exams")
    if not scope.include_unmapped:
        parts.append("nothing unattached to an exam")

    warning = None
    if not scope.is_everything:
        warning = (
            "While this filter is on, anything outside it is not served for "
            "review — it keeps decaying in the background. Widen the scope "
            "after the exam to pick it back up."
        )
    if count == 0:
        warning = ("Nothing practisable matches this filter. Either nothing is "
                   "mapped to it, or the concepts it covers have no questions "
                   "generated yet.")

    return {
        "concepts": count,
        "total": total,
        "summary": " · ".join(parts) if parts else "everything you've studied",
        "warning": warning,
    }


def options() -> dict:
    """What the UI can offer, with counts so empty choices are visible."""
    terms = [dict(r) for r in db.q(
        "SELECT id, name, active FROM term ORDER BY sort_order DESC")]
    courses = [dict(r) for r in db.q(
        "SELECT id, name, term_id FROM course ORDER BY sort_order")]

    exams = []
    for r in db.q("SELECT * FROM exam ORDER BY date DESC"):
        exams.append({
            "id": r["id"], "name": r["name"], "date": r["date"],
            "term_id": r["term_id"], "course_id": r["course_id"],
            "past": _is_past(r["date"]),
            "concepts": len(_concepts_of_exam(r)),
        })

    active = next((t["id"] for t in terms if t["active"]), None)

    return {
        "terms": terms,
        "courses": courses,
        "exams": exams,
        "active_term": active,
        "has_past_exams": any(e["past"] for e in exams),
        "presets": presets(active, exams),
    }


def presets(active_term: str | None, exams: list[dict]) -> list[dict]:
    """Named scopes, so the common cases are one click rather than three.

    The BCSC entry is the reason this exists. A comprehensive end-of-term paper
    is not "an exam" in the same sense as a midterm - it is every exam in the
    term at once, including the ones already sat. Expressing that by hand means
    selecting a term AND remembering to switch past exams back on, and getting
    it wrong silently narrows what she practises.
    """
    out = [{
        "id": "everything",
        "name": "Everything you've studied",
        "why": "The default. Best for long-term retention between exams.",
        "scope": {},
    }]

    upcoming = [e for e in exams if not e["past"]]
    if upcoming:
        nxt = min(upcoming, key=lambda e: e["date"])
        out.append({
            "id": "next_exam",
            "name": f"Next exam: {nxt['name']}",
            "why": f"Only what is mapped to {nxt['date']}.",
            "scope": {"exam_ids": [nxt["id"]], "include_unmapped": False},
        })

    if active_term:
        out.append({
            "id": "bcsc",
            "name": "BCSC - everything this term",
            "why": ("A comprehensive paper covers the whole term, including "
                    "blocks already examined, so past exams stay IN."),
            # exclude_past stays False on purpose: for a cumulative exam the
            # material from a finished midterm is still examinable.
            "scope": {"term_id": active_term, "exclude_past": False,
                      "include_unmapped": True},
        })

    return out
