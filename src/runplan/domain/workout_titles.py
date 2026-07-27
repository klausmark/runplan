"""Compact human-readable titles for Garmin workouts."""

from __future__ import annotations

from .estimates import DEFAULT_PACE_SECONDS_PER_KM, WorkoutEstimate, estimate_steps
from .models import Workout


def format_compact_distance(estimate: WorkoutEstimate) -> str:
    """Format estimated meters as a compact kilometer suffix."""
    kilometers = round(estimate.distance_meters / 1000, 1)
    value = f"{kilometers:.1f}".removesuffix(".0")
    prefix = "~" if estimate.distance_is_approximate else ""
    return f"{prefix}{value}k"


def garmin_workout_title(
    short_name: str,
    week: int,
    workout: Workout,
    fallback_pace_seconds_per_km: float = DEFAULT_PACE_SECONDS_PER_KM,
    *,
    workout_name: str | None = None,
) -> str:
    """Build the canonical Garmin title for one presented plan week."""
    estimate = estimate_steps(workout.steps, fallback_pace_seconds_per_km)
    distance = format_compact_distance(estimate)
    return f"{short_name} - W{week} - {workout_name or workout.name} - {distance}"


__all__ = ["format_compact_distance", "garmin_workout_title"]
