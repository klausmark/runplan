"""Map integration-independent workout steps to Garmin workout models."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from garminconnect.workout import (
    RunningWorkout,
    WorkoutSegment,
    create_cooldown_step,
    create_interval_step,
    create_recovery_step,
    create_repeat_group,
    create_warmup_step,
)

from ...domain.errors import WorkoutDefinitionError
from ...domain.models import Step, Workout
from ...domain.steps import estimate_duration, normalize_action, repeat_parts
from ...parsing.values import parse_step_end, step_note, step_pace, step_pace_type

RUNNING_SPORT = {
    "sportTypeId": 1,
    "sportTypeKey": "running",
    "displayOrder": 1,
}

PaceResolver = Callable[[str], tuple[float, float]]


def add_description(step: Any, text: str) -> Any:
    """Return a Garmin step with its watch-facing description."""
    return step.model_copy(update={"description": text})


def set_step_end(step: Any, kind: str, value: float) -> Any:
    """Set a distance end condition; time is already set by Garmin helpers."""
    if kind == "time":
        return step
    return step.model_copy(
        update={
            "endCondition": {
                "conditionTypeId": 3,
                "conditionTypeKey": "distance",
                "displayOrder": 3,
                "displayable": True,
            },
            "endConditionValue": value,
        }
    )


def set_pace_target(step: Any, pace: tuple[float, float] | None) -> Any:
    """Set a Garmin pace zone whose values are meters per second."""
    if pace is None:
        return step
    fast_seconds_per_km, slow_seconds_per_km = pace
    return step.model_copy(
        update={
            "targetType": {
                "workoutTargetTypeId": 6,
                "workoutTargetTypeKey": "pace.zone",
                "displayOrder": 6,
            },
            "targetValueOne": 1000.0 / slow_seconds_per_km,
            "targetValueTwo": 1000.0 / fast_seconds_per_km,
        }
    )


def compile_steps(
    step_definitions: list[Any],
    location: str = "steps",
    *,
    resolve_pace_type: PaceResolver | None = None,
) -> list[Any]:
    """Recursively compile human-authored steps to Garmin models."""
    compiled: list[Any] = []
    creators = {
        # Warmup and cooldown describe the phase of a workout, not whether the
        # athlete should walk or run.  Keep these watch-facing instructions
        # neutral; beginner plans can prescribe walking in the workout text.
        "warmup": (create_warmup_step, "Warm up"),
        "run": (create_interval_step, "Very easy run"),
        "walk": (create_recovery_step, "Walk"),
        "cooldown": (create_cooldown_step, "Cool down"),
    }
    for order, item in enumerate(step_definitions, start=1):
        item_location = f"{location}[{order}]"
        if not isinstance(item, dict) or len(item) != 1:
            raise WorkoutDefinitionError(f"{item_location}: each step must have exactly one action")
        raw_action, value = next(iter(item.items()))
        action = normalize_action(raw_action, item_location)
        if action == "repeat":
            count, child_steps = repeat_parts(value, item_location)
            compiled.append(
                create_repeat_group(
                    iterations=count,
                    workout_steps=compile_steps(
                        child_steps,
                        location=f"{item_location}.steps",
                        resolve_pace_type=resolve_pace_type,
                    ),
                    step_order=order,
                )
            )
            continue

        kind, end_value = parse_step_end(value, item_location)
        creator, default_description = creators[action]
        step = creator(end_value, step_order=order)
        step = set_step_end(step, kind, end_value)
        pace = step_pace(value, item_location)
        if pace is None:
            label = step_pace_type(value, item_location)
            if label is not None:
                if resolve_pace_type is None:
                    raise WorkoutDefinitionError(
                        f"{item_location}: pace_type {label!r} requires a 5K best resolver"
                    )
                pace = resolve_pace_type(label)
        step = set_pace_target(step, pace)
        note = step_note(value, item_location)
        compiled.append(add_description(step, note if note is not None else default_description))
    return compiled


def _format_pace(seconds: float) -> str:
    minutes, remainder = divmod(round(seconds), 60)
    return f"{minutes}:{remainder:02d}"


def _step_definition(
    step: Step,
    *,
    resolve_pace_type: PaceResolver | None = None,
) -> dict[str, Any]:
    if step.action == "repeat":
        return {
            "repeat": {
                "count": step.count,
                "steps": [
                    _step_definition(child, resolve_pace_type=resolve_pace_type)
                    for child in step.steps
                ],
            }
        }
    assert step.end_kind is not None and step.end_value is not None
    value: dict[str, Any] = {
        step.end_kind: (step.end_value if step.end_kind == "time" else f"{step.end_value:g}m")
    }
    if step.pace is not None:
        fast, slow = step.pace
        value["pace"] = _format_pace(fast)
        if fast != slow:
            value["pace"] += f"-{_format_pace(slow)}"
        value["pace"] += " min/km"
    elif step.pace_type is not None:
        if resolve_pace_type is None:
            raise WorkoutDefinitionError(
                f"step with pace_type {step.pace_type!r} requires a 5K best resolver"
            )
        fast, slow = resolve_pace_type(step.pace_type)
        value["pace"] = f"{_format_pace(fast)}-{_format_pace(slow)} min/km"
    if step.note is not None:
        value["note"] = step.note
    return {step.action: value}


def workout_definition(
    workout: Workout,
    *,
    resolve_pace_type: PaceResolver | None = None,
) -> dict[str, Any]:
    """Map a domain workout to the canonical definition consumed by Garmin."""
    return {
        "id": workout.id,
        "day": workout.day,
        "name": workout.name,
        "description": workout.description,
        "steps": [
            _step_definition(step, resolve_pace_type=resolve_pace_type) for step in workout.steps
        ],
        "schedule_date": workout.schedule_date.isoformat(),
    }


def build_workout(
    definition: dict[str, Any] | Workout,
    *,
    resolve_pace_type: PaceResolver | None = None,
) -> RunningWorkout:
    """Build a typed Garmin running workout."""
    if isinstance(definition, Workout):
        definition = workout_definition(definition, resolve_pace_type=resolve_pace_type)
    segment = WorkoutSegment(
        segmentOrder=1,
        sportType=RUNNING_SPORT,
        workoutSteps=compile_steps(definition["steps"], resolve_pace_type=resolve_pace_type),
    )
    return RunningWorkout(
        workoutName=definition["name"],
        description=definition["description"],
        estimatedDurationInSecs=round(estimate_duration(definition["steps"])),
        workoutSegments=[segment],
    )


__all__ = ["PaceResolver", "build_workout", "compile_steps", "workout_definition"]
