"""Serialise a generated program to Runplan YAML.

The serialised YAML reuses the existing schema and round-trips through
``load_program_model``. The composer keeps the program in the typed domain
model so the YAML format mirrors every other bundled program.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import yaml

from ..domain.models import Program, Step, Workout
from ..parsing.yaml_loader import load_program_model
from .plan import GeneratorResult


def program_to_dict(program: Program) -> dict[str, Any]:
    """Return a YAML-compatible dict representation of ``program``."""
    return {
        "program": {
            "id": program.id,
            "name": program.name,
            "short_name": program.short_name,
            "description": program.description,
            "start_week": program.start_week,
        },
        "weeks": [
            {
                "week": week.number,
                "focus": week.focus,
                "workouts": [_workout_to_dict(workout) for workout in week.workouts],
            }
            for week in program.weeks
        ],
    }


def _workout_to_dict(workout: Workout) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": workout.id,
        "day": workout.day,
        "name": workout.name,
        "steps": [_step_to_dict(step) for step in workout.steps],
    }
    if workout.description:
        payload["description"] = workout.description
    return payload


def _step_to_dict(step: Step) -> dict[str, Any]:
    if step.action == "repeat":
        return {
            "repeat": {
                "count": step.count,
                "steps": [_step_to_dict(child) for child in step.steps],
            }
        }
    payload: dict[str, Any] = {step.action: {}}
    if step.end_kind == "time":
        payload[step.action] = {"time": _seconds_to_duration(step.end_value or 0)}
    elif step.end_kind == "distance":
        payload[step.action] = {"distance": _meters_to_distance(step.end_value or 0)}
    if step.pace:
        payload[step.action]["pace"] = (
            f"{_seconds_to_pace(step.pace[0])}-{_seconds_to_pace(step.pace[1])} min/km"
        )
    return payload


def _seconds_to_duration(seconds: float) -> str:
    """Render a duration in seconds as a Runplan duration string."""
    total = int(round(seconds))
    if total % 60 == 0:
        return f"{total // 60}m"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m{secs}s"


def _meters_to_distance(meters: float) -> str:
    """Render a distance in meters as a Runplan distance string."""
    if abs(meters - round(meters)) < 0.1:
        meters = round(meters)
    if meters % 1000 == 0:
        return f"{int(meters // 1000)}km"
    if meters >= 1000:
        km = meters / 1000
        if abs(km - round(km, 1)) < 0.05:
            return f"{km:.1f}km"
        return f"{km:.2f}km"
    return f"{int(round(meters))}m"


def _seconds_to_pace(seconds: float) -> str:
    """Render a pace in seconds per km as 'M:SS'."""
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}"


def plan_to_yaml(result: GeneratorResult) -> str:
    """Return the generated program as a Runplan YAML string."""
    payload = program_to_dict(result.program)
    return yaml.safe_dump(payload, sort_keys=False, allow_unicode=True)


def validate_yaml(yaml_text: str) -> Program:
    """Validate that ``yaml_text`` round-trips through the existing parser."""
    raw = yaml.safe_load(yaml_text)
    if not isinstance(raw, dict):
        raise ValueError("generated YAML did not parse as a program")
    return load_program_model(raw)


def suggested_filename(start_week: str) -> str:
    """Return a stable filename suggestion for the generated YAML."""
    return f"first-10k-{start_week.lower()}.yaml"


def program_start_date(program: Program) -> date:
    """Return the program's first scheduled date."""
    return program.start_date


__all__ = [
    "plan_to_yaml",
    "program_start_date",
    "program_to_dict",
    "suggested_filename",
    "validate_yaml",
]
