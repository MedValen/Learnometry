"""
Mastery, retention, and decay. Pure functions over plain data - no database, no
network - because this is where the bugs that matter will live.

Two rules this module exists to enforce:

1. Mastery is not percent correct. It is recency-weighted credit, scaled by
   question difficulty and by her self-reported confidence, then shrunk toward a
   prior so four lucky attempts cannot paint a concept green.

2. Response time never enters the calculation. Where naming speed is at the 5th
   percentile - slow lexical retrieval, plausibly compounded by ESL. Scoring on
   speed would silently penalize the exact deficit the neuropsych report says
   not to penalize. `rt_ms` is stored and reported as a within-concept trend
   only. If you are tempted to add it here, read learner_profile.py first.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

# --------------------------------------------------------------- constants

# Harder questions carry more evidence about real understanding.
DIFFICULTY_WEIGHT = {1: 0.60, 2: 0.85, 3: 1.00, 4: 1.15}

# Correct answers: how much credit, by how sure she was.
CONFIDENCE_CREDIT = {"knew": 1.00, "unsure": 0.75, "guessed": 0.45}

# Wrong answers: how hard it counts against her. Confidently wrong is a
# misconception, which is worse than an acknowledged gap and needs remediating
# first - so it costs the most.
CONFIDENCE_PENALTY = {"knew": 1.60, "unsure": 1.00, "guessed": 0.70}

WRONG_SCALE = 0.5      # incorrect attempts pull down at half the magnitude
RECENCY_LAMBDA = 0.85  # weight of each older attempt relative to the next
WINDOW = 20            # attempts considered
PRIOR = 0.35           # what we assume before evidence
PRIOR_STRENGTH = 3.0   # in units of attempts

# Band cutoffs read from `effective`, which already folds decay in.
BAND_RED = 0.35
BAND_ORANGE = 0.50
BAND_YELLOW = 0.65
# Each practice cell has a hard mastery ceiling set by its credit value and the
# shrinkage prior, so this threshold and the credit weights are coupled: set it
# too high and "mastered" becomes a rung nobody can stand on. Sustained
# confident Level 3 reasoning must be able to reach it; recall-only practice
# must not. test_mastered_is_actually_reachable pins both directions.
BAND_LGREEN = 0.85
DARK_GREEN_RETENTION = 0.70

# "Inconsistent" means genuinely mixed, not merely mid-range.
INCONSISTENT_STDEV = 0.45
INCONSISTENT_MIN_N = 4
INCONSISTENT_WINDOW = 8

DAY = 86400.0


@dataclass
class Attempt:
    """The slice of an attempt row the math actually needs."""
    ts: float
    correct: bool
    difficulty: int = 1
    confidence: str = "unsure"
    fmt: str = ""
    rt_ms: int | None = None


@dataclass
class Mastery:
    mastery: float = PRIOR
    est_confidence: float = 0.0
    retention: float = 1.0
    effective: float = PRIOR
    band: str = "red"
    attempts: int = 0
    correct: int = 0
    streak: int = 0
    longest_streak: int = 0
    variance: float = 0.0
    stability_days: float = 1.0
    by_difficulty: dict = field(default_factory=dict)
    by_format: dict = field(default_factory=dict)
    avg_rt_ms: float | None = None
    last_reviewed: float | None = None


# ----------------------------------------------------------------- credit

def credit(a: Attempt) -> float:
    """Signed evidence contributed by one attempt.

    A correct L4 answer she was sure of is worth 1.15; a correct L1 guess is
    worth 0.45. A confidently wrong L3 answer is worth -0.80.

    Note the deliberate consequence: answering only Level 1 questions caps a
    concept around 0.60, which is light green at best. You cannot master a
    concept through recall questions alone - the bank has to escalate.
    """
    dw = DIFFICULTY_WEIGHT.get(a.difficulty, 1.0)
    if a.correct:
        return dw * CONFIDENCE_CREDIT.get(a.confidence, 0.75)
    return -WRONG_SCALE * dw * CONFIDENCE_PENALTY.get(a.confidence, 1.0)


def _clamp01(x: float) -> float:
    return 0.0 if x < 0.0 else 1.0 if x > 1.0 else x


# -------------------------------------------------------------- retention

def stability_days(interval_d: float, ease: float, mastery_value: float) -> float:
    """How long knowledge is expected to hold.

    With a review schedule, stability grows with the scheduled interval and its
    ease factor. Without one (Phase 1 - the scheduler lands in Phase 3), fall
    back to mastery: weak things are forgotten fast, strong things slowly.
    """
    if interval_d > 0:
        return max(1.0, interval_d * max(1.3, ease))
    return 1.0 + 20.0 * _clamp01(mastery_value)


def retention_at(days_since: float, stability: float) -> float:
    """Exponential forgetting. 1.0 the moment it was reviewed."""
    if days_since <= 0:
        return 1.0
    return math.exp(-days_since / max(0.5, stability))


# ------------------------------------------------------------------ bands

def band_for(effective: float, retention: float, variance: float, n: int) -> str:
    if n >= INCONSISTENT_MIN_N and variance >= INCONSISTENT_STDEV \
            and effective >= BAND_ORANGE:
        # Genuinely alternating right and wrong. A mean alone would hide this.
        return "yellow"
    if effective < BAND_RED:
        return "red"
    if effective < BAND_ORANGE:
        return "orange"
    if effective < BAND_YELLOW:
        return "yellow"
    if effective < BAND_LGREEN:
        return "light_green"
    return "dark_green" if retention >= DARK_GREEN_RETENTION else "light_green"


# ------------------------------------------------------------------ compute

def compute(
    attempts: list[Attempt],
    *,
    now: float,
    interval_d: float = 0.0,
    ease: float = 2.5,
) -> Mastery:
    """Full mastery state for one concept from its attempt history.

    `attempts` may be in any order; it is sorted newest-first internally.
    """
    m = Mastery()
    if not attempts:
        m.stability_days = stability_days(interval_d, ease, PRIOR)
        return m

    ordered = sorted(attempts, key=lambda a: a.ts, reverse=True)
    m.attempts = len(ordered)
    m.correct = sum(1 for a in ordered if a.correct)
    m.last_reviewed = ordered[0].ts

    window = ordered[:WINDOW]

    # Two separate jobs, deliberately given two separate denominators.
    #
    #   RECENCY_LAMBDA decides WHAT THE MEAN IS - recent attempts dominate.
    #   The attempt count decides HOW MUCH WE TRUST IT - shrinkage toward PRIOR.
    #
    # An earlier version shrank against the recency-weighted denominator, which
    # coupled them: lambda^rank saturates near 6.4, so the prior kept ~30% of
    # the weight forever and the top band became unreachable. Fixing that by
    # raising lambda then weakened recency until a declining student outscored
    # an improving one. They are different questions and need different divisors.
    num = 0.0
    den = 0.0
    for rank, a in enumerate(window):
        w = RECENCY_LAMBDA ** rank
        num += credit(a) * w
        den += w

    weighted_mean = num / den if den else PRIOR
    n_evidence = len(window)
    m.mastery = _clamp01(
        (weighted_mean * n_evidence + PRIOR * PRIOR_STRENGTH)
        / (n_evidence + PRIOR_STRENGTH)
    )

    # How sure the SYSTEM is of that number. Distinct from her self-confidence.
    n_eff = den
    diff_seen = len({a.difficulty for a in window})
    coverage = 0.7 + 0.3 * (diff_seen / 4.0)
    m.est_confidence = _clamp01(n_eff / (n_eff + 4.0) * coverage)

    # Inconsistency: spread of correctness over the recent window.
    recent = window[:INCONSISTENT_WINDOW]
    if len(recent) >= 2:
        vals = [1.0 if a.correct else 0.0 for a in recent]
        mean = sum(vals) / len(vals)
        m.variance = math.sqrt(sum((v - mean) ** 2 for v in vals) / len(vals))

    # Streaks run newest-backward.
    for a in ordered:
        if a.correct:
            m.streak += 1
        else:
            break
    run = 0
    for a in ordered:
        run = run + 1 if a.correct else 0
        m.longest_streak = max(m.longest_streak, run)

    # Per-difficulty and per-format accuracy feed the difficultyGap term in
    # selection and the format analytics in Phase 7.
    for key, attr in (("difficulty", "by_difficulty"), ("fmt", "by_format")):
        buckets: dict = {}
        for a in ordered:
            k = str(getattr(a, key))
            b = buckets.setdefault(k, {"n": 0, "correct": 0})
            b["n"] += 1
            b["correct"] += 1 if a.correct else 0
        for b in buckets.values():
            b["acc"] = b["correct"] / b["n"] if b["n"] else 0.0
        setattr(m, attr, buckets)

    times = [a.rt_ms for a in ordered if a.rt_ms]
    m.avg_rt_ms = sum(times) / len(times) if times else None

    # Decay.
    m.stability_days = stability_days(interval_d, ease, m.mastery)
    days = max(0.0, (now - m.last_reviewed) / DAY)
    m.retention = retention_at(days, m.stability_days)
    m.effective = _clamp01(m.mastery * (0.6 + 0.4 * m.retention))
    m.band = band_for(m.effective, m.retention, m.variance, len(recent))
    return m


def difficulty_gap(m: Mastery) -> float:
    """How much better she does on recall than on reasoning.

    Positive means she knows the facts but cannot apply them - the single most
    useful thing to target, and the reason difficulty is tracked separately from
    mastery at all.
    """
    lo = m.by_difficulty.get("1", {}).get("acc")
    hi = m.by_difficulty.get("3", {}).get("acc")
    if hi is None:
        hi = m.by_difficulty.get("4", {}).get("acc")
    if lo is None or hi is None:
        return 0.0
    return max(0.0, lo - hi)
