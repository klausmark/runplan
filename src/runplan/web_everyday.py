"""HTTP adapter for the Studio rolling-plan flow.

Step 11 surfaces the Step 10 ``propose_horizon`` and ``accept_horizon``
use cases inside the Studio. The adapter owns four responsibilities:

- validate the JSON payload (``goal``, ``training_days``, ``start_date``,
  ``horizon_days``), rejecting unknown values with HTTP 400s the Studio
  can surface;
- bridge the program record into a :class:`YamlProgramRepository` so the
  use cases can read and write the raw YAML document without knowing
  about the web filesystem;
- enrich every :class:`ProposedDay` with the recipe's estimate (distance
  and duration) so the dialog can render day cards without a separate
  ``/api/recipes/preview`` round-trip per day; and
- serialise :class:`EverydayHorizon` and :class:`AcceptedHorizon` back
  into JSON-friendly shapes the frontend already consumes through the
  recipe and coaching surfaces.

Structural rationale: one HTTP-facing module with one reason to change
(the rolling-plan endpoint surface). It depends only on the application
layer and the recipe catalogue — it does not know how the program is
stored at the web boundary.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date, timedelta
from http import HTTPStatus
from typing import Any

from .application.everyday import (
    EverydayError,
    accept_horizon,
    horizon_from_payload,
    horizon_to_payload,
    propose_horizon,
)
from .application.ports import ProgramRepository
from .domain.estimates import DEFAULT_PACE_SECONDS_PER_KM, estimate_steps
from .domain.everyday import EverydayGoal, EverydayProfile
from .domain.recipes import get_recipe
from .domain.recipes.base import RecipeInstantiationError
from .parsing.yaml_loader import load_program_model
from .users import RunplanUser, WebError, fallback_pace_seconds_per_km, five_k_pace_seconds
from .web_yaml import load_editable_yaml

__all__ = [
    "EverydayRequestError",
    "DEFAULT_TRAINING_DAYS",
    "DEFAULT_HORIZON_DAYS",
    "accept_response",
    "propose_response",
]


DEFAULT_TRAINING_DAYS: tuple[int, ...] = (1, 3, 5, 6)
"""Weekday pattern offered by default in the Studio rolling-plan dialog.

The same Mon/Wed/Fri/Sat pattern that a first-10K generator exposes;
Step 12 will replace this default with a runner preference.
"""

DEFAULT_HORIZON_DAYS = 14


class EverydayRequestError(WebError):
    """Raised when a rolling-plan request cannot be served."""


def _parse_program_text(program_file: str, program_text: str) -> dict[str, Any]:
    if not isinstance(program_text, str) or not program_text.strip():
        raise EverydayRequestError(HTTPStatus.NOT_FOUND, f"Program {program_file!r} is empty")
    try:
        raw = load_editable_yaml(program_text)
    except Exception as exc:  # ruamel.yaml raises YAMLError
        raise EverydayRequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid program YAML: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise EverydayRequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Program YAML must be an object"
        )
    return raw


def _parse_goal(value: Any) -> str:
    from .domain.everyday import _everyday_goal_values

    if value is None or value == "":
        return "maintain"
    if not isinstance(value, str):
        raise EverydayRequestError(HTTPStatus.BAD_REQUEST, f"goal must be a string; got {value!r}")
    cleaned = value.strip().lower()
    if cleaned not in _everyday_goal_values():
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST,
            f"goal must be one of {_everyday_goal_values()}; got {value!r}",
        )
    return cleaned


def _parse_training_days(value: Any) -> tuple[int, ...]:
    if value is None:
        return DEFAULT_TRAINING_DAYS
    if not isinstance(value, list):
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST,
            "training_days must be a list of integers 1-7",
        )
    try:
        cleaned = sorted({int(item) for item in value})
    except (TypeError, ValueError) as exc:
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST, f"training_days must be integers 1-7; got {value!r}"
        ) from exc
    for day in cleaned:
        if not 1 <= day <= 7:
            raise EverydayRequestError(
                HTTPStatus.BAD_REQUEST,
                f"training_days entries must be 1-7; got {day!r}",
            )
    if not cleaned:
        return DEFAULT_TRAINING_DAYS
    return tuple(cleaned)


def _parse_start_date(value: Any, *, today: date) -> date:
    if value is None or value == "":
        return today
    if not isinstance(value, str):
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST, f"start_date must use YYYY-MM-DD; got {value!r}"
        )
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST, f"start_date must use YYYY-MM-DD; got {value!r}"
        ) from exc


def _parse_horizon_days(value: Any) -> int:
    if value is None or value == "":
        return DEFAULT_HORIZON_DAYS
    if isinstance(value, bool):
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST, f"horizon_days must be a positive integer; got {value!r}"
        )
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST, f"horizon_days must be a positive integer; got {value!r}"
        ) from exc
    if parsed <= 0 or parsed > 28:
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST,
            f"horizon_days must be between 1 and 28; got {parsed}",
        )
    return parsed


def _resolve_program_start(raw: dict[str, Any]) -> date:
    """Return the Monday after the last program week (or program start).

    Mirrors :func:`runplan.cli._resolve_horizon_start` so the Studio
    defaults match the CLI exactly.
    """
    from .parsing.yaml_loader import parse_iso_week

    try:
        model = load_program_model(raw)
    except Exception as exc:
        raise EverydayRequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid program: {exc}"
        ) from exc
    _, start_date = parse_iso_week(model.start_week)
    weeks = sorted(model.weeks, key=lambda week: week.number)
    if not weeks:
        raise EverydayRequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "program has no weeks; cannot derive a horizon start"
        )
    last_week = weeks[-1]
    return start_date + timedelta(days=last_week.number * 7)


def _build_profile(*, five_k_best: str, training_days: tuple[int, ...]) -> EverydayProfile:
    five_k_seconds = 0.0
    if isinstance(five_k_best, str) and five_k_best.strip():
        try:
            five_k_seconds = five_k_pace_seconds(five_k_best) * 5.0
        except ValueError:
            five_k_seconds = 0.0
    return EverydayProfile(
        five_k_seconds=five_k_seconds,
        weekly_km_target=0.0,
        training_days=training_days,
        preferred_long_run_day=None,
    )


def _fallback_pace_seconds(five_k_best: str) -> float:
    try:
        return fallback_pace_seconds_per_km(five_k_best)
    except ValueError:
        return DEFAULT_PACE_SECONDS_PER_KM


def _estimate_for_day(recipe_key: str, parameters: Any) -> dict[str, Any] | None:
    """Return distance/duration estimate for one proposed day, or ``None``."""
    try:
        recipe = get_recipe(recipe_key)
    except KeyError:
        return None
    try:
        pair = recipe.instantiate(parameters)
    except RecipeInstantiationError:
        return None
    except Exception:
        return None
    estimate = estimate_steps(pair.workout.steps, DEFAULT_PACE_SECONDS_PER_KM)
    return {
        "estimated_distance_meters": estimate.distance_meters,
        "estimated_duration_seconds": estimate.duration_seconds,
        "distance_is_approximate": estimate.distance_is_approximate,
        "duration_is_approximate": estimate.duration_is_approximate,
    }


def _serialise_day(day) -> dict[str, Any]:
    payload = {
        "date": day.date.isoformat(),
        "weekday": day.date.isoweekday(),
        "form": day.form.name,
        "form_label": day.form.label,
        "recipe_key": day.recipe_key,
        "recipe_label": get_recipe(day.recipe_key).label,
        "parameters": _parameters_to_dict(day.parameters),
        "reasoning": list(day.reasoning),
        "warnings": list(day.warnings),
    }
    estimate = _estimate_for_day(day.recipe_key, day.parameters)
    if estimate is not None:
        payload["estimate"] = estimate
    return payload


def _parameters_to_dict(parameters: Any) -> dict[str, Any]:
    if parameters is None:
        return {}
    if is_dataclass(parameters):
        return asdict(parameters)
    if isinstance(parameters, Mapping):
        return {str(key): value for key, value in parameters.items()}
    return {}


def _group_by_week(days: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group days by ISO week number so the dialog can render week sections."""
    buckets: dict[int, list[dict[str, Any]]] = {}
    for day in days:
        iso_year, iso_week, _ = date.fromisoformat(day["date"]).isocalendar()
        key = iso_year * 100 + iso_week
        buckets.setdefault(key, []).append(day)
    groups: list[dict[str, Any]] = []
    for key in sorted(buckets):
        entries = sorted(buckets[key], key=lambda entry: entry["date"])
        iso_year = key // 100
        iso_week = key % 100
        groups.append(
            {
                "iso_year": iso_year,
                "iso_week": iso_week,
                "label": f"Week {iso_week} · {iso_year}",
                "days": entries,
            }
        )
    return groups


def propose_response(
    payload: Mapping[str, Any],
    *,
    user: RunplanUser,
    program_file: str,
    program_text: str,
    today: date,
    repository: ProgramRepository,
) -> dict[str, Any]:
    """Return the JSON-friendly proposed horizon for one Studio request.

    ``repository`` is injected so the web handler can pass the on-disk
    :class:`YamlProgramRepository` in production and tests can pass an
    in-memory implementation. ``today`` lets tests pin the "today"
    assumption deterministically. The default ``start_date`` is the
    Monday after the program's last week.
    """
    raw_program = _parse_program_text(program_file, program_text)
    goal: EverydayGoal = _parse_goal(payload.get("goal"))  # type: ignore[assignment]
    training_days = _parse_training_days(payload.get("training_days"))
    horizon_days = _parse_horizon_days(payload.get("horizon_days"))
    explicit_start = payload.get("start_date")
    if explicit_start in (None, ""):
        start_date = _resolve_program_start(raw_program)
    else:
        start_date = _parse_start_date(explicit_start, today=today)
    profile = _build_profile(five_k_best=user.five_k_best, training_days=training_days)

    try:
        horizon = propose_horizon(
            program_id=_program_id_for(raw_program),
            profile=profile,
            goal=goal,
            start_date=start_date,
            horizon_days=horizon_days,
            repository=repository,
            today=today,
        )
    except EverydayError as exc:
        status = HTTPStatus.BAD_REQUEST
        if exc.kind in {"invalid_request"}:
            status = HTTPStatus.UNPROCESSABLE_ENTITY
        raise EverydayRequestError(status, str(exc)) from exc

    serialised_days = [_serialise_day(day) for day in horizon.days]
    return {
        "program_file": program_file,
        "goal": horizon.goal,
        "start_date": horizon.start_date.isoformat(),
        "horizon_days": horizon.horizon_days,
        "today": today.isoformat(),
        "pace_seconds_per_km": _fallback_pace_seconds(user.five_k_best),
        "days": serialised_days,
        "weeks": _group_by_week(serialised_days),
        "horizon_payload": horizon_to_payload(horizon),
    }


def _program_id_for(raw: dict[str, Any]) -> str:
    program_block = raw.get("program")
    if not isinstance(program_block, dict):
        raise EverydayRequestError(HTTPStatus.UNPROCESSABLE_ENTITY, "program block is missing")
    program_id = program_block.get("id")
    if not isinstance(program_id, str) or not program_id:
        raise EverydayRequestError(HTTPStatus.UNPROCESSABLE_ENTITY, "program.id is missing")
    return program_id


def _parse_horizon_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise EverydayRequestError(HTTPStatus.BAD_REQUEST, "horizon payload must be an object")
    return value


def accept_response(
    payload: Mapping[str, Any],
    *,
    user: RunplanUser,
    program_file: str,
    program_text: str,
    repository: ProgramRepository,
) -> dict[str, Any]:
    """Accept the proposed horizon and return the accepted-day summary.

    ``repository`` is injected so the web handler can pass an in-memory
    implementation in tests and the on-disk
    :class:`YamlProgramRepository` in production. ``program_text`` is
    the in-memory YAML the handler already loaded; the adapter reads
    ``program.id`` from it so the use case can validate the repository
    round-trip without an extra filesystem hit.
    """
    raw_program = _parse_program_text(program_file, program_text)
    program_id = _program_id_for(raw_program)
    horizon_payload = _parse_horizon_payload(payload.get("horizon"))
    try:
        horizon = horizon_from_payload(horizon_payload)
    except (KeyError, ValueError, TypeError) as exc:
        raise EverydayRequestError(
            HTTPStatus.BAD_REQUEST, f"Invalid horizon payload: {exc}"
        ) from exc

    try:
        result = accept_horizon(horizon, program_id=program_id, repository=repository)
    except EverydayError as exc:
        status = HTTPStatus.BAD_REQUEST
        if exc.kind == "day_conflict":
            status = HTTPStatus.CONFLICT
        elif exc.kind in {"invalid_request"}:
            status = HTTPStatus.UNPROCESSABLE_ENTITY
        elif exc.kind == "duplicate_workout_id":
            status = HTTPStatus.CONFLICT
        raise EverydayRequestError(status, str(exc)) from exc

    return {
        "program_file": program_file,
        "accepted": {
            "program_id": result.program_id,
            "days": [
                {
                    "date": entry.date.isoformat(),
                    "week": entry.week,
                    "day": entry.day,
                    "workout_id": entry.workout_id,
                    "recipe_key": entry.recipe_key,
                }
                for entry in result.days
            ],
        },
    }
