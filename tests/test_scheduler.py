"""
Tests for question selection.

Selection is stochastic, so these assert distributions and orderings over many
runs rather than one exact sequence - a suite that pinned the sequence would
break on every tuning change while catching none of the real failures.

Run:  python tests/test_scheduler.py
"""

import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import scheduler as S  # noqa: E402

NOW = time.time()
DAY = 86400.0


def cand(cid, **kw):
    return S.Candidate(concept_id=cid, **kw)


# ---------------------------------------------------------------- priority

def test_weaker_outranks_stronger_all_else_equal():
    weak = cand("w", effective=0.2, high_yield=0.5)
    strong = cand("s", effective=0.8, high_yield=0.5)
    assert S.priority(weak) > S.priority(strong)


def test_high_yield_outranks_low_yield_at_equal_weakness():
    hi = cand("h", effective=0.4, high_yield=0.95)
    lo = cand("l", effective=0.4, high_yield=0.25)
    assert S.priority(hi) > S.priority(lo)


def test_weak_high_yield_beats_weaker_low_yield():
    """The core claim from the spec: yield can outweigh raw weakness."""
    critical = cand("acid_base", effective=0.45, high_yield=1.0)
    trivial = cand("obscure", effective=0.30, high_yield=0.1)
    assert S.priority(critical) > S.priority(trivial)


def test_mastered_concepts_still_return_eventually():
    """Forgetting risk floors at 0.3 so nothing is permanently retired."""
    mastered = cand("m", effective=0.95, high_yield=0.5, retention=1.0)
    assert S.priority(mastered) > 0


def test_decayed_outranks_fresh_at_equal_mastery():
    fresh = cand("f", effective=0.7, retention=1.0)
    stale = cand("s", effective=0.7, retention=0.3)
    assert S.priority(stale) > S.priority(fresh)


def test_exam_window_raises_priority():
    base = cand("x", effective=0.5, high_yield=0.6)
    soon = cand("x", effective=0.5, high_yield=0.6, exam_urgency=1.0)
    assert S.priority(soon) > S.priority(base) * 2.0


def test_difficulty_gap_raises_priority():
    flat = cand("a", effective=0.5, difficulty_gap=0.0)
    gappy = cand("b", effective=0.5, difficulty_gap=0.8)
    assert S.priority(gappy) > S.priority(flat)


def test_exam_urgency_curve():
    assert S.exam_urgency(0) == 1.0
    assert S.exam_urgency(None) == 0.0
    assert S.exam_urgency(30) == 0.0
    assert 0.3 < S.exam_urgency(12) < 0.6


# --------------------------------------------------------------- quotas

def test_quotas_sum_to_exactly_n():
    for n in (5, 10, 20, 7, 13, 1):
        for mode in S.MODES:
            q = S.quotas(mode, n)
            assert sum(q.values()) == n, (mode, n, q)


def test_weak_mode_is_mostly_weak():
    q = S.quotas("weak_areas", 20)
    assert q["weak"] >= 13


def test_spaced_mode_is_mostly_due():
    q = S.quotas("spaced", 20)
    assert q["due"] >= 15


# ------------------------------------------------------------- composition

def pool():
    """A realistic mixed pool: weak, strong, due, new, missed."""
    out = []
    for i in range(6):
        out.append(cand(f"weak{i}", effective=0.25, high_yield=0.6, attempts=8))
    for i in range(6):
        out.append(cand(f"strong{i}", effective=0.88, high_yield=0.5, attempts=15))
    for i in range(4):
        out.append(cand(f"due{i}", effective=0.6, attempts=10, due_at=NOW - DAY))
    for i in range(4):
        out.append(cand(f"new{i}", effective=0.35, attempts=0))
    for i in range(3):
        out.append(cand(f"missed{i}", effective=0.4, attempts=5, missed_recently=True))
    for i in range(3):
        out.append(cand(f"hy{i}", effective=0.45, high_yield=0.9, attempts=6))
    return out


def test_returns_exactly_n():
    for n in (5, 10, 20):
        got = S.compose(pool(), n=n, mode="mixed", now=NOW, rng=random.Random(1))
        assert len(got) == n, (n, len(got))


def test_no_duplicates_when_pool_is_large_enough():
    got = S.compose(pool(), n=20, mode="mixed", now=NOW, rng=random.Random(2))
    assert len({c.concept_id for c in got}) == 20


def test_weak_mode_actually_serves_weak_concepts():
    got = S.compose(pool(), n=20, mode="weak_areas", now=NOW, rng=random.Random(3))
    weak_served = sum(1 for c in got if c.effective < 0.5)
    assert weak_served >= 12, weak_served


def test_spaced_mode_serves_due_concepts_first():
    got = S.compose(pool(), n=10, mode="spaced", now=NOW, rng=random.Random(4))
    due = sum(1 for c in got if c.due_at is not None)
    assert due >= 4, due   # only 4 due exist; the rest spills


def test_short_pool_still_fills_the_session():
    """Three concepts, twenty questions: repeat rather than end early."""
    tiny = [cand("a", effective=0.3), cand("b", effective=0.4), cand("c", effective=0.5)]
    got = S.compose(tiny, n=20, mode="mixed", now=NOW, rng=random.Random(5))
    assert len(got) == 20


def test_empty_pool_is_safe():
    assert S.compose([], n=10, mode="mixed", now=NOW) == []


def test_sessions_differ_between_runs():
    """Softmax, not argmax: two sessions should not be identical."""
    a = [c.concept_id for c in S.compose(pool(), n=10, mode="mixed", now=NOW,
                                         rng=random.Random(11))]
    b = [c.concept_id for c in S.compose(pool(), n=10, mode="mixed", now=NOW,
                                         rng=random.Random(99))]
    assert a != b


def test_selection_still_favors_weak_on_average():
    """Stochastic, but not random: weak concepts must dominate over many runs."""
    counts = {}
    for seed in range(40):
        for c in S.compose(pool(), n=10, mode="mixed", now=NOW, rng=random.Random(seed)):
            counts[c.concept_id] = counts.get(c.concept_id, 0) + 1
    weak_total = sum(v for k, v in counts.items() if k.startswith("weak"))
    strong_total = sum(v for k, v in counts.items() if k.startswith("strong"))
    assert weak_total > strong_total * 1.5, (weak_total, strong_total)


# -------------------------------------------------------- variant rotation

def test_prefers_unseen_variant():
    c = cand("x", available_cells=[
        ("recognition", 1, NOW - DAY),
        ("application", 3, None),          # never served
    ])
    assert S.pick_cell(c)[0] == "application"


def test_opens_on_the_easiest_unseen_variant():
    c = cand("x", available_cells=[
        ("application", 3, None),
        ("recognition", 1, None),
    ])
    assert S.pick_cell(c)[1] == 1


def test_rotates_to_least_recently_seen():
    c = cand("x", effective=0.3, available_cells=[
        ("recognition", 1, NOW - 60),        # just served
        ("cued_recall", 2, NOW - 10 * DAY),  # stale
    ])
    assert S.pick_cell(c)[0] == "cued_recall"


def test_escalates_difficulty_when_doing_well():
    c = cand("x", effective=0.75, available_cells=[
        ("recognition", 1, NOW - 10 * DAY),
        ("application", 3, NOW - 2 * DAY),
    ])
    assert S.pick_cell(c)[1] == 3


def test_no_cells_is_safe():
    assert S.pick_cell(cand("x")) is None


# ------------------------------------------------------------------ SM-2

def test_correct_answers_lengthen_the_interval():
    s = {"ease": 2.5, "interval_d": 0.0, "reps": 0}
    seen = []
    for _ in range(4):
        s = S.schedule_next(correct=True, confidence="knew", **{
            k: s[k] for k in ("ease", "interval_d", "reps")})
        seen.append(s["interval_d"])
    assert seen == sorted(seen)
    assert seen[-1] > 6


def test_wrong_answer_resets_to_one_day():
    r = S.schedule_next(correct=False, confidence="unsure",
                        ease=2.5, interval_d=30.0, reps=5)
    assert r["interval_d"] == 1.0 and r["reps"] == 0 and r["lapsed"]


def test_confidently_wrong_hurts_ease_more_than_guessing():
    conf = S.schedule_next(correct=False, confidence="knew",
                           ease=2.5, interval_d=10, reps=3)
    guess = S.schedule_next(correct=False, confidence="guessed",
                            ease=2.5, interval_d=10, reps=3)
    assert conf["ease"] <= guess["ease"]


def test_correct_guess_earns_less_ease_than_confident_correct():
    knew = S.schedule_next(correct=True, confidence="knew",
                           ease=2.5, interval_d=6, reps=2)
    guessed = S.schedule_next(correct=True, confidence="guessed",
                              ease=2.5, interval_d=6, reps=2)
    assert knew["ease"] > guessed["ease"]
    assert knew["interval_d"] > guessed["interval_d"]


def test_ease_never_goes_below_floor():
    ease = 2.5
    for _ in range(30):
        ease = S.schedule_next(correct=False, confidence="knew",
                               ease=ease, interval_d=5, reps=1)["ease"]
    assert ease >= 1.3


# ------------------------------- overlapping buckets (regression) ----------

def test_buckets_overlap_rather_than_partition():
    """Regression: a single-bucket rule let "missed" swallow everything.

    After any session with wrong answers most concepts are recently-missed. If
    that were an exclusive label, the missed quota (10% in mixed mode) would be
    the only bucket with candidates and composition would collapse.
    """
    c = cand("x", effective=0.3, high_yield=0.9, attempts=5,
             missed_recently=True, due_at=NOW - DAY)
    b = S.buckets_for(c, NOW)
    assert {"missed", "due", "weak", "high_yield"} <= b, b


def test_new_concepts_are_only_new():
    b = S.buckets_for(cand("n", attempts=0), NOW)
    assert b == {"new"}


def test_all_recently_missed_still_composes_a_full_session():
    """The exact failure seen on seeded data: everything missed, n not honored."""
    pool = [cand(f"c{i}", effective=0.2 + i * 0.05, high_yield=0.8,
                 attempts=6, missed_recently=True) for i in range(15)]
    got = S.compose(pool, n=10, mode="mixed", now=NOW, rng=random.Random(3))
    assert len(got) == 10
    assert len({c.concept_id for c in got}) == 10


def test_scarce_buckets_are_not_starved_by_weak():
    """One due concept must survive a mode whose weak quota could absorb it."""
    pool = [cand(f"w{i}", effective=0.2, attempts=5) for i in range(20)]
    pool.append(cand("due1", effective=0.3, attempts=5, due_at=NOW - DAY))
    got = S.compose(pool, n=10, mode="mixed", now=NOW, rng=random.Random(4))
    assert any(c.concept_id == "due1" for c in got)


if __name__ == "__main__":
    passed = failed = 0
    for name, fn in sorted(globals().items()):
        if not name.startswith("test_") or not callable(fn):
            continue
        try:
            fn()
            passed += 1
            print(f"  PASS  {name}")
        except AssertionError as exc:
            failed += 1
            print(f"  FAIL  {name}: {exc}")
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1 if failed else 0)
