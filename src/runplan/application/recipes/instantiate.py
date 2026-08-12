"""Connect recipes to program editing.

Step 6 turns a recipe, its parameters, and a target week/day into a
new explicit :class:`~runplan.domain.models.Workout` placed inside a
program's YAML document. The use case is intentionally web-agnostic:
callers inject a :class:`ProgramRepository` port that loads and saves
the raw YAML document, and the use case handles the round-trip through
the existing parser for validation.

Structural rationale: this module is one use case with a single reason
to change (recipe insertion); it keeps the YAML serialisation private
because the inverse of the parser does not belong in the domain layer.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Any

from ...domain.errors import WorkoutDefinitionError
from ...domain.models import Step, Workout
from ...domain.recipes import RecipeParameters, WorkoutRecipe, get_recipe
from ...domain.workout_form import WorkoutWithForm
from ...parsing.yaml_loader import load_program_model
from ..ports import ProgramRepository

__all__ = [
    "InstantiateRecipeError",
    "InstantiateRecipeResult",
    "instantiate_recipe",
]


@dataclass(frozen=True, slots=True)
class InstantiateRecipeResult:
    """Outcome of a successful :func:`instantiate_recipe` call."""

    workout_with_form: WorkoutWithForm
    recipe_key: str
    week: int
    day: int
    schedule_date: date


class InstantiateRecipeError(WorkoutDefinitionError):
    """Raised when :func:`instantiate_recipe` cannot complete.

    ``kind`` identifies the failure mode so callers can map it to a
    user-facing error. ``message`` is the human-readable explanation.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message

    def __str__(self) -> str:
        return self.message


_ID_PATTERN_REPLACEMENT = "-"
_VALID_WEEK_RANGE = range(1, 1_000)
_VALID_DAY_RANGE = range(1, 8)
_INVALID_WEEK = "invalid_week"
_INVALID_DAY = "invalid_day"
_OCCUPIED_DAY = "occupied_day"
_UNKNOWN_PROGRAM = "unknown_program"
_UNKNOWN_RECIPE = "unknown_recipe"
_INVALID_PARAMETERS = "invalid_parameters"
_DUPLICATE_WORKOUT_ID = "duplicate_workout_id"
_INVALID_PROGRAM = "invalid_program"


def _default_id_allocator(recipe_key: str, week: int, day: int, existing_ids: set[str]) -> str:
    """Return a deterministic workout id, suffixing on collision."""
    import re

    slug = re.sub(r"[^a-z0-9]+", _ID_PATTERN_REPLACEMENT, recipe_key.lower()).strip("-")
    base = f"{slug}-{week:02d}-d{day}"
    if base not in existing_ids:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base}-{suffix}"


def _schedule_date(start_date: date, week: int, day: int) -> date:
    return start_date + timedelta(days=(week - 1) * 7 + (day - 1))


def _seconds_to_duration(seconds: float) -> str:
    total = int(round(seconds))
    if total <= 0:
        raise InstantiateRecipeError(
            "invalid_step",
            f"step duration must be greater than 0; got {seconds!r}",
        )
    if total % 60 == 0:
        return f"{total // 60}m"
    minutes, secs = divmod(total, 60)
    return f"{minutes}m{secs}s"


def _meters_to_distance(meters: float) -> str:
    if meters <= 0:
        raise InstantiateRecipeError(
            "invalid_step",
            f"step distance must be greater than 0; got {meters!r}",
        )
    if meters % 1000 == 0:
        return f"{int(meters // 1000)}km"
    if meters >= 1000:
        km = meters / 1000
        return f"{km:.1f}km"
    return f"{int(round(meters))}m"


def _seconds_to_pace(seconds: float) -> str:
    total = int(round(seconds))
    return f"{total // 60}:{total % 60:02d}"


def _pace_to_string(pace: tuple[float, float]) -> str:
    if pace[0] == pace[1]:
        return f"{_seconds_to_pace(pace[0])} min/km"
    return f"{_seconds_to_pace(pace[0])}-{_seconds_to_pace(pace[1])} min/km"


def _step_to_raw_dict(step: Step) -> dict[str, Any]:
    if step.action == "repeat":
        return {
            "repeat": {
                "count": step.count,
                "steps": [_step_to_raw_dict(child) for child in step.steps],
            }
        }
    end_spec: dict[str, Any] = {}
    if step.end_kind == "time":
        end_spec["time"] = _seconds_to_duration(step.end_value or 0.0)
    elif step.end_kind == "distance":
        end_spec["distance"] = _meters_to_distance(step.end_value or 0.0)
    if step.pace is not None:
        end_spec["pace"] = _pace_to_string(step.pace)
    elif step.pace_type is not None:
        end_spec["pace_type"] = step.pace_type
    if step.note is not None:
        end_spec["note"] = step.note
    return {step.action: end_spec}


def _workout_to_raw_dict(
    workout: Workout,
    *,
    workout_id: str,
    day: int,
    schedule_date: date,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": workout_id,
        "day": day,
        "name": workout.name,
        "steps": [_step_to_raw_dict(step) for step in workout.steps],
    }
    if workout.description:
        payload["description"] = workout.description
    payload["schedule_date"] = schedule_date.isoformat()
    return payload


def _existing_workout_ids(raw: dict[str, Any]) -> set[str]:
    ids: set[str] = set()
    for week in raw.get("weeks", []):
        if not isinstance(week, dict):
            continue
        for workout in week.get("workouts", []):
            if not isinstance(workout, dict):
                continue
            workout_id = workout.get("id")
            if isinstance(workout_id, str):
                ids.add(workout_id)
    return ids


def _validate_target(
    raw: dict[str, Any], week: int, day: int
) -> tuple[dict[str, Any], dict[str, Any]]:
    if week not in _VALID_WEEK_RANGE:
        raise InstantiateRecipeError(_INVALID_WEEK, f"week {week} is outside the supported range")
    if day not in _VALID_DAY_RANGE:
        raise InstantiateRecipeError(_INVALID_DAY, "day must be from 1 to 7")
    weeks = raw.get("weeks")
    if not isinstance(weeks, list) or not weeks:
        raise InstantiateRecipeError(_INVALID_PROGRAM, "program has no weeks")
    week_block = next(
        (item for item in weeks if isinstance(item, dict) and item.get("week") == week),
        None,
    )
    if week_block is None:
        raise InstantiateRecipeError(
            _INVALID_WEEK,
            f"program does not contain week {week}",
        )
    workouts = week_block.get("workouts")
    if not isinstance(workouts, list):
        raise InstantiateRecipeError(
            _INVALID_PROGRAM,
            f"week {week} workouts must be a list",
        )
    occupied = next(
        (item for item in workouts if isinstance(item, dict) and item.get("day") == day),
        None,
    )
    if occupied is not None:
        raise InstantiateRecipeError(
            _OCCUPIED_DAY,
            f"day {day} is already used in week {week}",
        )
    return week_block, week_block  # both references; kept for clarity


def instantiate_recipe(
    *,
    program_id: str,
    recipe_key: str,
    parameters: RecipeParameters,
    week: int,
    day: int,
    repository: ProgramRepository,
    id_allocator: Callable[[set[str]], str] | None = None,
) -> InstantiateRecipeResult:
    """Insert a recipe into ``program_id`` at ``week`` / ``day``.

    ``parameters`` must be the typed dataclass accepted by the recipe
    (``recipe.parameters_type()``). ``id_allocator`` lets callers override
    the deterministic id generation; the default produces an id of the
    form ``<recipe-key>-<week>-d<day>`` and suffixes with ``-2``, ``-3``,
    … on collision.

    The complete program is revalidated before persistence so a bad
    recipe or an inconsistent target surfaces as
    :class:`InstantiateRecipeError` without touching the repository.
    """
    try:
        raw = repository.load(program_id)
    except KeyError as exc:
        raise InstantiateRecipeError(
            _UNKNOWN_PROGRAM,
            f"program {program_id!r} does not exist",
        ) from exc

    try:
        recipe: WorkoutRecipe = get_recipe(recipe_key)
    except KeyError as exc:
        raise InstantiateRecipeError(
            _UNKNOWN_RECIPE,
            f"unknown recipe key {recipe_key!r}",
        ) from exc

    if not isinstance(parameters, recipe.parameters_type):
        raise InstantiateRecipeError(
            _INVALID_PARAMETERS,
            f"recipe {recipe_key!r} expects "
            f"{recipe.parameters_type.__name__}, got {type(parameters).__name__}",
        )

    try:
        pair = recipe.instantiate(parameters)
    except WorkoutDefinitionError as exc:
        raise InstantiateRecipeError(_INVALID_PARAMETERS, str(exc)) from exc
    except ValueError as exc:
        raise InstantiateRecipeError(_INVALID_PARAMETERS, str(exc)) from exc

    week_block, _ = _validate_target(raw, week, day)

    existing_ids = _existing_workout_ids(raw)
    allocator = id_allocator or (lambda ids: _default_id_allocator(recipe_key, week, day, ids))
    workout_id = allocator(existing_ids)
    if workout_id in existing_ids:
        raise InstantiateRecipeError(
            _DUPLICATE_WORKOUT_ID,
            f"workout id {workout_id!r} is already used in program {program_id!r}",
        )

    start_date = _resolve_start_date(raw)
    schedule = _schedule_date(start_date, week, day)

    raw_workout = _workout_to_raw_dict(
        pair.workout, workout_id=workout_id, day=day, schedule_date=schedule
    )
    week_block.setdefault("workouts", []).append(raw_workout)
    week_block["workouts"].sort(key=lambda item: item.get("day", 0))

    try:
        load_program_model(raw)
    except WorkoutDefinitionError as exc:
        raise InstantiateRecipeError(_INVALID_PROGRAM, str(exc)) from exc

    repository.save(program_id, raw)

    scheduled_workout = replace(
        pair.workout,
        id=workout_id,
        day=day,
        schedule_date=schedule,
    )
    return InstantiateRecipeResult(
        workout_with_form=WorkoutWithForm(workout=scheduled_workout, form=pair.form),
        recipe_key=recipe_key,
        week=week,
        day=day,
        schedule_date=schedule,
    )


def _resolve_start_date(raw: dict[str, Any]) -> date:
    program = raw.get("program")
    if not isinstance(program, dict):
        raise InstantiateRecipeError(_INVALID_PROGRAM, "program metadata must be an object")
    start_week = program.get("start_week")
    if not isinstance(start_week, str):
        raise InstantiateRecipeError(_INVALID_PROGRAM, "program.start_week must be a string")
    from ...parsing.yaml_loader import parse_iso_week

    _, monday = parse_iso_week(start_week)
    return monday
