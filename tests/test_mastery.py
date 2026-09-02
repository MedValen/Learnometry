"""
Tests for the mastery math.

These assert the *properties* the design promises, not specific decimals - so
the formula can be tuned without rewriting the suite, but cannot quietly lose a
guarantee.

Run:  python -m pytest tests -q      (or: python tests/test_mastery.py)
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend import mastery as M  # noqa: E402

NOW = time.time()
DAY = 86400.0


def seq(n, correct=True, difficulty=2, confidence="unsure", spacing_days=1.0):
    """n attempts, newest last, one per `spacing_days`."""
    return [
        M.Attempt(ts=NOW - (n - 1 - i) * spacing_days * DAY,
                  correct=correct, difficulty=difficulty, confidence=confidence)
        for i in range(n)
    ]


# --------------------------------------------------------- core guarantees

def test_no_history_sits_at_prior():
    m = M.compute([], now=NOW)
    assert m.mastery == M.PRIOR
    assert m.band == "red"
    assert m.attempts == 0


def test_small_sample_cannot_go_green():
    """Four lucky answers must not paint a concept green."""
    m = M.compute(seq(4, correct=True, confidence="knew", difficulty=2), now=NOW)
    assert m.band in ("orange", "yellow"), m.band
    assert m.effective < M.BAND_YELLOW


def test_sustained_correct_reaches_green():
    m = M.compute(seq(15, correct=True, confidence="knew", difficulty=3), now=NOW)
    assert m.band in ("light_green", "dark_green"), (m.band, m.effective)


def test_mastery_is_not_percent_correct():
    """Same 100% accuracy, different difficulty -> different mastery."""
    easy = M.compute(seq(15, difficulty=1, confidence="knew"), now=NOW)
    hard = M.compute(seq(15, difficulty=3, confidence="knew"), now=NOW)
    assert hard.mastery > easy.mastery
    assert easy.correct == hard.correct  # identical raw score


def test_level_one_only_cannot_master():
    """The deliberate ceiling: recall alone never reaches dark green."""
    m = M.compute(seq(30, difficulty=1, confidence="knew"), now=NOW)
    assert m.band != "dark_green"
    assert m.mastery <= M.DIFFICULTY_WEIGHT[1] + 0.01


def test_recency_beats_ancient_history():
    """Ten old wins then five recent losses must read worse than the reverse."""
    old_good = seq(10, correct=True, confidence="knew")
    recent_bad = [M.Attempt(ts=NOW - i * 3600, correct=False, difficulty=2,
                            confidence="unsure") for i in range(5)][::-1]
    declining = M.compute(old_good + recent_bad, now=NOW)

    old_bad = [M.Attempt(ts=NOW - (15 - i) * DAY, correct=False, difficulty=2,
                         confidence="unsure") for i in range(10)]
    recent_good = [M.Attempt(ts=NOW - i * 3600, correct=True, difficulty=2,
                             confidence="knew") for i in range(5)][::-1]
    improving = M.compute(old_bad + recent_good, now=NOW)

    assert improving.mastery > declining.mastery


# ------------------------------------------------------------- confidence

def test_confident_wrong_costs_more_than_hedged_wrong():
    """The misconception signal from section 5."""
    confident = M.credit(M.Attempt(ts=NOW, correct=False, difficulty=3, confidence="knew"))
    hedged = M.credit(M.Attempt(ts=NOW, correct=False, difficulty=3, confidence="unsure"))
    guessed = M.credit(M.Attempt(ts=NOW, correct=False, difficulty=3, confidence="guessed"))
    assert confident < hedged < guessed < 0


def test_correct_guess_counts_less_than_knowing():
    knew = M.credit(M.Attempt(ts=NOW, correct=True, difficulty=2, confidence="knew"))
    guessed = M.credit(M.Attempt(ts=NOW, correct=True, difficulty=2, confidence="guessed"))
    assert 0 < guessed < knew


# ---------------------------------------------------------------- decay

def test_retention_decays_and_mastery_does_not():
    attempts = seq(15, correct=True, confidence="knew", difficulty=3)
    fresh = M.compute(attempts, now=NOW)
    stale = M.compute(attempts, now=NOW + 120 * DAY)

    assert stale.mastery == fresh.mastery          # what she knew is unchanged
    assert stale.retention < fresh.retention       # confidence in it is not
    assert stale.effective < fresh.effective
    assert stale.retention < 0.5


def test_decay_is_gradual_not_a_cliff():
    attempts = seq(15, correct=True, confidence="knew", difficulty=3)
    bands = [M.compute(attempts, now=NOW + d * DAY).band for d in (0, 10, 30, 90, 365)]
    assert bands[0] in ("light_green", "dark_green")
    assert bands[-1] in ("red", "orange", "yellow")
    # Never jumps straight from mastered to red.
    order = ["red", "orange", "yellow", "light_green", "dark_green"]
    idx = [order.index(b) for b in bands]
    assert idx == sorted(idx, reverse=True), idx


def test_scheduled_reviews_slow_decay():
    attempts = seq(15, correct=True, confidence="knew", difficulty=3)
    unscheduled = M.compute(attempts, now=NOW + 60 * DAY)
    scheduled = M.compute(attempts, now=NOW + 60 * DAY, interval_d=45, ease=2.5)
    assert scheduled.retention > unscheduled.retention


# ----------------------------------------------------------- inconsistency

def test_high_mean_but_mixed_reads_yellow():
    """The override that makes yellow mean 'inconsistent' and not just 'mid'.

    A concept can average well and still be unreliable. Mean alone hides that;
    the variance term is what surfaces it.
    """
    assert M.band_for(0.90, retention=1.0, variance=0.50, n=8) == "yellow"
    assert M.band_for(0.90, retention=1.0, variance=0.10, n=8) == "dark_green"


def test_alternating_weak_reads_red_not_yellow():
    """Deliberate: the override does not apply below orange.

    Someone alternating right and wrong at 50% is weak, not merely
    inconsistent, and calling that yellow would understate the problem.
    """
    alt = [M.Attempt(ts=NOW - i * DAY, correct=(i % 2 == 0), difficulty=2,
                     confidence="unsure") for i in range(10)][::-1]
    m = M.compute(alt, now=NOW)
    assert m.variance >= M.INCONSISTENT_STDEV   # it IS inconsistent
    assert m.band == "red"                      # but weakness dominates
    assert m.effective < M.BAND_ORANGE


def test_steady_performance_is_not_inconsistent():
    m = M.compute(seq(10, correct=True, confidence="knew", difficulty=2), now=NOW)
    assert m.variance < M.INCONSISTENT_STDEV


# --------------------------------------------------------- difficulty gap

def test_difficulty_gap_detects_recall_without_application():
    attempts = (
        [M.Attempt(ts=NOW - i * DAY, correct=True, difficulty=1, confidence="knew")
         for i in range(6)]
        + [M.Attempt(ts=NOW - i * DAY, correct=False, difficulty=3, confidence="unsure")
           for i in range(6)]
    )
    m = M.compute(attempts, now=NOW)
    assert M.difficulty_gap(m) > 0.8


def test_difficulty_gap_zero_without_evidence():
    m = M.compute(seq(6, difficulty=1), now=NOW)
    assert M.difficulty_gap(m) == 0.0


# ------------------------------------------------------- the profile rule

def test_response_time_never_changes_mastery():
    """The neuropsych constraint, enforced as a test.

    slow naming. If a future change makes speed count, this fails.
    """
    slow = [M.Attempt(ts=NOW - i * DAY, correct=True, difficulty=2,
                      confidence="knew", rt_ms=90_000) for i in range(12)]
    fast = [M.Attempt(ts=NOW - i * DAY, correct=True, difficulty=2,
                      confidence="knew", rt_ms=1_200) for i in range(12)]
    a, b = M.compute(slow, now=NOW), M.compute(fast, now=NOW)
    assert a.mastery == b.mastery
    assert a.effective == b.effective
    assert a.band == b.band


def test_streaks_count_from_most_recent():
    attempts = seq(5, correct=True) + [
        M.Attempt(ts=NOW + 3600, correct=False, difficulty=2, confidence="unsure")]
    m = M.compute(attempts, now=NOW + 7200)
    assert m.streak == 0            # the newest attempt was wrong
    assert m.longest_streak == 5


def test_mastered_is_actually_reachable():
    """Regression: dark green was mathematically unreachable.

    Every practice cell has a hard mastery ceiling, set by its credit value
    against the shrinkage prior. A previous tuning put the ceiling for sustained
    Level 3 work at 0.793 while dark green sat at 0.85, so "mastered" was a rung
    nobody could stand on.

    The ceiling is measured through compute() rather than recomputed here, so
    this test cannot drift away from the implementation it is guarding.
    """
    def ceiling(difficulty, confidence):
        return M.compute(
            seq(M.WINDOW * 2, correct=True, difficulty=difficulty,
                confidence=confidence),
            now=NOW,
        ).mastery

    # Confident clinical reasoning must be able to reach mastered.
    assert ceiling(3, "knew") >= M.BAND_LGREEN, (
        f"L3 ceiling {ceiling(3, 'knew'):.3f} < dark green {M.BAND_LGREEN}")
    assert ceiling(4, "knew") >= M.BAND_LGREEN

    # Recall-only practice must not, however much of it she does.
    assert ceiling(1, "knew") < M.BAND_LGREEN
    assert ceiling(2, "unsure") < M.BAND_LGREEN


def test_sustained_level_three_actually_masters():
    """The same guarantee, end to end through compute()."""
    m = M.compute(seq(20, correct=True, confidence="knew", difficulty=3), now=NOW)
    assert m.band == "dark_green", (m.band, m.effective)


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
