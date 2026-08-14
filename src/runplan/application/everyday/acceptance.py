"""Accept a rolling everyday horizon by writing it into the program YAML.

The use case turns each :class:`~runplan.domain.everyday.ProposedDay`
into a new workout record in the runner's program, creates any missing
week blocks, and validates the complete program before persistence.
Validation reuses :func:`runplan.parsing.yaml_loader.load_program_model`
so the same shape rules that the parser enforces apply to the everyday
write path.

The use case is intentionally batch-oriented: it performs one
``save`` at the end rather than calling ``instantiate_recipe`` once per
day.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from ...domain.everyday import EverydayHorizon
from ...parsing.yaml_loader import load_program_model, parse_iso_week
from ..ports import ProgramRepository
from .errors import (
    DAY_CONFLICT,
    DUPLICATE_WORKOUT_ID,
    INVALID_REQUEST,
    UNKNOWN_PROGRAM,
    EverydayError,
)

__all__ = ["AcceptedDay", "AcceptedHorizon", "accept_horizon"]


@dataclass(frozen=True, slots=True)
class AcceptedDay:
    """Summary of one accepted day in the runner's program."""

    date: date
    week: int
    day: int
    workout_id: str
    recipe_key: str


@dataclass(frozen=True, slots=True)
class AcceptedHorizon:
    """Outcome of a successful :func:`accept_horizon` call."""

    program_id: str
    days: tuple[AcceptedDay, ...]


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


def _default_id_allocator(recipe_key: str, week: int, day: int, existing_ids: set[str]) -> str:
    import re

    slug = re.sub(r"[^a-z0-9]+", "-", recipe_key.lower()).strip("-")
    base = f"{slug}-{week:02d}-d{day}"
    if base not in existing_ids:
        return base
    suffix = 2
    while f"{base}-{suffix}" in existing_ids:
        suffix += 1
    return f"{base}-{suffix}"


def _rebuild_workout(
    *,
    workout_id: str,
    day: int,
    schedule_date: date,
    recipe_key: str,
    parameters: Any,
) -> dict[str, Any]:
    """Instantiate the recipe again and convert the typed ``Workout``
    back into a raw YAML dict.

    Calling ``recipe.instantiate`` here keeps the everyday write path
    aligned with the single-recipe ``instantiate_recipe`` use case: the
    same steps, durations, and serialisation rules are produced.
    """
    from ...domain.recipes import get_recipe
    from ..recipes.instantiate import _workout_to_raw_dict

    recipe = get_recipe(recipe_key)
    pair = recipe.instantiate(parameters)
    return _workout_to_raw_dict(
        pair.workout,
        workout_id=workout_id,
        day=day,
        schedule_date=schedule_date,
    )


def _week_and_day_for(target: date, start_date: date) -> tuple[int, int]:
    delta_days = (target - start_date).days
    if delta_days < 0:
        raise EverydayError(
            INVALID_REQUEST,
            f"proposed date {target.isoformat()} is before program start {start_date.isoformat()}",
        )
    week = (delta_days // 7) + 1
    day = target.isoweekday()
    return week, day


def _make_allocator(
    id_allocator: Callable[[set[str]], str] | None,
) -> Callable[[str, set[str]], str]:
    """Return a closure that captures the current recipe + week + day so
    the default id allocator can produce deterministic ids."""
    state: dict[str, int | str] = {}

    def _default(existing_ids: set[str]) -> str:
        return _default_id_allocator(
            state["recipe_key"],  # type: ignore[arg-type]
            state["week"],  # type: ignore[arg-type]
            state["day"],  # type: ignore[arg-type]
            existing_ids,
        )

    def _allocate(recipe_key: str, week: int, day: int, existing_ids: set[str]) -> str:
        if id_allocator is not None:
            return id_allocator(existing_ids)
        state["recipe_key"] = recipe_key
        state["week"] = week
        state["day"] = day
        return _default(existing_ids)

    return _allocate


def accept_horizon(
    horizon: EverydayHorizon,
    *,
    program_id: str,
    repository: ProgramRepository,
    id_allocator: Callable[[set[str]], str] | None = None,
) -> AcceptedHorizon:
    """Write ``horizon`` into the program YAML and return the accepted days.

    The use case adds the proposed weeks in number order, appends each
    proposed workout to its week, validates the complete program, and
    then performs a single ``save`` through the repository. ``id_allocator``
    lets callers override the deterministic id generation; the default
    produces an id of the form ``<recipe-key>-<week>-d<day>`` and
    suffixes with ``-2``, ``-3``, … on collision.
    """
    try:
        raw = repository.load(program_id)
    except KeyError as exc:
        raise EverydayError(
            UNKNOWN_PROGRAM,
            f"program {program_id!r} does not exist",
        ) from exc

    program_block = raw.get("program")
    if not isinstance(program_block, dict):
        raise EverydayError(INVALID_REQUEST, "program block is missing")
    try:
        _, start_date = parse_iso_week(program_block.get("start_week"))
    except ValueError as exc:
        raise EverydayError(INVALID_REQUEST, str(exc)) from exc

    weeks = raw.get("weeks")
    if not isinstance(weeks, list):
        raise EverydayError(INVALID_REQUEST, "program has no weeks list")

    allocate = _make_allocator(id_allocator)

    week_blocks_by_number: dict[int, dict[str, Any]] = {
        week["week"]: week
        for week in weeks
        if isinstance(week, dict) and isinstance(week.get("week"), int)
    }
    proposed_days = sorted(horizon.days, key=lambda day: day.date)
    target_pairs = [_week_and_day_for(day.date, start_date) for day in proposed_days]

    week_numbers = {pair[0] for pair in target_pairs}
    for week_number in sorted(week_numbers - set(week_blocks_by_number)):
        new_block: dict[str, Any] = {"week": week_number, "workouts": []}
        week_blocks_by_number[week_number] = new_block
        weeks.append(new_block)
    weeks.sort(key=lambda item: item.get("week", 0) if isinstance(item, dict) else 0)

    existing_ids = _existing_workout_ids(raw)
    accepted: list[AcceptedDay] = []
    for day, (week, day_num) in zip(proposed_days, target_pairs, strict=True):
        week_block = week_blocks_by_number[week]
        workouts = week_block.setdefault("workouts", [])
        if any(isinstance(item, dict) and item.get("day") == day_num for item in workouts):
            raise EverydayError(
                DAY_CONFLICT,
                f"day {day_num} is already used in week {week}",
            )
        new_id = allocate(day.recipe_key, week, day_num, existing_ids)
        if new_id in existing_ids:
            raise EverydayError(
                DUPLICATE_WORKOUT_ID,
                f"workout id {new_id!r} is already used in program {program_id!r}",
            )
        existing_ids.add(new_id)
        raw_workout = _rebuild_workout(
            workout_id=new_id,
            day=day_num,
            schedule_date=day.date,
            recipe_key=day.recipe_key,
            parameters=day.parameters,
        )
        workouts.append(raw_workout)
        workouts.sort(key=lambda item: item.get("day", 0) if isinstance(item, dict) else 0)
        accepted.append(
            AcceptedDay(
                date=day.date,
                week=week,
                day=day_num,
                workout_id=new_id,
                recipe_key=day.recipe_key,
            )
        )

    try:
        load_program_model(raw)
    except Exception as exc:
        raise EverydayError(INVALID_REQUEST, str(exc)) from exc

    repository.save(program_id, raw)
    return AcceptedHorizon(program_id=program_id, days=tuple(accepted))
