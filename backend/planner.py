"""
Time-boxed study plans.

The split here is deliberate and load-bearing:

  THE ARITHMETIC IS COMPUTED. Days left, minutes available, how many questions
  fit, which concepts make the cut and which get dropped - all derived from her
  real mastery data by the code below. It is auditable and it cannot hallucinate.

  THE STRATEGY IS GENERATED. Claude explains how to attack the plan, given her
  profile. It never invents the numbers; it is handed them.

Two honesty rules the schedule obeys:

  * If there is not enough time to cover everything, it says so and names what
    it dropped. A plan that silently omits half the material looks complete and
    is worse than useless the night before an exam.
  * It never schedules more minutes than she said she has.
"""

from __future__ import annotations

import time
import uuid
from datetime import date, timedelta

from . import bank, claude, db, organizer, scheduler
from . import learner_profile

# Unhurried on purpose. Extended time is a formal accommodation, so planning at
# a brisk pace would build a schedule she is behind on by day two.
MINUTES_PER_QUESTION = 1.0

# One question per screen, 3-4 elements at a time. Long blocks are where the
# working-memory cost compounds, so the plan chunks rather than marathons.
BLOCK_MINUTES = 20
MAX_BLOCKS_PER_DAY = 6

# The last stretch before an exam is consolidation, not new material.
REVIEW_ONLY_DAYS = 1


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def build(
    exam_id: str,
    *,
    minutes_per_day: int = 60,
    days_off: list[str] | None = None,
) -> dict:
    exam = organizer.get_exam(exam_id)
    days_left = exam["days_left"]
    if days_left is None:
        raise ValueError("This exam has no usable date.")
    if days_left < 0:
        raise ValueError(f"{exam['name']} was {abs(days_left)} days ago.")

    concepts = organizer.exam_concepts(exam_id)
    if not concepts:
        raise ValueError(
            "Nothing is mapped to this exam yet. Add topics or concepts to it first.")

    off = set(days_off or [])
    today = date.today()
    study_days = [today + timedelta(days=i) for i in range(max(1, int(days_left)) + 1)]
    study_days = [d for d in study_days if _iso(d) not in off]
    if not study_days:
        raise ValueError("Every day between now and the exam is marked off.")

    # Capacity.
    total_minutes = len(study_days) * minutes_per_day
    capacity = int(total_minutes / MINUTES_PER_QUESTION)

    # Priority: exam weight x weakness x forgetting. Same shape as the selector,
    # so the plan and the practice engine agree about what matters.
    for c in concepts:
        weakness = max(0.0, 1.0 - c["effective"])
        forgetting = 0.3 + 0.7 * (1.0 - c["retention"])
        unknown = 1.25 if c["attempts"] == 0 else 1.0
        c["_priority"] = weakness * c["weight"] * forgetting * unknown
    ranked = sorted(concepts, key=lambda c: c["_priority"], reverse=True)

    # How many questions each concept earns. Weak needs more; solid needs a check.
    def needed(c: dict) -> int:
        if c["attempts"] == 0:
            return 4
        if c["effective"] < 0.35:
            return 6
        if c["effective"] < 0.5:
            return 4
        if c["effective"] < 0.65:
            return 3
        if c["effective"] < 0.85:
            return 2
        return 1

    scheduled: list[dict] = []
    dropped: list[dict] = []
    used = 0
    for c in ranked:
        want = needed(c)
        if used + want <= capacity:
            c["_questions"] = want
            scheduled.append(c)
            used += want
        elif capacity - used >= 2:
            c["_questions"] = capacity - used      # partial coverage, honestly
            scheduled.append(c)
            used = capacity
        else:
            dropped.append(c)

    days = _lay_out(scheduled, study_days, minutes_per_day, exam)

    plan = {
        "exam": exam,
        "generated_at": time.time(),
        "days_left": days_left,
        "minutes_per_day": minutes_per_day,
        "study_days": len(study_days),
        "capacity_questions": capacity,
        "scheduled_questions": used,
        "concepts_covered": len(scheduled),
        "concepts_dropped": [
            {"name": c["name"], "topic": c["topic"], "effective": c["effective"],
             "weight": round(c["weight"], 2)}
            for c in dropped
        ],
        "days": days,
        "warnings": _warnings(dropped, days_left, minutes_per_day, capacity,
                              ranked, scheduled_questions=used),
        "top_priority": [
            {"name": c["name"], "topic": c["topic"],
             "effective": c["effective"], "questions": c.get("_questions", 0)}
            for c in scheduled[:5]
        ],
    }

    pid = f"plan_{uuid.uuid4().hex[:8]}"
    db.run("UPDATE study_plan SET superseded = 1 WHERE exam_id = ?", exam_id)
    db.run(
        "INSERT INTO study_plan (id, exam_id, generated_at, days_left, "
        "minutes_per_day, plan, superseded) VALUES (?,?,?,?,?,?,0)",
        pid, exam_id, plan["generated_at"], days_left, minutes_per_day,
        db.js(plan),
    )
    plan["id"] = pid
    return plan


def _lay_out(scheduled, study_days, minutes_per_day, exam) -> list[dict]:
    """Spread concepts across days, interleaved and spaced.

    Two choices worth naming. Concepts are dealt round-robin rather than in
    blocks, so a day mixes topics - interleaving is well evidenced, and
    set-shifting is often a relative strength on this kind of profile. And
    the highest-priority concepts get a second, later appearance when there is
    room, because one pass on the weakest material is not learning.
    """
    n_days = len(study_days)
    review_from = max(0, n_days - REVIEW_ONLY_DAYS)

    buckets: list[list[dict]] = [[] for _ in study_days]
    for i, c in enumerate(scheduled):
        buckets[i % max(1, review_from or n_days)].append(c)

    # Second pass for the worst material, placed at least two days later.
    for i, c in enumerate(scheduled[: max(1, len(scheduled) // 3)]):
        first = i % max(1, review_from or n_days)
        second = first + 2
        if second < review_from:
            buckets[second].append(dict(c, _questions=max(1, c["_questions"] // 2),
                                        _repeat=True))

    days = []
    for i, (d, items) in enumerate(zip(study_days, buckets)):
        is_last = i >= review_from
        blocks = []
        remaining = minutes_per_day

        if is_last:
            blocks.append({
                "kind": "review",
                "label": "Review only - no new material",
                "minutes": min(remaining, BLOCK_MINUTES * 2),
                "questions": int(min(remaining, BLOCK_MINUTES * 2) / MINUTES_PER_QUESTION),
                "mode": "spaced",
                "concepts": [],
                "note": "The day before an exam is for consolidation. "
                        "New material now competes with what you already have.",
            })
        else:
            # Hard budget for the day. Nothing below may exceed it - a plan that
            # quietly overruns the time she said she has is a plan she falls
            # behind on by day two.
            budget = int(minutes_per_day / MINUTES_PER_QUESTION)
            chunk: list[dict] = []
            chunk_q = 0

            for c in items:
                if budget <= 0 or len(blocks) >= MAX_BLOCKS_PER_DAY:
                    break
                take = min(c["_questions"], budget)
                if take <= 0:
                    break
                chunk.append(dict(c, _questions=take))
                chunk_q += take
                budget -= take

                if chunk_q * MINUTES_PER_QUESTION >= BLOCK_MINUTES:
                    blocks.append(_block(chunk, chunk_q))
                    chunk, chunk_q = [], 0

            if chunk and len(blocks) < MAX_BLOCKS_PER_DAY:
                blocks.append(_block(chunk, chunk_q))
            remaining = minutes_per_day - sum(b["minutes"] for b in blocks)

        days.append({
            "date": _iso(d),
            "weekday": d.strftime("%a"),
            "day_index": i,
            "is_exam_eve": i == n_days - 1,
            "minutes": sum(b["minutes"] for b in blocks),
            "questions": sum(b["questions"] for b in blocks),
            "blocks": blocks,
        })
    return days


def _block(chunk: list[dict], questions: int) -> dict:
    return {
        "kind": "practice",
        "label": " · ".join(c["name"] for c in chunk[:3])
                 + (f" +{len(chunk) - 3} more" if len(chunk) > 3 else ""),
        "minutes": int(round(questions * MINUTES_PER_QUESTION)),
        "questions": questions,
        "mode": "weak_areas",
        "concepts": [
            {"concept_id": c["concept_id"], "name": c["name"],
             "questions": c["_questions"], "effective": c["effective"],
             "repeat": bool(c.get("_repeat"))}
            for c in chunk
        ],
    }


def _warnings(dropped, days_left, minutes_per_day, capacity, ranked,
              scheduled_questions=0) -> list[str]:
    out = []

    # The opposite of running out of time, and just as worth saying. Without
    # this, a 6-minute day against a 45-minute budget reads as a broken plan
    # rather than as "there isn't more material mapped to this exam yet".
    if capacity and scheduled_questions and scheduled_questions < capacity * 0.5:
        used_pct = scheduled_questions / capacity
        out.append(
            f"You have far more time than mapped material - this plan uses about "
            f"{used_pct:.0%} of the {minutes_per_day} minutes a day you set. That "
            f"isn't a scheduling error: only {len(ranked)} concept(s) are attached "
            f"to this exam. Map more topics to it, or generate questions for the "
            f"material it covers, and rebuild."
        )

    if dropped:
        need = sum(1 for _ in ranked)
        out.append(
            f"There isn't enough time to cover everything. {len(dropped)} of "
            f"{need} concepts didn't fit and were dropped - the lowest-priority "
            f"ones, listed below. To fit them all you'd need roughly "
            f"{int((capacity + len(dropped) * 3) * MINUTES_PER_QUESTION / max(1, days_left))} "
            f"minutes a day instead of {minutes_per_day}."
        )
    if days_left <= 2:
        out.append(
            "With this little time left, the plan front-loads your weakest "
            "high-weight material and stops introducing new concepts early. "
            "That is the right trade this close to an exam."
        )
    if minutes_per_day > 180:
        out.append(
            "Over three hours a day is scheduled. Break it into separate "
            "sittings - the blocks above are 20 minutes for a reason."
        )
    untested = [c for c in ranked if c["attempts"] == 0]
    if untested:
        out.append(
            f"{len(untested)} mapped concept(s) have never been practised, so "
            f"their difficulty is a guess. The plan assumes they're weak, which "
            f"is the safe assumption but may not be true."
        )
    return out


# ------------------------------------------------------------- strategy

STRATEGY_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string",
                     "description": "One sentence: the single most important thing about this plan."},
        "approach": {"type": "string",
                     "description": "4-6 short lines, one idea per line, on how to work this plan."},
        "per_day_tip": {"type": "string",
                        "description": "One line she should apply every single day."},
        "watch_out": {"type": "string",
                      "description": "The most likely way this plan goes wrong for her specifically."},
        "table": {"type": "string",
                  "description": "A markdown table summarising the phases of the plan. 3-6 rows."},
    },
    "required": ["headline", "approach", "per_day_tip", "watch_out", "table"],
    "additionalProperties": False,
}


def strategy(plan: dict) -> dict:
    """Ask Claude how to work the plan. It is given the numbers, never asked for them."""
    exam = plan["exam"]
    lines = [
        f"Exam: {exam['name']} ({exam['kind']}) on {exam['date']}, "
        f"{plan['days_left']} days away.",
        f"She has {plan['minutes_per_day']} minutes a day across "
        f"{plan['study_days']} study days.",
        f"That is {plan['capacity_questions']} questions of capacity; the plan "
        f"schedules {plan['scheduled_questions']} across "
        f"{plan['concepts_covered']} concepts.",
        "",
        "Highest-priority concepts:",
    ]
    for c in plan["top_priority"]:
        lines.append(f"  - {c['name']} ({c['topic']}): currently "
                     f"{c['effective']:.0%}, {c['questions']} questions planned")
    if plan["concepts_dropped"]:
        lines.append("")
        lines.append(f"Dropped for lack of time ({len(plan['concepts_dropped'])}): "
                     + ", ".join(c["name"] for c in plan["concepts_dropped"][:8]))
    if plan["warnings"]:
        lines.append("")
        lines.append("Constraints already computed:")
        lines += [f"  - {w}" for w in plan["warnings"]]

    prompt = (
        "\n".join(lines)
        + "\n\n"
        "The schedule above is already built and the arithmetic is settled. Do "
        "not recompute it, do not propose different numbers, and do not invent "
        "concepts that are not listed.\n\n"
        "Tell her how to work it. Be specific to this plan and to her profile - "
        "generic exam advice is worthless here. If the plan is too thin for the "
        "time remaining, say so plainly rather than being encouraging about it.\n\n"
        "`watch_out` should name the most likely failure mode for someone with "
        "very low auditory working memory and intact reasoning studying under "
        "time pressure."
    )

    msg = claude.call(
        system=learner_profile.active(),
        messages=[{"role": "user", "content": prompt}],
        schema=STRATEGY_SCHEMA,
        max_tokens=6000,
        effort="high",
        task="plan_strategy",
    )
    return claude.json_of(msg)


def latest(exam_id: str) -> dict | None:
    row = db.q1(
        "SELECT plan FROM study_plan WHERE exam_id = ? AND superseded = 0 "
        "ORDER BY generated_at DESC LIMIT 1", exam_id)
    return db.unjs(row["plan"], None) if row else None
