"""Evidence-based weekly volume progression.

The progression rule is intentionally not centred on the 10% rule. Buist et
al. (2008, PMID 17940147) showed that a 10% graded program failed to reduce
injury rates in novice runners compared with a standard program. The
generator therefore gives every profile a profile-dependent cap and a
minimum absolute step, and uses a four-week microcycle with a forced recovery
week as the primary safety mechanism.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import GenerationError
from .inputs import (
    MIN_LONG_RUN_KM,
    ProgressionProfile,
)
from .phase import PhaseKind, phase_plan

PROFILE_INCREMENT: dict[ProgressionProfile, float] = {
    "cautious": 0.05,
    "balanced": 0.08,
    "ambitious": 0.10,
}

PROFILE_ABS_MIN_KM: dict[ProgressionProfile, float] = {
    "cautious": 1.0,
    "balanced": 1.5,
    "ambitious": 2.0,
}

PROFILE_LONG_RUN_ABS_MIN_KM: dict[ProgressionProfile, float] = {
    "cautious": 0.5,
    "balanced": 1.0,
    "ambitious": 1.0,
}

PROFILE_LONG_RUN_PCT: dict[ProgressionProfile, float] = {
    "cautious": 0.05,
    "balanced": 0.08,
    "ambitious": 0.10,
}

LONG_RUN_SHARE_MAX = 0.40
RECOVERY_REDUCTION = 0.78
POST_RECOVERY_CAP = 1.05
INTRO_DURATION_WEEKS = 3

STARTING_WEEK_KM_NO_HISTORY = 8.0
STARTING_LONG_RUN_KM_NO_HISTORY = 4.0


@dataclass(frozen=True, slots=True)
class VolumePlan:
    """Per-week targets for the whole program."""

    weekly_km: tuple[float, ...]
    long_run_km: tuple[float, ...]
    recovery_weeks: tuple[int, ...]
    taper_weeks: tuple[int, ...]

    def total_km(self) -> float:
        return sum(self.weekly_km)

    def peak_km(self) -> float:
        return max(self.weekly_km)


def starting_weekly_km(
    current_weekly_km: float,
    sessions_per_week: int,
) -> float:
    """Return the volume the first week should land near.

    Beginners with no history get a cautious run/walk start. Everyone else
    starts within 110% of their reported weekly volume, scaled down slightly
    when the runner has fewer than three sessions per week.
    """
    if current_weekly_km <= 0:
        return STARTING_WEEK_KM_NO_HISTORY
    if sessions_per_week >= 4:
        return current_weekly_km
    two_thirds = 2 / 3
    ceiling = current_weekly_km * 1.05
    floor = current_weekly_km * two_thirds
    return max(floor, min(ceiling, current_weekly_km))


def starting_long_run_km(
    current_weekly_km: float,
    current_longest_km: float | None,
) -> float:
    """Return the first-week long-run distance."""
    if current_longest_km is not None and current_longest_km > 0:
        return min(current_longest_km, max(MIN_LONG_RUN_KM, current_weekly_km * 0.40))
    if current_weekly_km <= 0:
        return STARTING_LONG_RUN_KM_NO_HISTORY
    return min(current_weekly_km * 0.40, max(MIN_LONG_RUN_KM, 5.0))


def _cap(value: float, ceiling: float | None) -> float:
    if ceiling is None or value <= ceiling:
        return value
    return ceiling


def build_volume_plan(
    duration_weeks: int,
    current_weekly_km: float,
    current_longest_km: float | None,
    sessions_per_week: int,
    profile: ProgressionProfile,
    max_weekly_km: float | None,
    max_long_run_km: float | None,
) -> VolumePlan:
    """Compute the weekly volume and long-run distances for the program.

    The plan alternates three build weeks and one recovery week, repeats that
    for the duration, and finishes with a peak and a taper. The long-run
    distance grows gently and never exceeds the configured share or cap.
    """
    if max_weekly_km is not None and max_weekly_km < current_weekly_km * 0.5:
        raise GenerationError("max_weekly_km is too low to support the current weekly volume")
    if max_long_run_km is not None and max_long_run_km < MIN_LONG_RUN_KM:
        raise GenerationError(f"max_long_run_km must be at least {MIN_LONG_RUN_KM} km")

    sessions_factor = max(0.7, min(1.0, sessions_per_week / 5))
    starting_week = starting_weekly_km(current_weekly_km, sessions_per_week)
    if max_weekly_km is not None:
        starting_week = min(starting_week, max_weekly_km)
    starting_long = starting_long_run_km(current_weekly_km, current_longest_km)
    if max_long_run_km is not None:
        starting_long = min(starting_long, max_long_run_km)

    base = starting_week * sessions_factor
    week_km: list[float] = []
    long_km: list[float] = []
    previous_week = base
    previous_long = starting_long
    peak_before_recovery = base
    recovery_weeks: list[int] = []
    taper_weeks: list[int] = []
    phases = phase_plan(duration_weeks)

    abs_min = PROFILE_ABS_MIN_KM[profile]
    abs_min_long = PROFILE_LONG_RUN_ABS_MIN_KM[profile]
    pct = PROFILE_INCREMENT[profile]
    long_pct = PROFILE_LONG_RUN_PCT[profile]

    for week in range(1, duration_weeks + 1):
        phase = next(p for p in phases if p.contains(week))
        is_intro = week <= INTRO_DURATION_WEEKS
        if phase.kind is PhaseKind.TAPER:
            factor = 0.60 if duration_weeks <= 9 else 0.55
            target_pre_cap = peak_before_recovery * factor
            taper_weeks.append(week)
            long_target = max(starting_long, previous_long * factor)
        elif week == 1:
            target_pre_cap = base
            long_target = starting_long
        elif week % 4 == 0:
            target_pre_cap = peak_before_recovery * RECOVERY_REDUCTION
            recovery_weeks.append(week)
            long_target = max(MIN_LONG_RUN_KM, previous_long * 0.85)
        elif is_intro:
            increment = max(previous_week * 0.05, abs_min * 0.75)
            target_pre_cap = previous_week + increment
            long_target = max(starting_long, previous_long + max(long_pct * previous_long, 0.5))
        else:
            increment = max(previous_week * pct, abs_min)
            target_pre_cap = previous_week + increment
            long_target = previous_long + max(long_pct * previous_long, abs_min_long)

        target = _cap(target_pre_cap, max_weekly_km)
        if week > 1 and week % 4 != 0 and phase.kind is not PhaseKind.TAPER:
            ceiling = max(target, peak_before_recovery * POST_RECOVERY_CAP)
            target = min(target, ceiling)
        if phase.kind is not PhaseKind.TAPER and week > 1:
            peak_before_recovery = max(peak_before_recovery, target)

        share = target * LONG_RUN_SHARE_MAX
        if long_target > share:
            long_target = share
        if max_long_run_km is not None:
            long_target = min(long_target, max_long_run_km)

        week_km.append(round(target, 2))
        long_km.append(round(long_target, 2))
        previous_week = target
        previous_long = long_target

    return VolumePlan(
        weekly_km=tuple(week_km),
        long_run_km=tuple(long_km),
        recovery_weeks=tuple(recovery_weeks),
        taper_weeks=tuple(taper_weeks),
    )


__all__ = [
    "LONG_RUN_SHARE_MAX",
    "POST_RECOVERY_CAP",
    "RECOVERY_REDUCTION",
    "VolumePlan",
    "build_volume_plan",
    "starting_long_run_km",
    "starting_weekly_km",
]
