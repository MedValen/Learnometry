"""
Learning analytics: working out how she actually learns.

The whole value of this module is that it refuses to say things it cannot
support. "You retain pharmacology 18% better after flashcard review" is a
wonderful sentence and a lie unless the data carries it, and a study app that
invents that sentence is worse than one that says nothing - she would change how
she studies on the strength of noise.

So every comparison here goes through the same gate:

    n per group  >= MIN_N          enough attempts to mean anything
    |difference| >= MIN_EFFECT     big enough to act on
    p            <  MAX_P          unlikely to be chance

An insight that fails any of those is returned as `pending` with the number of
attempts still needed, so she can see what the app is watching rather than
wondering why a panel is empty.

The test is a two-proportion z-test, implemented here because the whole app runs
on the standard library. It assumes independent attempts, which is imperfect -
repeated attempts at the same concept are correlated - so the p-values are
slightly optimistic. MIN_EFFECT is the guard against that: a difference has to
be large as well as significant.
"""

from __future__ import annotations

import math
import time

from . import db

MIN_N = 30            # attempts per group
MIN_EFFECT = 0.08     # 8 percentage points
MAX_P = 0.05

DAY = 86400.0

FORMAT_LABELS = {
    "recognition": "picking the answer",
    "cued_recall": "producing the term",
    "discrimination": "telling look-alikes apart",
    "application": "applying it to a case",
    "visual_map": "completing a table",
}


# ------------------------------------------------------------- statistics

def _phi(z: float) -> float:
    """Standard normal CDF."""
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def two_proportion(a_hits: int, a_n: int, b_hits: int, b_n: int) -> dict:
    """Two-sided two-proportion z-test."""
    if a_n == 0 or b_n == 0:
        return {"p": 1.0, "z": 0.0, "diff": 0.0, "a": 0.0, "b": 0.0}

    pa, pb = a_hits / a_n, b_hits / b_n
    pooled = (a_hits + b_hits) / (a_n + b_n)
    se = math.sqrt(pooled * (1 - pooled) * (1 / a_n + 1 / b_n))
    if se == 0:
        return {"p": 1.0, "z": 0.0, "diff": pa - pb, "a": pa, "b": pb}

    z = (pa - pb) / se
    return {"p": round(2 * (1 - _phi(abs(z))), 5), "z": round(z, 3),
            "diff": round(pa - pb, 4), "a": round(pa, 4), "b": round(pb, 4)}


def _gate(label: str, kind: str, a_hits, a_n, b_hits, b_n,
          claim_up: str, claim_down: str, a_name: str, b_name: str) -> dict:
    """Run a comparison and decide whether it may be shown."""
    stat = two_proportion(a_hits, a_n, b_hits, b_n)
    enough = a_n >= MIN_N and b_n >= MIN_N
    big = abs(stat["diff"]) >= MIN_EFFECT
    sig = stat["p"] < MAX_P

    out = {
        "id": label, "kind": kind,
        "a_name": a_name, "b_name": b_name,
        "a_n": a_n, "b_n": b_n,
        "a_acc": stat["a"], "b_acc": stat["b"],
        "diff": stat["diff"], "p": stat["p"],
        "surfaced": bool(enough and big and sig),
    }
    if out["surfaced"]:
        out["claim"] = (claim_up if stat["diff"] > 0 else claim_down).format(
            pct=abs(round(stat["diff"] * 100)),
            a=a_name, b=b_name,
            a_acc=round(stat["a"] * 100), b_acc=round(stat["b"] * 100))
        out["confidence"] = (
            f"{a_n + b_n} attempts, p = {stat['p']:.3f}. "
            "Compared with yourself only — there is no norm here.")
    else:
        reasons = []
        if not enough:
            need = max(0, MIN_N - min(a_n, b_n))
            reasons.append(f"needs about {need} more attempts in the smaller group")
        if enough and not big:
            reasons.append(
                f"the difference is only {abs(round(stat['diff'] * 100))} points — "
                f"too small to act on")
        if enough and big and not sig:
            reasons.append(f"could still be chance (p = {stat['p']:.2f})")
        out["pending"] = "; ".join(reasons)
    return out


# ------------------------------------------------------------- comparisons

def _fetch(where: str = "", *params) -> list[dict]:
    sql = ("SELECT correct, confidence, used_cue, difficulty, fmt, ts, concept_id "
           "FROM attempt")
    if where:
        sql += " WHERE " + where
    return [dict(r) for r in db.q(sql, *params)]


def by_format(rows: list[dict]) -> list[dict]:
    """How she does per question format, each against everything else."""
    out = []
    formats = sorted({r["fmt"] for r in rows if r["fmt"]})
    for fmt in formats:
        mine = [r for r in rows if r["fmt"] == fmt]
        rest = [r for r in rows if r["fmt"] != fmt]
        out.append(_gate(
            f"format_{fmt}", "format",
            sum(r["correct"] for r in mine), len(mine),
            sum(r["correct"] for r in rest), len(rest),
            claim_up="You do {pct} points better at {a} than at everything else.",
            claim_down="{a} is your weakest question format — {pct} points below "
                       "your average.",
            a_name=FORMAT_LABELS.get(fmt, fmt), b_name="everything else"))
    return out


def recall_vs_application(rows: list[dict]) -> dict:
    """The difficulty gap, tested rather than eyeballed."""
    recall = [r for r in rows if r["difficulty"] == 1]
    applied = [r for r in rows if r["difficulty"] >= 3]
    return _gate(
        "difficulty_gap", "difficulty",
        sum(r["correct"] for r in recall), len(recall),
        sum(r["correct"] for r in applied), len(applied),
        claim_up="You know the facts but struggle to apply them — {pct} points "
                 "better on recall than on clinical reasoning. That gap is the "
                 "highest-value thing to work on.",
        claim_down="You apply material better than you recall it in isolation, "
                   "by {pct} points. Unusual, and worth knowing.",
        a_name="recall questions", b_name="reasoning questions")


def calibration(rows: list[dict]) -> dict:
    """Is she right when she thinks she is?

    Not a gated comparison - a direct measurement, reported with its own n.
    Over-confidence is the single most useful thing this app can tell her,
    because a confidently wrong answer is a misconception rather than a gap.
    """
    out = {"buckets": [], "n": len(rows)}
    for conf in ("knew", "unsure", "guessed"):
        mine = [r for r in rows if r["confidence"] == conf]
        if not mine:
            continue
        acc = sum(r["correct"] for r in mine) / len(mine)
        out["buckets"].append({
            "confidence": conf, "n": len(mine), "accuracy": round(acc, 3)})

    knew = next((b for b in out["buckets"] if b["confidence"] == "knew"), None)
    if knew and knew["n"] >= MIN_N:
        if knew["accuracy"] < 0.8:
            out["verdict"] = (
                f"When you say you knew it, you're right {knew['accuracy']:.0%} "
                f"of the time. Under about 80% that means some of what feels "
                f"solid isn't — those are misconceptions, not gaps, and they're "
                f"the ones worth chasing first.")
        elif knew["accuracy"] > 0.95:
            out["verdict"] = (
                f"When you say you knew it, you're right {knew['accuracy']:.0%} "
                f"of the time. Your confidence is well calibrated — you can "
                f"trust that feeling.")
        else:
            out["verdict"] = (
                f"When you say you knew it, you're right {knew['accuracy']:.0%} "
                f"of the time. That's well calibrated.")
    else:
        need = MIN_N - (knew["n"] if knew else 0)
        out["pending"] = (f"Needs about {max(0, need)} more answers marked "
                          f"'knew it' before this means anything.")
    return out


def cue_dependence(rows: list[dict]) -> dict:
    """How often the word needs a nudge, and whether it helps when it does."""
    cued = [r for r in rows if r["used_cue"]]
    uncued = [r for r in rows if not r["used_cue"]]
    typed = [r for r in rows if r["fmt"] == "cued_recall"]
    typed_cued = [r for r in typed if r["used_cue"]]

    out = {
        "cued_n": len(cued), "uncued_n": len(uncued),
        "cue_rate": round(len(cued) / len(rows), 3) if rows else 0.0,
        "typed_cue_rate": round(len(typed_cued) / len(typed), 3) if typed else None,
    }
    if len(cued) >= MIN_N:
        acc = sum(r["correct"] for r in cued) / len(cued)
        out["cued_accuracy"] = round(acc, 3)
        out["note"] = (
            f"You open the cue on {out['cue_rate']:.0%} of questions, and when "
            f"you do you get it right {acc:.0%} of the time. A high number there "
            f"is good news: it means the knowledge is in there and only the word "
            f"was slow, which is exactly what your Color Naming score predicts.")
    else:
        out["pending"] = (f"Needs about {max(0, MIN_N - len(cued))} more "
                          f"cue-assisted answers.")
    return out


def spaced_effect(rows: list[dict]) -> dict:
    """Do reviewed concepts hold up better than unreviewed ones?

    The honest version of "spaced repetition works". Concepts with a review
    schedule and more than one rep are compared against those without.
    """
    scheduled = {r["concept_id"] for r in db.q(
        "SELECT concept_id FROM review WHERE reps >= 2")}
    if not scheduled:
        return {"id": "spaced", "surfaced": False,
                "pending": "No concepts have been through two scheduled reviews yet."}

    a = [r for r in rows if r["concept_id"] in scheduled]
    b = [r for r in rows if r["concept_id"] not in scheduled]
    return _gate(
        "spaced", "method",
        sum(r["correct"] for r in a), len(a),
        sum(r["correct"] for r in b), len(b),
        claim_up="Concepts you've reviewed on schedule come back {pct} points "
                 "more accurate than ones you haven't.",
        claim_down="Reviewed concepts are scoring {pct} points *lower* — which "
                   "usually means review is being aimed at your hardest "
                   "material, not that review isn't working.",
        a_name="concepts on a review schedule", b_name="concepts without one")


def time_of_day(rows: list[dict]) -> dict:
    """Morning versus evening, only if there is enough of both."""
    def bucket(ts):
        h = time.localtime(ts).tm_hour
        return "early" if h < 12 else "late" if h >= 18 else "midday"

    early = [r for r in rows if bucket(r["ts"]) == "early"]
    late = [r for r in rows if bucket(r["ts"]) == "late"]
    return _gate(
        "time_of_day", "conditions",
        sum(r["correct"] for r in early), len(early),
        sum(r["correct"] for r in late), len(late),
        claim_up="You score {pct} points better before noon than after six.",
        claim_down="You score {pct} points better after six than before noon.",
        a_name="mornings", b_name="evenings")


# ---------------------------------------------------------------- report

def report() -> dict:
    rows = _fetch()
    total = len(rows)

    comparisons = by_format(rows) + [
        recall_vs_application(rows),
        spaced_effect(rows),
        time_of_day(rows),
    ]
    surfaced = [c for c in comparisons if c.get("surfaced")]
    pending = [c for c in comparisons if not c.get("surfaced")]

    return {
        "attempts": total,
        "gate": {"min_n": MIN_N, "min_effect": MIN_EFFECT, "max_p": MAX_P},
        "insights": sorted(surfaced, key=lambda c: -abs(c["diff"])),
        "pending": pending,
        "calibration": calibration(rows),
        "cues": cue_dependence(rows),
        "method": (
            "Every claim above is a two-proportion z-test against your own "
            f"history: at least {MIN_N} attempts per group, a difference of at "
            f"least {round(MIN_EFFECT * 100)} points, and p below {MAX_P}. "
            "Anything that fails one of those is listed as pending rather than "
            "guessed at. Repeated attempts at the same concept are correlated, "
            "so treat the p-values as optimistic."),
    }
