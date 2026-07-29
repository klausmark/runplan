"""Shared estimates for structured workouts."""

from __future__ import annotations

from dataclasses import dataclass

from .models import Step

DEFAULT_PACE_SECONDS_PER_KM = 6 * 60


@dataclass(frozen=True, slots=True)
class WorkoutEstimate:
    duration_seconds: float
    distance_meters: float
    distance_is_approximate: bool
    duration_is_approximate: bool


def estimate_steps(
    steps: tuple[Step, ...],
    fallback_pace_seconds_per_km: float = DEFAULT_PACE_SECONDS_PER_KM,
) -> WorkoutEstimate:
    """Estimate complete totals and record use of fallback pace for distance."""
    duration = 0.0
    distance = 0.0
    distance_is_approximate = False
    duration_is_approximate = False
    for step in steps:
        if step.action == "repeat":
            child = estimate_steps(step.steps, fallback_pace_seconds_per_km)
            count = step.count or 0
            duration += count * child.duration_seconds
            distance += count * child.distance_meters
            distance_is_approximate = distance_is_approximate or (
                count > 0 and child.distance_is_approximate
            )
            duration_is_approximate = duration_is_approximate or (
                count > 0 and child.duration_is_approximate
            )
        elif step.end_kind == "time":
            seconds = step.end_value or 0
            duration += seconds
            # Recoveries represent pauses and do not contribute running distance.
            if step.action != "recovery":
                if step.pace:
                    pace = sum(step.pace) / len(step.pace)
                else:
                    pace = fallback_pace_seconds_per_km
                    distance_is_approximate = True
                distance += seconds / pace * 1000
        elif step.end_kind == "distance":
            meters = step.end_value or 0
            distance += meters
            pace = sum(step.pace) / len(step.pace) if step.pace else fallback_pace_seconds_per_km
            if not step.pace:
                duration_is_approximate = True
            duration += meters / 1000 * pace
    return WorkoutEstimate(
        duration,
        distance,
        distance_is_approximate,
        duration_is_approximate,
    )


__all__ = ["DEFAULT_PACE_SECONDS_PER_KM", "WorkoutEstimate", "estimate_steps"]
