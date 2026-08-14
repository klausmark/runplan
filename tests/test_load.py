"""Recent-load classification (Step 10 ``domain/load``).

The classifier is shared by the recommender and the rolling everyday
horizon; the tests below cover the boundary cases that the recommender
already relied on, plus the new ``recent_window`` and ``baseline_totals``
helpers that the everyday generator uses.
"""

from __future__ import annotations

from datetime import date, timedelta

from runplan.domain.load import (
    BASELINE_DAY_OFFSET,
    BASELINE_DAYS,
    BASELINE_WEEKS,
    HIGH_LOAD_DISTANCE_THRESHOLD_M,
    HIGH_LOAD_DURATION_THRESHOLD_S,
    HIGH_LOAD_RELATIVE,
    LOW_LOAD_RELATIVE,
    MIN_BASELINE_WEEKS,
    RECENT_HISTORY_DAYS,
    RECENT_KEY_DAYS,
    LoadLevel,
    baseline_totals,
    classify_load,
    recent_window,
)
from runplan.domain.recommendations import CompletedWorkout
from runplan.domain.workout_form import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    TEMPO_RUN,
)

_TARGET_DAY = date(2026, 8, 12)


def _completed(
    on: date,
    form,
    *,
    km: float = 5.0,
    minutes: int = 30,
) -> CompletedWorkout:
    return CompletedWorkout(
        date=on,
        form=form,
        distance_meters=km * 1000,
        duration_seconds=minutes * 60,
    )


def _baseline(
    *,
    weeks: int = 4,
    km_per_week: float = 22.5,
    minutes_per_session: int = 35,
    sessions_per_week: int = 3,
) -> tuple[CompletedWorkout, ...]:
    """A steady baseline that does not touch the last seven days."""
    out: list[CompletedWorkout] = []
    end = _TARGET_DAY - timedelta(days=8)
    for week in range(weeks):
        for session in range(sessions_per_week):
            day_offset = session * 3 + 1
            out.append(
                _completed(
                    end - timedelta(days=week * 7 + day_offset),
                    EASY_RUN,
                    km=km_per_week / sessions_per_week,
                    minutes=minutes_per_session,
                )
            )
    return tuple(sorted(out, key=lambda w: w.date))


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


def test_constants_match_recommender_semantics() -> None:
    assert RECENT_KEY_DAYS == 7
    assert RECENT_HISTORY_DAYS == 14
    assert BASELINE_DAY_OFFSET == 8
    assert BASELINE_DAYS == 35
    assert BASELINE_WEEKS == 4
    assert MIN_BASELINE_WEEKS == 3
    assert HIGH_LOAD_DISTANCE_THRESHOLD_M == 5_000.0
    assert HIGH_LOAD_DURATION_THRESHOLD_S == 45 * 60
    assert HIGH_LOAD_RELATIVE == 1.25
    assert LOW_LOAD_RELATIVE == 0.80


# ---------------------------------------------------------------------------
# recent_window
# ---------------------------------------------------------------------------


def test_recent_window_excludes_target_day_and_uses_recent_key_days() -> None:
    inside = _completed(_TARGET_DAY - timedelta(days=3), EASY_RUN)
    boundary = _completed(_TARGET_DAY - timedelta(days=RECENT_KEY_DAYS), EASY_RUN)
    outside = _completed(_TARGET_DAY - timedelta(days=RECENT_KEY_DAYS + 1), EASY_RUN)
    on_target = _completed(_TARGET_DAY, EASY_RUN)

    window = recent_window((inside, boundary, outside, on_target), _TARGET_DAY)

    assert inside in window
    assert on_target not in window
    assert boundary in window  # the upper bound is inclusive
    assert outside not in window


# ---------------------------------------------------------------------------
# baseline_totals
# ---------------------------------------------------------------------------


def test_baseline_totals_aggregate_distance_duration_and_iso_weeks() -> None:
    baseline = _baseline()
    totals = baseline_totals(baseline, _TARGET_DAY)

    assert totals.total_distance_m > 0
    assert totals.total_duration_s > 0
    assert MIN_BASELINE_WEEKS <= len(totals.iso_weeks)


def test_baseline_totals_excludes_recent_window() -> None:
    recent = _completed(_TARGET_DAY - timedelta(days=5), EASY_RUN, km=10, minutes=60)
    totals = baseline_totals((recent,), _TARGET_DAY)
    assert totals.total_distance_m == 0
    assert totals.total_duration_s == 0
    assert totals.iso_weeks == frozenset()


# ---------------------------------------------------------------------------
# classify_load
# ---------------------------------------------------------------------------


def test_classify_load_high_when_two_recent_key_workouts() -> None:
    history = (
        _completed(_TARGET_DAY - timedelta(days=2), INTERVAL_WORKOUT, km=8, minutes=45),
        _completed(_TARGET_DAY - timedelta(days=4), TEMPO_RUN, km=8, minutes=45),
    )
    assert classify_load(history, _TARGET_DAY) is LoadLevel.HIGH


def test_classify_load_high_when_recent_exceeds_baseline_with_margin() -> None:
    baseline = _baseline()
    high_recent = (
        _completed(_TARGET_DAY - timedelta(days=2), EASY_RUN, km=12, minutes=70),
        _completed(_TARGET_DAY - timedelta(days=4), EASY_RUN, km=12, minutes=70),
        _completed(_TARGET_DAY - timedelta(days=6), EASY_RUN, km=12, minutes=70),
    )
    assert classify_load(baseline + high_recent, _TARGET_DAY) is LoadLevel.HIGH


def test_classify_load_low_when_recent_drops_below_baseline_with_margin() -> None:
    baseline = _baseline()
    low_recent = (_completed(_TARGET_DAY - timedelta(days=4), EASY_RUN, km=2, minutes=12),)
    assert classify_load(baseline + low_recent, _TARGET_DAY) is LoadLevel.LOW


def test_classify_load_normal_between_thresholds() -> None:
    baseline = _baseline()
    mild_recent = (
        _completed(_TARGET_DAY - timedelta(days=2), EASY_RUN, km=8, minutes=45),
        _completed(_TARGET_DAY - timedelta(days=5), EASY_RUN, km=8, minutes=45),
    )
    assert classify_load(baseline + mild_recent, _TARGET_DAY) is LoadLevel.NORMAL


def test_classify_load_unknown_when_baseline_has_few_weeks() -> None:
    sparse = (_completed(_TARGET_DAY - timedelta(days=10), EASY_RUN, km=5, minutes=30),)
    assert classify_load(sparse, _TARGET_DAY) is LoadLevel.UNKNOWN


def test_classify_load_high_triggers_with_long_run_and_tempo_outside_recent_window() -> None:
    """Two key workouts separated by more than 7 days must NOT trigger HIGH."""
    history = (
        _completed(_TARGET_DAY - timedelta(days=2), LONG_RUN, km=14, minutes=75),
        _completed(_TARGET_DAY - timedelta(days=10), TEMPO_RUN, km=8, minutes=42),
    )
    level = classify_load(history, _TARGET_DAY)
    assert level is not LoadLevel.HIGH


def test_classify_load_ignores_completed_workouts_after_target() -> None:
    """Future 'completed' workouts must not affect the load classification."""
    future_workout = _completed(_TARGET_DAY + timedelta(days=2), EASY_RUN, km=100, minutes=600)
    history = _baseline() + (future_workout,)
    level = classify_load(history, _TARGET_DAY)
    assert level is not LoadLevel.HIGH


# ---------------------------------------------------------------------------
# LoadLevel enum
# ---------------------------------------------------------------------------


def test_load_level_values() -> None:
    assert {level.value for level in LoadLevel} == {"high", "normal", "low", "unknown"}


def test_load_level_recovery_is_not_key() -> None:
    """The classifier only treats LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT as key."""
    from runplan.domain.recommendations import KEY_WORKOUT_FORMS

    assert RECOVERY_RUN not in KEY_WORKOUT_FORMS
    assert EASY_RUN not in KEY_WORKOUT_FORMS
    assert LONG_RUN in KEY_WORKOUT_FORMS
