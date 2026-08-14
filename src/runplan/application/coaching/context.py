"""Coaching context assembly and program-history bridging.

Step 8 wires the existing pure recommendation engine into the Studio
add-workout dialog. The function in this module turns the user's
five-kilometre best, a readiness selection, the runner's request, and
the run plan's completed history into a
:class:`~runplan.domain.recommendations.CoachingContext` that the
recommender understands. Bridging program records into
:class:`~runplan.domain.recommendations.CompletedWorkout` lives next to
the context builder so the rest of the application still sees the
domain types instead of raw payloads.

The functions are intentionally pure: they read the inputs they receive
and never read the clock. ``today`` callers provide the date when the
runner is choosing a workout so the recommendation can reason about
recency relative to that date.

Structural rationale: the bridging function is separate from the
context builder so the recommender layer stays free of YAML knowledge.
"""

from __future__ import annotations

from datetime import date
from typing import Any

from ...domain.errors import WorkoutDefinitionError
from ...domain.models import Program
from ...domain.recommendations import (
    CoachingContext,
    CompletedWorkout,
    Readiness,
    RunnerPace,
    WorkoutRequestKind,
)
from ...domain.workout_form import infer_workout_form
from ...parsing.yaml_loader import load_program_model
from ...users import five_k_pace_seconds

__all__ = [
    "build_recommendation_context",
    "completed_workouts_from_program",
    "parse_readiness",
    "parse_request_kind",
    "week_key_forms_for",
]


_READINESS_BY_VALUE: dict[str, Readiness] = {
    "low": Readiness.LOW,
    "normal": Readiness.NORMAL,
    "high": Readiness.HIGH,
}

_REQUEST_KIND_BY_VALUE: dict[str, WorkoutRequestKind] = {
    "default": WorkoutRequestKind.DEFAULT,
    "easy": WorkoutRequestKind.EASY,
    "recovery": WorkoutRequestKind.RECOVERY,
    "key": WorkoutRequestKind.KEY,
}


def parse_readiness(value: Any) -> Readiness | None:
    """Map a JSON-friendly readiness string to :class:`Readiness`.

    ``None`` and an empty string both mean "not provided" and remain
    ``None`` so the recommender treats the field as unknown. Unknown
    values raise :class:`ValueError` so the HTTP adapter can answer
    with a 400 rather than silently swallowing the input.
    """
    if value is None or value == "":
        return None
    if not isinstance(value, str):
        raise ValueError(f"invalid readiness {value!r}; expected low, normal, or high")
    cleaned = value.strip().lower()
    if cleaned == "":
        return None
    try:
        return _READINESS_BY_VALUE[cleaned]
    except KeyError as exc:
        raise ValueError(f"invalid readiness {value!r}; expected low, normal, or high") from exc


def parse_request_kind(value: Any) -> WorkoutRequestKind:
    """Map a JSON-friendly request-kind string to :class:`WorkoutRequestKind`.

    Missing or empty input falls back to :data:`WorkoutRequestKind.DEFAULT`.
    Unknown values raise :class:`ValueError` so the HTTP adapter can
    answer with a 400.
    """
    if value is None or value == "":
        return WorkoutRequestKind.DEFAULT
    if not isinstance(value, str):
        raise ValueError(
            f"invalid request_kind {value!r}; expected default, easy, recovery, or key"
        )
    cleaned = value.strip().lower()
    if cleaned == "":
        return WorkoutRequestKind.DEFAULT
    try:
        return _REQUEST_KIND_BY_VALUE[cleaned]
    except KeyError as exc:
        raise ValueError(
            f"invalid request_kind {value!r}; expected default, easy, recovery, or key"
        ) from exc


def build_recommendation_context(
    completed: tuple[CompletedWorkout, ...],
    *,
    five_k_best: str,
    readiness: Readiness | None,
    request_kind: WorkoutRequestKind,
) -> CoachingContext:
    """Build a :class:`CoachingContext` from collected history and user inputs.

    A non-empty ``five_k_best`` is converted to a
    :class:`RunnerPace` so the recommender can build key-workout pace
    targets; an empty string leaves ``pace=None`` which keeps the easy
    and recovery defaults in play.
    """
    pace = None
    if isinstance(five_k_best, str) and five_k_best.strip():
        try:
            pace = RunnerPace(five_k_pace_seconds(five_k_best))
        except ValueError:
            pace = None
    return CoachingContext(
        pace=pace,
        readiness=readiness,
        request_kind=request_kind,
        recent_completed_workouts=completed,
    )


def completed_workouts_from_program(
    raw_program: dict[str, Any],
) -> tuple[CompletedWorkout, ...]:
    """Return :class:`CompletedWorkout` for every completed record in the program.

    Each completed record needs an ``actual`` block with non-null
    ``distance_meters``, ``duration_seconds`` and ``completed_at``. The
    workout form is inferred from the workout's step structure via
    :func:`infer_workout_form` so a recipe-authored workout keeps its
    authoring category without storing it inside the program YAML.
    """
    try:
        model = load_program_model(raw_program)
    except WorkoutDefinitionError:
        return ()
    return _collect_completed_from_model(model, raw_program)


def _collect_completed_from_model(
    model: Program, raw_program: dict[str, Any]
) -> tuple[CompletedWorkout, ...]:
    raw_weeks = raw_program.get("weeks")
    if not isinstance(raw_weeks, list):
        return ()
    completed: list[CompletedWorkout] = []
    for week_idx, model_week in enumerate(model.weeks):
        raw_week = raw_weeks[week_idx] if week_idx < len(raw_weeks) else None
        if not isinstance(raw_week, dict):
            continue
        workouts = raw_week.get("workouts")
        if not isinstance(workouts, list):
            continue
        for workout_idx, model_workout in enumerate(model_week.workouts):
            if workout_idx >= len(workouts):
                continue
            raw_workout = workouts[workout_idx]
            if not isinstance(raw_workout, dict):
                continue
            tracked = _tracked_completion(raw_workout)
            if tracked is None:
                continue
            workout_date = model_workout.schedule_date
            if workout_date == date(1970, 1, 1) or tracked.completed_at is None:
                completion_date = workout_date
            else:
                completion_date = _parse_iso_date(tracked.completed_at)
                if completion_date is None:
                    completion_date = workout_date
            completed.append(
                CompletedWorkout(
                    date=completion_date,
                    form=infer_workout_form(model_workout),
                    distance_meters=tracked.distance_meters or 0.0,
                    duration_seconds=tracked.duration_seconds or 0,
                )
            )
    return tuple(completed)


class _TrackedCompletion:
    __slots__ = ("completed_at", "distance_meters", "duration_seconds")

    def __init__(
        self, completed_at: str | None, distance_meters: float | None, duration_seconds: int | None
    ) -> None:
        self.completed_at = completed_at
        self.distance_meters = distance_meters
        self.duration_seconds = duration_seconds


def _tracked_completion(workout: dict[str, Any]) -> _TrackedCompletion | None:
    tracking = workout.get("tracking")
    if not isinstance(tracking, dict):
        return None
    actual = tracking.get("actual")
    if not isinstance(actual, dict):
        return None
    distance = actual.get("distance_meters")
    duration = actual.get("duration_seconds")
    if not isinstance(distance, (int, float)) or not isinstance(duration, (int, float)):
        return None
    completed_at = actual.get("completed_at")
    if not isinstance(completed_at, str):
        completed_at = None
    return _TrackedCompletion(
        completed_at=completed_at, distance_meters=float(distance), duration_seconds=int(duration)
    )


def _parse_iso_date(value: str) -> date | None:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned:
        return None
    try:
        return date.fromisoformat(cleaned[:10])
    except ValueError:
        return None


def week_key_forms_for(raw_program: dict[str, Any], week_number: int) -> tuple[str, ...]:
    """Return the key-workout form names that already exist in one week.

    Only weeks with at least one :class:`~runplan.domain.workout_form.WorkoutForm`
    in :data:`~runplan.domain.recommendations.KEY_WORKOUT_FORMS` contribute.
    The Studio uses this list to warn the runner when the suggested
    workout is itself a key, fulfilling the key-workout rule from
    ``docs/program-prompt.md`` for planned (not yet completed) workouts.
    """
    try:
        model = load_program_model(raw_program)
    except WorkoutDefinitionError:
        return ()
    raw_weeks = raw_program.get("weeks")
    if not isinstance(raw_weeks, list):
        return ()
    for week_idx, model_week in enumerate(model.weeks):
        if model_week.number != week_number:
            continue
        raw_week = raw_weeks[week_idx] if week_idx < len(raw_weeks) else None
        if not isinstance(raw_week, dict):
            return ()
        workouts = raw_week.get("workouts")
        if not isinstance(workouts, list):
            return ()
        key_names: list[str] = []
        for workout_idx, model_workout in enumerate(model_week.workouts):
            if workout_idx >= len(workouts):
                continue
            raw_workout = workouts[workout_idx]
            if not isinstance(raw_workout, dict):
                continue
            tracking = raw_workout.get("tracking")
            status: str | None = None
            if isinstance(tracking, dict):
                candidate = tracking.get("status")
                if isinstance(candidate, str):
                    status = candidate
            if status == "completed":
                continue
            if not _is_key_form(infer_workout_form(model_workout)):
                continue
            key_names.append(infer_workout_form(model_workout).name)
        return tuple(dict.fromkeys(key_names))
    return ()


def _is_key_form(form) -> bool:
    from ...domain.recommendations import KEY_WORKOUT_FORMS

    return form in KEY_WORKOUT_FORMS
