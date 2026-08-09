"""Load and normalize Runplan YAML documents."""

from __future__ import annotations

import re
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..domain.errors import WorkoutDefinitionError
from ..domain.models import Program
from .coaching import parse_coaching
from .yaml_models import program_model
from .yaml_tracking import normalize_tracking


def normalize_workout(raw: Any, location: str) -> dict[str, Any]:
    """Validate and normalize one workout."""
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(f"{location}: must be an object")
    name = raw.get("name")
    description = raw.get("description")
    steps = raw.get("steps")
    if not isinstance(name, str) or not name.strip():
        raise WorkoutDefinitionError(f"{location}.name: must contain the workout name")
    if description is not None and not isinstance(description, str):
        raise WorkoutDefinitionError(f"{location}.description: must be text or null")
    if not isinstance(steps, list) or not steps:
        raise WorkoutDefinitionError(f"{location}.steps: must be a non-empty list")
    result = {
        "name": name.strip(),
        "description": description.strip() if isinstance(description, str) else None,
        "steps": steps,
    }
    if raw.get("tracking") is not None:
        result["tracking"] = normalize_tracking(raw["tracking"], f"{location}.tracking")
    return result


def parse_iso_week(value: Any, location: str = "program.start_week") -> tuple[str, date]:
    """Parse an ISO calendar week and return its canonical label and Monday."""
    if not isinstance(value, str) or not re.fullmatch(r"\d{4}-W\d{2}", value.strip()):
        raise WorkoutDefinitionError(f"{location}: must use YYYY-Www")
    label = value.strip()
    year, week = int(label[:4]), int(label[6:])
    try:
        monday = date.fromisocalendar(year, week, 1)
    except ValueError as exc:
        raise WorkoutDefinitionError(f"{location}: invalid ISO calendar week {label!r}") from exc
    return label, monday


def load_program(raw: dict[str, Any], selected_week: int) -> dict[str, Any]:
    """Validate a program and select one normalized week."""
    program, weeks = _document_sections(raw)
    fields = _program_fields(program)
    normalized_weeks = [
        _normalize_week(week, index, fields["start_date"])
        for index, week in enumerate(weeks, start=1)
    ]
    week_numbers = [week["number"] for week in normalized_weeks]
    if week_numbers != list(range(1, len(weeks) + 1)):
        raise WorkoutDefinitionError(
            f"weeks: week numbers must be contiguous from 1; found {week_numbers}"
        )
    selected = next(
        (week["workouts"] for week in normalized_weeks if week["number"] == selected_week),
        None,
    )
    if not selected:
        raise WorkoutDefinitionError(f"Program does not contain week {selected_week}")
    return {
        **fields,
        "start_date": fields["start_date"].isoformat(),
        "weeks": normalized_weeks,
        "week": selected_week,
        "workouts": selected,
    }


def _document_sections(raw: dict[str, Any]) -> tuple[dict[str, Any], list[Any]]:
    program, weeks = raw.get("program"), raw.get("weeks")
    if not isinstance(program, dict):
        raise WorkoutDefinitionError("Field 'program' must be an object")
    if not isinstance(weeks, list) or not weeks:
        raise WorkoutDefinitionError("Field 'weeks' must be a non-empty list")
    return program, weeks


def _program_fields(program: dict[str, Any]) -> dict[str, Any]:
    program_id = program.get("id")
    if not isinstance(program_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", program_id):
        raise WorkoutDefinitionError("program.id: use lowercase ASCII letters, numbers and hyphens")
    name = program.get("name")
    if not isinstance(name, str) or not name.strip():
        raise WorkoutDefinitionError("program.name: must contain the program name")
    short_name = program.get("short_name")
    if (
        not isinstance(short_name, str)
        or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", short_name.strip())
        or not 2 <= len(short_name.strip()) <= 10
    ):
        raise WorkoutDefinitionError(
            "program.short_name: use 2-10 ASCII letters, numbers, and hyphens"
        )
    description = program.get("description")
    if description is not None and not isinstance(description, str):
        raise WorkoutDefinitionError("program.description: must be text or null")
    start_week, start_date = parse_iso_week(program.get("start_week"))
    if "coaching" in program and not isinstance(program["coaching"], (dict, type(None))):
        raise WorkoutDefinitionError("program.coaching: must be an object or null")
    coaching = parse_coaching(program.get("coaching"))
    return {
        "program_id": program_id,
        "program_name": name.strip(),
        "program_short_name": short_name.strip(),
        "program_description": description.strip() if isinstance(description, str) else None,
        "start_week": start_week,
        "start_date": start_date,
        "coaching": coaching,
    }


def _normalize_week(raw: Any, index: int, start_date: date) -> dict[str, Any]:
    location = f"weeks[{index}]"
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(f"{location}: must be an object")
    number = raw.get("week")
    if isinstance(number, bool) or not isinstance(number, int):
        raise WorkoutDefinitionError(f"{location}.week: must be an integer")
    workouts = raw.get("workouts")
    if not isinstance(workouts, list) or not workouts:
        raise WorkoutDefinitionError(f"{location}.workouts: must be a non-empty list")
    return {
        "number": number,
        "focus": raw.get("focus"),
        "workouts": _normalize_week_workouts(workouts, location, number, start_date),
    }


def _normalize_week_workouts(
    raw_workouts: list[Any], location: str, week: int, start_date: date
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    ids: set[str] = set()
    days: set[int] = set()
    previous_day = 0
    for index, raw in enumerate(raw_workouts, start=1):
        item_location = f"{location}.workouts[{index}]"
        workout_id, day = _workout_identity(raw, item_location, ids, days, previous_day)
        previous_day = day
        workout = normalize_workout(raw, item_location)
        workout.update(
            id=workout_id,
            day=day,
            schedule_date=(start_date + timedelta(days=(week - 1) * 7 + day - 1)).isoformat(),
        )
        result.append(workout)
    return result


def _workout_identity(
    raw: Any, location: str, ids: set[str], days: set[int], previous_day: int
) -> tuple[str, int]:
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(f"{location}: must be an object")
    workout_id = raw.get("id")
    if not isinstance(workout_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", workout_id):
        raise WorkoutDefinitionError(
            f"{location}.id: use lowercase ASCII letters, numbers, and hyphens"
        )
    if workout_id in ids:
        raise WorkoutDefinitionError(
            f"{location}.id: ID {workout_id!r} is already used in the week"
        )
    day = raw.get("day")
    if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7:
        raise WorkoutDefinitionError(f"{location}.day: must be from 1 to 7")
    if day in days:
        raise WorkoutDefinitionError(f"{location}.day: day {day} is already used in the week")
    if day <= previous_day:
        raise WorkoutDefinitionError(
            f"{location.rsplit('.workouts', 1)[0]}.workouts: must be sorted by day"
        )
    ids.add(workout_id)
    days.add(day)
    return workout_id, day


def load_definition(path: Path, selected_week: int = 1) -> dict[str, Any]:
    """Read and validate one complete YAML program file."""
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise WorkoutDefinitionError(f"File not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise WorkoutDefinitionError(f"Could not read YAML file: {exc}") from exc
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(
            "YAML file must be a program with fields 'program' and 'weeks'"
        )
    if "program" not in raw or "weeks" not in raw:
        raise WorkoutDefinitionError(
            "Single-workout format is not supported; the file must contain "
            "both 'program' and 'weeks'"
        )
    return load_program(raw, selected_week)


def load_program_model(raw: dict[str, Any]) -> Program:
    """Validate raw YAML data and return a typed complete program."""
    return program_model(load_program(raw, selected_week=1))


def load_definition_model(path: Path) -> Program:
    """Read a YAML file and return a typed complete program."""
    return program_model(load_definition(path, selected_week=1))


__all__ = [
    "load_definition",
    "load_definition_model",
    "load_program",
    "load_program_model",
    "normalize_workout",
    "parse_iso_week",
    "program_model",
]
