"""Load and normalize Runplan YAML documents."""

from __future__ import annotations

import re
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from ..domain.errors import WorkoutDefinitionError
from ..domain.models import Program, Step, Week, Workout
from ..domain.steps import normalize_action, repeat_parts
from .values import parse_step_end, step_pace


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
    tracking = raw.get("tracking")
    if tracking is not None:
        if not isinstance(tracking, dict):
            raise WorkoutDefinitionError(f"{location}.tracking: must be an object")
        status = tracking.get("status")
        if status not in {"planned", "scheduled", "completed", "missed", "retired"}:
            raise WorkoutDefinitionError(f"{location}.tracking.status: invalid status")
        normalized_tracking = dict(tracking)
        synced_week = tracking.get("synced_week")
        if synced_week is not None and (
            not isinstance(synced_week, int) or isinstance(synced_week, bool) or synced_week <= 0
        ):
            raise WorkoutDefinitionError(
                f"{location}.tracking.synced_week: must be a positive integer"
            )
        scheduled_date = tracking.get("scheduled_date")
        if scheduled_date is not None:
            try:
                if isinstance(scheduled_date, datetime):
                    raise ValueError
                parsed_date = (
                    scheduled_date
                    if isinstance(scheduled_date, date)
                    else date.fromisoformat(scheduled_date)
                )
            except (TypeError, ValueError) as exc:
                raise WorkoutDefinitionError(
                    f"{location}.tracking.scheduled_date: must be an ISO date"
                ) from exc
            normalized_tracking["scheduled_date"] = parsed_date.isoformat()
        content_hash = tracking.get("synced_content_hash")
        if content_hash is not None and (
            not isinstance(content_hash, str)
            or re.fullmatch(r"[0-9a-fA-F]{64}", content_hash) is None
        ):
            raise WorkoutDefinitionError(
                f"{location}.tracking.synced_content_hash: must be a SHA-256 hash"
            )
        garmin = tracking.get("garmin")
        if garmin is not None:
            if not isinstance(garmin, dict):
                raise WorkoutDefinitionError(f"{location}.tracking.garmin: must be an object")
            for field in ("workout_id", "schedule_id", "activity_id"):
                value = garmin.get(field)
                if value is not None and (
                    not isinstance(value, int) or isinstance(value, bool) or value <= 0
                ):
                    raise WorkoutDefinitionError(
                        f"{location}.tracking.garmin.{field}: must be a positive integer"
                    )
        actual = tracking.get("actual")
        if actual is not None and not isinstance(actual, dict):
            raise WorkoutDefinitionError(f"{location}.tracking.actual: must be an object")
        if status == "completed":
            if not isinstance(actual, dict):
                raise WorkoutDefinitionError(f"{location}.tracking.actual: required when completed")
            for field in ("distance_meters", "duration_seconds"):
                value = actual.get(field)
                if not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0:
                    raise WorkoutDefinitionError(
                        f"{location}.tracking.actual.{field}: must be positive"
                    )
        elif isinstance(actual, dict):
            for field in ("distance_meters", "duration_seconds"):
                value = actual.get(field)
                if value is not None and (
                    not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
                ):
                    raise WorkoutDefinitionError(
                        f"{location}.tracking.actual.{field}: must be positive"
                    )
        if isinstance(actual, dict):
            normalized_actual = dict(actual)
            completed_at = actual.get("completed_at")
            if completed_at is not None:
                try:
                    parsed_completed = (
                        completed_at
                        if isinstance(completed_at, datetime)
                        else datetime.fromisoformat(completed_at)
                    )
                except (TypeError, ValueError) as exc:
                    raise WorkoutDefinitionError(
                        f"{location}.tracking.actual.completed_at: must be an ISO timestamp"
                    ) from exc
                normalized_actual["completed_at"] = parsed_completed.isoformat()
            normalized_tracking["actual"] = normalized_actual
        result["tracking"] = normalized_tracking
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
    program = raw.get("program")
    weeks = raw.get("weeks")
    if not isinstance(program, dict):
        raise WorkoutDefinitionError("Field 'program' must be an object")
    if not isinstance(weeks, list) or not weeks:
        raise WorkoutDefinitionError("Field 'weeks' must be a non-empty list")

    program_id = program.get("id")
    if not isinstance(program_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", program_id):
        raise WorkoutDefinitionError("program.id: use lowercase ASCII letters, numbers and hyphens")
    program_name = program.get("name")
    if not isinstance(program_name, str) or not program_name.strip():
        raise WorkoutDefinitionError("program.name: must contain the program name")
    program_short_name = program.get("short_name")
    if (
        not isinstance(program_short_name, str)
        or not re.fullmatch(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*", program_short_name.strip())
        or not 2 <= len(program_short_name.strip()) <= 10
    ):
        raise WorkoutDefinitionError(
            "program.short_name: use 2-10 ASCII letters, numbers, and hyphens"
        )
    program_description = program.get("description")
    if program_description is not None and not isinstance(program_description, str):
        raise WorkoutDefinitionError("program.description: must be text or null")
    start_week, start_date = parse_iso_week(program.get("start_week"))

    week_numbers: list[int] = []
    selected: list[dict[str, Any]] = []
    normalized_weeks: list[dict[str, Any]] = []

    for week_index, week in enumerate(weeks, start=1):
        week_location = f"weeks[{week_index}]"
        if not isinstance(week, dict):
            raise WorkoutDefinitionError(f"{week_location}: must be an object")
        week_number = week.get("week")
        if isinstance(week_number, bool) or not isinstance(week_number, int):
            raise WorkoutDefinitionError(f"{week_location}.week: must be an integer")
        week_numbers.append(week_number)

        workouts = week.get("workouts")
        if not isinstance(workouts, list) or not workouts:
            raise WorkoutDefinitionError(f"{week_location}.workouts: must be a non-empty list")

        ids: set[str] = set()
        days: set[int] = set()
        previous_day = 0
        normalized_workouts: list[dict[str, Any]] = []
        for workout_index, workout_raw in enumerate(workouts, start=1):
            workout_location = f"{week_location}.workouts[{workout_index}]"
            if not isinstance(workout_raw, dict):
                raise WorkoutDefinitionError(f"{workout_location}: must be an object")

            workout_id = workout_raw.get("id")
            if not isinstance(workout_id, str) or not re.fullmatch(
                r"[a-z0-9]+(?:-[a-z0-9]+)*", workout_id
            ):
                raise WorkoutDefinitionError(
                    f"{workout_location}.id: use lowercase ASCII letters, numbers, and hyphens"
                )
            if workout_id in ids:
                raise WorkoutDefinitionError(
                    f"{workout_location}.id: ID {workout_id!r} is already used in the week"
                )
            ids.add(workout_id)

            day = workout_raw.get("day")
            if isinstance(day, bool) or not isinstance(day, int) or not 1 <= day <= 7:
                raise WorkoutDefinitionError(f"{workout_location}.day: must be from 1 to 7")
            if day in days:
                raise WorkoutDefinitionError(
                    f"{workout_location}.day: day {day} is already used in the week"
                )
            if day <= previous_day:
                raise WorkoutDefinitionError(f"{week_location}.workouts: must be sorted by day")
            days.add(day)
            previous_day = day

            workout = normalize_workout(workout_raw, workout_location)
            workout["id"] = workout_id
            workout["day"] = day
            workout["schedule_date"] = (
                start_date + timedelta(days=(week_number - 1) * 7 + day - 1)
            ).isoformat()
            normalized_workouts.append(workout)

        normalized_week = {
            "number": week_number,
            "focus": week.get("focus"),
            "workouts": normalized_workouts,
        }
        normalized_weeks.append(normalized_week)
        if week_number == selected_week:
            selected.extend(normalized_workouts)

    expected_weeks = list(range(1, len(weeks) + 1))
    if week_numbers != expected_weeks:
        raise WorkoutDefinitionError(
            f"weeks: week numbers must be contiguous from 1; found {week_numbers}"
        )
    if not selected:
        raise WorkoutDefinitionError(f"Program does not contain week {selected_week}")

    return {
        "program_id": program_id,
        "program_name": program_name.strip(),
        "program_short_name": program_short_name.strip(),
        "program_description": (
            program_description.strip() if isinstance(program_description, str) else None
        ),
        "start_date": start_date.isoformat(),
        "start_week": start_week,
        "weeks": normalized_weeks,
        "week": selected_week,
        "workouts": selected,
    }


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
    """Build a typed domain program from validated normalized data."""
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
