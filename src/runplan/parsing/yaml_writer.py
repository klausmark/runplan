"""Deterministically render typed programs as source-only YAML."""

from __future__ import annotations

from decimal import Decimal
from io import StringIO
from math import isfinite
from typing import Any

from ruamel.yaml import YAML

from ..domain.models import Program, Step


def _decimal_text(value: float) -> str:
    if not isfinite(value):
        raise ValueError("YAML step values must be finite")
    return format(Decimal(str(value)).normalize(), "f")


def _duration_text(seconds: float) -> str:
    value = Decimal(_decimal_text(seconds))
    hours, remainder = divmod(value, Decimal(3600))
    minutes, remainder = divmod(remainder, Decimal(60))
    parts: list[str] = []
    if hours:
        parts.append(f"{hours:f}h")
    if minutes:
        parts.append(f"{minutes:f}m")
    if remainder:
        parts.append(f"{remainder.normalize():f}s")
    return "".join(parts)


def _distance_text(meters: float) -> str:
    value = Decimal(_decimal_text(meters))
    if value >= 1000:
        return f"{(value / 1000).normalize():f}km"
    return f"{value.normalize():f}m"


def _pace_point(seconds: float) -> str:
    if not isfinite(seconds) or not seconds.is_integer() or seconds <= 0:
        raise ValueError("YAML pace values must be positive whole seconds per kilometer")
    minutes, remainder = divmod(int(seconds), 60)
    return f"{minutes}:{remainder:02d}"


def _pace_text(pace: tuple[float, float]) -> str:
    fast, slow = pace
    if fast > slow:
        raise ValueError("YAML pace ranges must be ordered from fast to slow")
    first, second = _pace_point(fast), _pace_point(slow)
    interval = first if first == second else f"{first}-{second}"
    return f"{interval} min/km"


def _step_data(step: Step) -> dict[str, Any]:
    if step.action == "repeat":
        return {
            "repeat": {
                "count": step.count,
                "steps": [_step_data(child) for child in step.steps],
            }
        }

    if step.end_kind == "time":
        value: dict[str, Any] = {"time": _duration_text(step.end_value)}
    else:
        value = {"distance": _distance_text(step.end_value)}
    if step.pace is not None:
        value["pace"] = _pace_text(step.pace)
    return {step.action: value}


def _program_data(program: Program) -> dict[str, Any]:
    program_fields: dict[str, Any] = {
        "id": program.id,
        "name": program.name,
        "short_name": program.short_name,
    }
    if program.description is not None:
        program_fields["description"] = program.description
    program_fields["start_week"] = program.start_week

    weeks = []
    for week in program.weeks:
        week_fields: dict[str, Any] = {"week": week.number}
        if week.focus is not None:
            week_fields["focus"] = week.focus
        workouts = []
        for workout in week.workouts:
            workout_fields: dict[str, Any] = {
                "id": workout.id,
                "day": workout.day,
                "name": workout.name,
            }
            if workout.description is not None:
                workout_fields["description"] = workout.description
            workout_fields["steps"] = [_step_data(step) for step in workout.steps]
            workouts.append(workout_fields)
        week_fields["workouts"] = workouts
        weeks.append(week_fields)
    return {"program": program_fields, "weeks": weeks}


def dump_program_yaml(program: Program) -> str:
    """Return canonical source YAML for a typed program, including a final newline."""
    yaml = YAML()
    yaml.default_flow_style = False
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    stream = StringIO()
    yaml.dump(_program_data(program), stream)
    return stream.getvalue()


__all__ = ["dump_program_yaml"]
