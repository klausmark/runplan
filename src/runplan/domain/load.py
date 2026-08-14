"""Recent-load classification shared by the coaching and everyday horizons.

The recommender in :mod:`runplan.application.coaching.recommend` and the
rolling everyday horizon in :mod:`runplan.generation.everyday` both need
the same notion of "high", "normal", "low", and "unknown" recent load.
The classification lives here in the domain layer so neither use case
depends on the other. The constants are the same ones the recommender
used to keep before the logic moved.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .recommendations import KEY_WORKOUT_FORMS, CompletedWorkout


class LoadLevel(Enum):
    """Coarse label for the runner's recent running load.

    ``HIGH`` suppresses key workouts and steers the recommender toward
    recovery. ``LOW`` is informative only — the recommender still defaults
    to easy. ``UNKNOWN`` is returned when the baseline window does not
    contain enough weeks to compare against.
    """

    HIGH = "high"
    NORMAL = "normal"
    LOW = "low"
    UNKNOWN = "unknown"


HIGH_LOAD_DISTANCE_THRESHOLD_M = 5_000.0
"""Minimum absolute distance gap (in metres) above the baseline before
:class:`LoadLevel.HIGH` is reported. Prevents the relative ratio from
flagging tiny weeks as high by themselves."""

HIGH_LOAD_DURATION_THRESHOLD_S = 45 * 60
"""Same as :data:`HIGH_LOAD_DISTANCE_THRESHOLD_M` but for duration."""

HIGH_LOAD_RELATIVE = 1.25
"""Recent distance or duration must reach this fraction of the baseline
weekly average to qualify for :class:`LoadLevel.HIGH`."""

LOW_LOAD_RELATIVE = 0.80
"""Recent distance or duration below this fraction of the baseline weekly
average, with the same absolute margin as the high threshold, counts as
:class:`LoadLevel.LOW`."""

RECENT_KEY_DAYS = 7
"""Window used to detect a recent key workout."""

RECENT_HISTORY_DAYS = 14
"""Window used for the recommender's eligibility checks."""

BASELINE_DAYS = 35
"""Outer edge of the baseline window (days before the target day)."""

BASELINE_DAY_OFFSET = 8
"""Inner edge of the baseline window. The seven days immediately before
the target are reserved for the "recent" window so the baseline does not
pollute the recency signal."""

MIN_HISTORY_WORKOUTS = 3
"""Minimum number of completed workouts in the recent window below
which the recommender suppresses key workouts."""

MIN_HISTORY_MINUTES = 90
"""Minimum total minutes in the recent window below which the recommender
suppresses key workouts."""

MIN_BASELINE_WEEKS = 3
"""Minimum count of distinct ISO weeks in the baseline window for the
classifier to return a non-unknown level."""

BASELINE_WEEKS = 4
"""Number of weeks the baseline window is intended to cover; used in
comments and documentation rather than computation."""


@dataclass(frozen=True, slots=True)
class BaselineTotals:
    """Aggregate distance and duration over the baseline window."""

    total_distance_m: float
    total_duration_s: int
    iso_weeks: frozenset[tuple[int, int]]


def recent_window(
    workouts: tuple[CompletedWorkout, ...], target_day: date
) -> tuple[CompletedWorkout, ...]:
    """Return the workouts in the last :data:`RECENT_KEY_DAYS` days."""
    return tuple(w for w in workouts if 0 < (target_day - w.date).days <= RECENT_KEY_DAYS)


def baseline_totals(workouts: tuple[CompletedWorkout, ...], target_day: date) -> BaselineTotals:
    """Return the aggregate distance, duration, and ISO weeks in the
    baseline window (``BASELINE_DAY_OFFSET`` to ``BASELINE_DAYS`` days
    before ``target_day``).
    """
    total_distance = 0.0
    total_duration = 0
    weeks: set[tuple[int, int]] = set()
    for workout in workouts:
        days_back = (target_day - workout.date).days
        if BASELINE_DAY_OFFSET <= days_back <= BASELINE_DAYS:
            total_distance += workout.distance_meters
            total_duration += workout.duration_seconds
            iso_year, iso_week, _ = workout.date.isocalendar()
            weeks.add((iso_year, iso_week))
    return BaselineTotals(
        total_distance_m=total_distance,
        total_duration_s=total_duration,
        iso_weeks=frozenset(weeks),
    )


def classify_load(workouts: tuple[CompletedWorkout, ...], target_day: date) -> LoadLevel:
    """Return the recent load level for ``target_day``.

    Two short-circuits run before the relative ratio check:

    1. Two or more key workouts in the recent window is always
       :class:`LoadLevel.HIGH`.
    2. Fewer than :data:`MIN_BASELINE_WEEKS` distinct ISO weeks in the
       baseline window is :class:`LoadLevel.UNKNOWN`.
    """

    recent = recent_window(workouts, target_day)

    recent_key_count = sum(1 for w in recent if w.form in KEY_WORKOUT_FORMS)
    if recent_key_count >= 2:
        return LoadLevel.HIGH

    totals = baseline_totals(workouts, target_day)
    if len(totals.iso_weeks) < MIN_BASELINE_WEEKS:
        return LoadLevel.UNKNOWN

    baseline_weeks = BASELINE_WEEKS
    baseline_weekly_distance = totals.total_distance_m / baseline_weeks
    baseline_weekly_duration = totals.total_duration_s / baseline_weeks

    recent_distance = sum(w.distance_meters for w in recent)
    recent_duration = sum(w.duration_seconds for w in recent)

    distance_high = (
        recent_distance >= baseline_weekly_distance * HIGH_LOAD_RELATIVE
        and recent_distance >= baseline_weekly_distance + HIGH_LOAD_DISTANCE_THRESHOLD_M
    )
    duration_high = (
        recent_duration >= baseline_weekly_duration * HIGH_LOAD_RELATIVE
        and recent_duration >= baseline_weekly_duration + HIGH_LOAD_DURATION_THRESHOLD_S
    )
    if distance_high or duration_high:
        return LoadLevel.HIGH

    distance_low = (
        recent_distance <= baseline_weekly_distance * LOW_LOAD_RELATIVE
        and baseline_weekly_distance - recent_distance >= HIGH_LOAD_DISTANCE_THRESHOLD_M
    )
    duration_low = (
        recent_duration <= baseline_weekly_duration * LOW_LOAD_RELATIVE
        and baseline_weekly_duration - recent_duration >= HIGH_LOAD_DURATION_THRESHOLD_S
    )
    if distance_low or duration_low:
        return LoadLevel.LOW

    return LoadLevel.NORMAL


__all__ = [
    "BASELINE_DAY_OFFSET",
    "BASELINE_DAYS",
    "BASELINE_WEEKS",
    "BaselineTotals",
    "HIGH_LOAD_DISTANCE_THRESHOLD_M",
    "HIGH_LOAD_DURATION_THRESHOLD_S",
    "HIGH_LOAD_RELATIVE",
    "LOW_LOAD_RELATIVE",
    "LoadLevel",
    "MIN_BASELINE_WEEKS",
    "MIN_HISTORY_MINUTES",
    "MIN_HISTORY_WORKOUTS",
    "RECENT_HISTORY_DAYS",
    "RECENT_KEY_DAYS",
    "baseline_totals",
    "classify_load",
    "recent_window",
]
