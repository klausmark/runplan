"""Construct typed domain models from normalized YAML data."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..domain.errors import WorkoutDefinitionError
from ..domain.models import Program, Step, Week, Workout
from ..domain.steps import normalize_action, repeat_parts
from .values import parse_step_end, step_pace


def _step_model(raw: Any, location: str) -> Step:
    if not isinstance(raw, dict) or len(raw) != 1:
        raise WorkoutDefinitionError(f"{location}: each step must have exactly one action")
    raw_action, value = next(iter(raw.items()))
    action = normalize_action(raw_action, location)
    if action == "repeat":
        count, children = repeat_parts(value, location)
        return Step(
            action="repeat",
            count=count,
            steps=tuple(
                _step_model(child, f"{location}.steps[{index}]")
                for index, child in enumerate(children, start=1)
            ),
        )
    end_kind, end_value = parse_step_end(value, location)
    public_action = "recovery" if action == "walk" else action
    return Step(
        action=public_action,
        end_kind=end_kind,
        end_value=end_value,
        pace=step_pace(value, location),
    )


def program_model(normalized: dict[str, Any]) -> Program:
    """Build a typed domain program from validated normalized data.

    Structural rationale: this is one boundary mapping from normalized dictionaries to
    the immutable domain object graph.
    """
    weeks = tuple(
        Week(
            number=week["number"],
            focus=week.get("focus"),
            workouts=tuple(
                Workout(
                    id=workout["id"],
                    day=workout["day"],
                    name=workout["name"],
                    description=workout.get("description"),
                    steps=tuple(
                        _step_model(step, f"steps[{index}]")
                        for index, step in enumerate(workout["steps"], start=1)
                    ),
                    schedule_date=date.fromisoformat(workout["schedule_date"]),
                    status=workout.get("tracking", {}).get("status", "planned"),
                    garmin_workout_id=workout.get("tracking", {})
                    .get("garmin", {})
                    .get("workout_id"),
                    garmin_schedule_id=workout.get("tracking", {})
                    .get("garmin", {})
                    .get("schedule_id"),
                    activity_id=workout.get("tracking", {}).get("garmin", {}).get("activity_id"),
                    completed_at=workout.get("tracking", {}).get("actual", {}).get("completed_at"),
                    actual_distance_meters=workout.get("tracking", {})
                    .get("actual", {})
                    .get("distance_meters"),
                    actual_duration_seconds=workout.get("tracking", {})
                    .get("actual", {})
                    .get("duration_seconds"),
                )
                for workout in week["workouts"]
            ),
        )
        for week in normalized["weeks"]
    )
    return Program(
        id=normalized["program_id"],
        name=normalized["program_name"],
        short_name=normalized["program_short_name"],
        description=normalized.get("program_description"),
        start_date=date.fromisoformat(normalized["start_date"]),
        start_week=normalized["start_week"],
        weeks=weeks,
    )
