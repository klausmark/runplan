"""HTTP adapter for the Studio coaching recommendation flow.

Step 8 exposes the pure recommendation engine through a single HTTP
endpoint so the add-workout dialog can ask for a recommendation in one
round-trip and render the result next to its existing recipe selector.
The adapter owns four responsibilities:

- validate the JSON payload (readiness, request kind, target day),
- bridge the program record into ``CompletedWorkout`` history using
  :func:`completed_workouts_from_program`,
- identify any existing key workouts in the target week so the UI can
  warn about the key-workout rule for planned workouts that the
  recommender cannot see, and
- serialise :class:`WorkoutRecommendation` plus the supporting
  suggestions back into JSON-friendly shapes the frontend already
  consumes through the recipe surface.

Structural rationale: one HTTP-facing module with one reason to change
(the coaching endpoint surface). It depends only on the application
layer and the recipe catalogue — it does not know how the program is
stored.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import asdict, is_dataclass
from datetime import date
from http import HTTPStatus
from typing import Any

from .application.coaching import (
    build_recommendation_context,
    completed_workouts_from_program,
    parse_readiness,
    parse_request_kind,
    recommend_workouts,
    week_key_forms_for,
)
from .domain.recommendations import (
    Readiness,
    RecipeSuggestion,
    WorkoutRequestKind,
)
from .domain.workout_form import FORM_BY_NAME
from .users import (
    RunplanUser,
    WebError,
    fallback_pace_seconds_per_km,
)
from .web_yaml import load_editable_yaml

__all__ = ["RecommendationRequestError", "recommendation_response"]


class RecommendationRequestError(WebError):
    """Raised when the recommendation request cannot be served."""


def recommendation_response(
    payload: Mapping[str, Any],
    *,
    user: RunplanUser,
    program_file: str,
    program_text: str,
    today: date,
) -> dict[str, Any]:
    """Return the JSON-friendly recommendation for one Studio request.

    The caller supplies the program file path and raw YAML text; the
    adapter does not depend on the storage layer. ``today`` lets tests
    pin the "today" assumption deterministically.
    """
    raw_program = _parse_program_text(program_file, program_text)
    target_day = _parse_target_day(payload.get("target_day"))
    week_number = _parse_week_number(payload.get("week"))
    readiness = _coerce_readiness(payload.get("readiness"))
    request_kind = _coerce_request_kind(payload.get("request_kind"))
    pace_value = user.five_k_best

    completed = completed_workouts_from_program(raw_program)
    context = build_recommendation_context(
        completed,
        five_k_best=pace_value,
        readiness=readiness,
        request_kind=request_kind,
    )
    recommendation = recommend_workouts(context, target_day)
    week_keys = week_key_forms_for(raw_program, week_number)
    fallback_pace = _safe_fallback_pace(pace_value)

    return {
        "target_day": target_day.isoformat(),
        "week": week_number,
        "week_key_forms": list(week_keys),
        "today": today.isoformat(),
        "pace_seconds_per_km": fallback_pace,
        "primary": _serialise_suggestion(recommendation.primary),
        "alternatives": [_serialise_suggestion(item) for item in recommendation.alternatives],
        "reasoning": list(recommendation.reasoning),
        "warnings": list(recommendation.warnings),
        "form_catalog": _form_catalog(),
    }


def _parse_program_text(program_file: str, program_text: str) -> dict[str, Any]:
    if not isinstance(program_text, str) or not program_text.strip():
        raise RecommendationRequestError(HTTPStatus.NOT_FOUND, f"Program {program_file!r} is empty")
    try:
        raw = load_editable_yaml(program_text)
    except Exception as exc:  # ruamel.yaml raises YAMLError
        raise RecommendationRequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid program YAML: {exc}"
        ) from exc
    if not isinstance(raw, dict):
        raise RecommendationRequestError(
            HTTPStatus.UNPROCESSABLE_ENTITY, "Program YAML must be an object"
        )
    return raw


def _parse_target_day(value: Any) -> date:
    if not isinstance(value, str) or not value.strip():
        raise RecommendationRequestError(
            HTTPStatus.BAD_REQUEST, "target_day is required (YYYY-MM-DD)"
        )
    try:
        return date.fromisoformat(value.strip())
    except ValueError as exc:
        raise RecommendationRequestError(
            HTTPStatus.BAD_REQUEST, f"target_day must use YYYY-MM-DD; got {value!r}"
        ) from exc


def _parse_week_number(value: Any) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        if isinstance(value, str):
            try:
                value = int(value.strip())
            except ValueError as exc:
                raise RecommendationRequestError(
                    HTTPStatus.BAD_REQUEST, f"week must be an integer; got {value!r}"
                ) from exc
        else:
            raise RecommendationRequestError(
                HTTPStatus.BAD_REQUEST, f"week must be an integer; got {value!r}"
            )
    if value <= 0:
        raise RecommendationRequestError(HTTPStatus.BAD_REQUEST, "week must be greater than zero")
    return value


def _coerce_readiness(value: Any) -> Readiness | None:
    try:
        return parse_readiness(value)
    except ValueError as exc:
        raise RecommendationRequestError(HTTPStatus.BAD_REQUEST, str(exc)) from exc


def _coerce_request_kind(value: Any) -> WorkoutRequestKind:
    try:
        return parse_request_kind(value)
    except ValueError as exc:
        raise RecommendationRequestError(HTTPStatus.BAD_REQUEST, str(exc)) from exc


def _safe_fallback_pace(five_k_best: str) -> float | None:
    try:
        return fallback_pace_seconds_per_km(five_k_best)
    except ValueError:
        return None


def _serialise_suggestion(suggestion: RecipeSuggestion) -> dict[str, Any]:
    recipe = suggestion.resolve()[0]
    parameters = suggestion.parameters
    parameters_dict = _parameters_to_dict(parameters)
    return {
        "recipe_key": suggestion.recipe_key,
        "recipe_label": recipe.label,
        "form": recipe.form.name,
        "form_label": recipe.form.label,
        "description": recipe.description,
        "parameters": parameters_dict,
    }


def _parameters_to_dict(parameters: Any) -> dict[str, Any]:
    if parameters is None:
        return {}
    if is_dataclass(parameters):
        return asdict(parameters)
    if isinstance(parameters, Mapping):
        return {str(key): value for key, value in parameters.items()}
    return {}


def _form_catalog() -> list[dict[str, str]]:
    return [{"name": form.name, "label": form.label} for form in FORM_BY_NAME.values()]


def delta_from_today(today: date, target_day: date) -> int:
    """Return the day offset (``target - today``) — exposed for tests."""
    return (target_day - today).days
