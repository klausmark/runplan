"""Day assignment for the first 10K generator.

The generator picks one weekday per role from the user's pool of possible
days. The long-run day prefers a weekend slot so the user can run after work
on Saturday or Sunday. The quality day rotates to avoid repeating the same
weekday week-over-week when quality sessions are enabled. Easy days fill the
remaining slots.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import GenerationError
from .inputs import TrainingDays

WEEKEND_DAYS = (6, 7)

MIN_SESSIONS_PER_WEEK = 2
MAX_SESSIONS_PER_WEEK = 7


@dataclass(frozen=True, slots=True)
class WeekAssignment:
    """The day assignment for one week."""

    long_run_day: int
    quality_day: int | None
    easy_days: tuple[int, ...]

    def all_days(self) -> tuple[int, ...]:
        return tuple(sorted({self.long_run_day, *(self.easy_days), *(self.quality_day,)} - {None}))


def _spaced_distance(a: int, b: int) -> int:
    """Return the absolute cyclic distance between two weekdays."""
    diff = abs(a - b)
    return min(diff, 7 - diff)


def pick_long_run_day(
    pool: tuple[int, ...],
    preferred: int | None,
) -> int:
    """Return the weekday for the long run.

    The preferred day is honoured when it is in the pool. Otherwise the
    generator prefers Sunday, then Saturday, then the latest day in the pool.
    The weekend preference gives the runner a daylight slot to fit a longer
    session around family and work.
    """
    if preferred is not None and preferred in pool:
        return preferred
    for day in WEEKEND_DAYS[::-1]:
        if day in pool:
            return day
    return pool[-1]


def pick_quality_day(
    pool: tuple[int, ...],
    long_run_day: int,
    prev_quality_day: int | None,
) -> int:
    """Pick the quality day for the coming week.

    The choice respects three constraints: the chosen day must be in the
    pool, must be at least one day away from the long run, and must differ
    from the previous week's quality day when the pool is large enough.
    """
    if len(pool) == 1:
        raise GenerationError("pool must contain at least one day besides the long run")
    candidates = [
        day for day in pool if day != long_run_day and _spaced_distance(day, long_run_day) >= 2
    ]
    if not candidates:
        candidates = [day for day in pool if day != long_run_day]
    if prev_quality_day is not None and len(candidates) >= 2:
        non_repeat = [day for day in candidates if day != prev_quality_day]
        if non_repeat:
            candidates = non_repeat
    return sorted(candidates, key=lambda d: (abs(d - (long_run_day - 2)), d))[0]


def assign_week(
    pool: tuple[int, ...],
    sessions_per_week: int,
    long_run_day: int,
    prev_quality_day: int | None,
    week_index: int,
    quality_per_week: int = 0,
) -> WeekAssignment:
    """Return the day assignment for one week.

    The ``week_index`` parameter (0-based) is used to rotate the long-run day
    every four weeks so the program does not always demand the same weekday.
    The ``quality_per_week`` parameter controls whether the quality slot is
    reserved. Without it, the empty quality slot would silently drop the
    session count below the requested total.
    """
    if sessions_per_week >= 3 and quality_per_week >= 1:
        quality_day = pick_quality_day(pool, long_run_day, prev_quality_day)
    else:
        quality_day = None
    reserved = {long_run_day}
    if quality_day is not None:
        reserved.add(quality_day)
    remaining = [day for day in pool if day not in reserved]
    extra = max(0, sessions_per_week - 1 - (1 if quality_day is not None else 0))
    easy_days = tuple(sorted(remaining[:extra]))
    if not easy_days and quality_day is None and sessions_per_week > 1:
        raise GenerationError("no easy days available for the requested session count")
    return WeekAssignment(
        long_run_day=long_run_day,
        quality_day=quality_day,
        easy_days=easy_days,
    )


def assign_program(
    training_days: TrainingDays,
    duration_weeks: int,
    preferred_long_run_day: int | None = None,
    long_run_rotation: int = 4,
    quality_per_week: int = 0,
) -> tuple[WeekAssignment, ...]:
    """Return the day assignment for every program week."""
    pool = training_days.possible_days
    if not pool:
        raise GenerationError("training_days.possible_days is empty")
    if duration_weeks < 1:
        raise GenerationError("duration_weeks must be >= 1")
    long_run_day = pick_long_run_day(pool, preferred_long_run_day)
    assignments: list[WeekAssignment] = []
    prev_quality_day: int | None = None
    for week_index in range(duration_weeks):
        if week_index > 0 and week_index % long_run_rotation == 0:
            rotated = _rotate_long_run(pool, long_run_day)
            if rotated is not None and rotated != long_run_day:
                long_run_day = rotated
        assignment = assign_week(
            pool=pool,
            sessions_per_week=training_days.sessions_per_week,
            long_run_day=long_run_day,
            prev_quality_day=prev_quality_day,
            week_index=week_index,
            quality_per_week=quality_per_week,
        )
        assignments.append(assignment)
        prev_quality_day = assignment.quality_day
    return tuple(assignments)


def _rotate_long_run(pool: tuple[int, ...], current: int) -> int | None:
    """Pick a different weekday in the pool for the long run."""
    candidates = [day for day in pool if day != current]
    if not candidates:
        return None
    return sorted(candidates)[0]


def pick_last_day(pool: tuple[int, ...]) -> int:
    """Return the day used for the final-week 10K test run.

    The test run lands on the latest possible day in the pool so the runner
    has the rest of the week to taper.
    """
    return pool[-1]


__all__ = [
    "MAX_SESSIONS_PER_WEEK",
    "MIN_SESSIONS_PER_WEEK",
    "WEEKEND_DAYS",
    "WeekAssignment",
    "assign_program",
    "assign_week",
    "pick_last_day",
    "pick_long_run_day",
    "pick_quality_day",
]
