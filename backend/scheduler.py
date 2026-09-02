"""
Question selection. Pure functions over plain data.

Two ideas do the work here:

1. PRIORITY ranks concepts by how much studying them is worth right now -
   weakness, yield, forgetting risk, exam proximity, and the recall/apply gap.

2. COMPOSITION stops priority from being the only voice. A purely greedy
   selector would serve the same five red concepts forever, so the seven
   priorities from the spec become quotas on the session rather than a sort
   order, and picks inside each quota are softmax-sampled instead of taken
   argmax. Two sessions on the same data are related, not identical.

Variant rotation is the Keybr property: hammer the weakness, never the item.
A concept is targeted repeatedly through different (format, difficulty) cells.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field

DAY = 86400.0

# Bucket shares per session mode. Modes reweight the same machinery rather than
# running separate code paths, so a bug fix lands everywhere at once.
MODES: dict[str, dict[str, float]] = {
    "mixed":       {"weak": .35, "high_yield": .20, "due": .20, "missed": .10,
                    "related": .05, "check": .05, "new": .05},
    "weak_areas":  {"weak": .70, "high_yield": .10, "due": .05, "missed": .10,
                    "related": .05, "check": .00, "new": .00},
    "high_yield":  {"weak": .20, "high_yield": .60, "due": .10, "missed": .05,
                    "related": .00, "check": .05, "new": .00},
    "spaced":      {"weak": .10, "high_yield": .05, "due": .80, "missed": .00,
                    "related": .00, "check": .05, "new": .00},
    "exam_cram":   {"weak": .40, "high_yield": .35, "due": .15, "missed": .10,
                    "related": .00, "check": .00, "new": .00},
    "new_material": {"weak": .15, "high_yield": .15, "due": .10, "missed": .00,
                     "related": .00, "check": .00, "new": .60},
    "endless":     {"weak": .35, "high_yield": .20, "due": .20, "missed": .10,
                    "related": .05, "check": .05, "new": .05},
}

TAU = 0.35          # softmax temperature; lower = greedier
COOLDOWN_ITEMS = 6  # a concept cannot return within this many items
CHECK_MIN_BAND = 0.65   # only light/dark green concepts are worth spot-checking
ESCALATE_ABOVE = 0.60   # above this, serve the hardest variant she has
NEW_MAX_ATTEMPTS = 0


@dataclass
class Candidate:
    """Everything selection needs about one concept. No DB rows in here."""
    concept_id: str
    effective: float = 0.35
    retention: float = 1.0
    high_yield: float = 0.5
    attempts: int = 0
    difficulty_gap: float = 0.0
    due_at: float | None = None
    exam_urgency: float = 0.0     # 0 = no exam, 1 = exam is imminent
    last_attempt_ts: float | None = None
    missed_recently: bool = False
    related_to_missed: bool = False
    available_cells: list = field(default_factory=list)  # [(fmt, difficulty, last_seen)]


# ------------------------------------------------------------------ priority

def priority(c: Candidate) -> float:
    """studyPriority = weakness x yield x forgetting x exam x difficultyGap.

    Each term is bounded so no single one can dominate: a perfectly-known
    concept still returns eventually (forgetting floors at 0.3), and a low-yield
    concept is halved rather than zeroed.
    """
    weakness = max(0.0, 1.0 - c.effective) ** 1.5
    yield_w = 0.5 + 1.5 * c.high_yield
    forgetting = 0.3 + 0.7 * (1.0 - c.retention)
    exam_w = 1.0 + 1.5 * c.exam_urgency
    gap_w = 1.0 + c.difficulty_gap
    return weakness * yield_w * forgetting * exam_w * gap_w


def is_due(c: Candidate, now: float) -> bool:
    return c.due_at is not None and c.due_at <= now


# Filled scarcest-first. A concept is consumed by whichever quota reaches it
# first, so the big "weak" pool cannot eat the specific buckets' candidates.
FILL_ORDER = ["new", "due", "missed", "related", "check", "high_yield", "weak"]


def buckets_for(c: Candidate, now: float) -> set[str]:
    """Every quota this concept could satisfy.

    Deliberately NOT exclusive. An earlier version returned a single bucket and
    the categories swallowed each other: after any session with wrong answers,
    almost everything is "recently missed", so a one-bucket rule collapsed the
    whole composition into that one quota. These are overlapping priorities,
    not a partition.
    """
    out: set[str] = set()
    if c.attempts <= NEW_MAX_ATTEMPTS:
        out.add("new")
        return out          # nothing else is meaningful with no history
    if c.missed_recently:
        out.add("missed")
    if is_due(c, now):
        out.add("due")
    if c.related_to_missed:
        out.add("related")
    if c.effective >= CHECK_MIN_BAND:
        out.add("check")
    if c.high_yield >= 0.7 and c.effective < 0.65:
        out.add("high_yield")
    if c.effective < 0.5:
        out.add("weak")
    return out or {"weak"}


def bucket_of(c: Candidate, now: float) -> str:
    """The single most specific label, for display only - never for filling."""
    b = buckets_for(c, now)
    for name in FILL_ORDER:
        if name in b:
            return name
    return "weak"


# -------------------------------------------------------------- composition

def quotas(mode: str, n: int) -> dict[str, int]:
    """Turn shares into whole counts that sum to exactly n."""
    shares = MODES.get(mode, MODES["mixed"])
    raw = {k: v * n for k, v in shares.items()}
    out = {k: int(v) for k, v in raw.items()}

    # Hand out the remainder to the largest fractional parts.
    remainder = n - sum(out.values())
    for k, _ in sorted(raw.items(), key=lambda kv: kv[1] - int(kv[1]), reverse=True):
        if remainder <= 0:
            break
        out[k] += 1
        remainder -= 1
    return out


def softmax_pick(pool: list[Candidate], rng: random.Random, tau: float = TAU) -> Candidate:
    """Weighted draw, so strong candidates usually win but not always."""
    if len(pool) == 1:
        return pool[0]
    scores = [priority(c) for c in pool]
    top = max(scores)
    weights = [math.exp((s - top) / tau) for s in scores]
    total = sum(weights)
    if total <= 0:
        return rng.choice(pool)
    r = rng.random() * total
    acc = 0.0
    for c, w in zip(pool, weights):
        acc += w
        if r <= acc:
            return c
    return pool[-1]


def compose(
    candidates: list[Candidate],
    *,
    n: int,
    mode: str = "mixed",
    now: float,
    rng: random.Random | None = None,
) -> list[Candidate]:
    """Select n concepts for a session.

    Unfilled quotas spill into the remaining pool by priority rather than
    shortening the session - if there is nothing due for review, those slots
    become extra weak-concept work instead of a 14-question "20-question" set.
    """
    rng = rng or random.Random()
    if not candidates or n <= 0:
        return []

    eligible_for: dict[str, list[Candidate]] = {b: [] for b in FILL_ORDER}
    for c in candidates:
        for b in buckets_for(c, now):
            eligible_for.setdefault(b, []).append(c)

    want = quotas(mode, n)
    chosen: list[Candidate] = []
    used: set[str] = set()
    recent: list[str] = []   # cooldown window

    def take(pool_name: str, count: int) -> int:
        got = 0
        pool = [c for c in eligible_for.get(pool_name, []) if c.concept_id not in used]
        while got < count and pool:
            fresh = [c for c in pool if c.concept_id not in recent[-COOLDOWN_ITEMS:]]
            pick = softmax_pick(fresh or pool, rng)
            chosen.append(pick)
            used.add(pick.concept_id)
            recent.append(pick.concept_id)
            pool = [c for c in pool if c.concept_id != pick.concept_id]
            got += 1
        return got

    # Scarcest buckets first, so the broad "weak" quota cannot consume the
    # candidates that only it and one specific bucket could have served.
    shortfall = 0
    for bucket in FILL_ORDER:
        count = want.get(bucket, 0)
        shortfall += count - take(bucket, count)

    # Redistribute what the scarce buckets could not fill, before generic spill.
    if shortfall > 0:
        for bucket in ("weak", "high_yield", "missed", "due"):
            if shortfall <= 0:
                break
            shortfall -= take(bucket, shortfall)

    # Spill: fill any shortfall from whatever is left, best-first.
    if len(chosen) < n:
        rest = sorted(
            (c for c in candidates if c.concept_id not in used),
            key=priority, reverse=True,
        )
        for c in rest[: n - len(chosen)]:
            chosen.append(c)
            used.add(c.concept_id)

    # If the bank is smaller than the session, cycle rather than cut it short.
    if len(chosen) < n and chosen:
        i = 0
        while len(chosen) < n:
            chosen.append(chosen[i % len(chosen)])
            i += 1

    return chosen[:n]


# ---------------------------------------------------------- variant rotation

def pick_cell(c: Candidate, *, escalate: bool = True) -> tuple | None:
    """Choose which (format, difficulty) variant of a concept to serve.

    Least-recently-seen first, so a weak concept comes back as anatomy, then
    localization, then a vignette - rather than the same stem four times.

    When she is doing well, prefer a cell one level harder than her current
    ceiling: a concept practiced only at Level 1 can never register as mastered
    (see mastery.credit), so the engine has to climb.
    """
    if not c.available_cells:
        return None

    cells = sorted(c.available_cells, key=lambda x: (x[2] if x[2] is not None else -1))
    if not escalate:
        return cells[0]

    unseen = [x for x in cells if x[2] is None]
    if unseen:
        # Among never-seen variants, take the easiest - don't open on a Level 4.
        return sorted(unseen, key=lambda x: x[1])[0]

    if c.effective >= ESCALATE_ABOVE:
        # Doing well: serve the hardest variant available, stalest first. A
        # concept practiced only at Level 1 caps around 0.60 in mastery.credit,
        # so climbing is the only route to mastered - and she has the reasoning
        # for it. The load ceiling is enforced in the question itself,
        # not by keeping her on easy items.
        hardest = max(x[1] for x in cells)
        return sorted((x for x in cells if x[1] == hardest), key=lambda x: x[2])[0]

    return cells[0]


# -------------------------------------------------------------------- SM-2

def schedule_next(
    *, correct: bool, ease: float, interval_d: float, reps: int, confidence: str = "unsure",
) -> dict:
    """SM-2, adjusted so self-reported confidence moves the ease factor.

    A correct-but-guessed answer should not buy the same interval as a confident
    one, and a confidently wrong answer should shorten the schedule more than an
    acknowledged gap.
    """
    quality = {"knew": 5, "unsure": 4, "guessed": 3}.get(confidence, 4) if correct \
        else {"knew": 0, "unsure": 2, "guessed": 2}.get(confidence, 2)

    if quality < 3:
        return {"ease": max(1.3, ease - 0.2), "interval_d": 1.0,
                "reps": 0, "lapsed": True}

    new_ease = max(1.3, ease + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02)))
    if reps == 0:
        interval = 1.0
    elif reps == 1:
        interval = 6.0
    else:
        interval = max(1.0, interval_d * new_ease)

    return {"ease": new_ease, "interval_d": interval, "reps": reps + 1, "lapsed": False}


def exam_urgency(days_away: float | None) -> float:
    """1.0 the day of, decaying to 0 about three weeks out."""
    if days_away is None or days_away < 0:
        return 0.0
    return max(0.0, min(1.0, 1.0 - days_away / 21.0))
