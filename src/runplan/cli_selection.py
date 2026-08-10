"""Select presentation weeks and compile them for synchronization."""

from __future__ import annotations

import os
from argparse import Namespace
from typing import Any

from .application.presentation_weeks import build_presentation_weeks, presentation_start
from .domain.estimates import estimate_steps
from .domain.selectors import WeekSelection
from .domain.workout_titles import garmin_workout_title
from .integrations.garmin.mapper import build_workout
from .parsing.yaml_loader import load_definition, load_definition_model
from .users import (
    DEFAULT_FIVE_K_BEST,
    ENV_FIVE_K_BEST,
    fallback_pace_seconds_per_km,
)


def week_selection(arguments: Namespace, *, default_all: bool = False) -> WeekSelection:
    """Translate parsed CLI selector options to a domain value object."""
    expression = getattr(arguments, "select_weeks", None)
    if expression is not None:
        return WeekSelection.parse(expression)
    weeks_ahead = getattr(arguments, "weeks_ahead", None)
    if weeks_ahead is not None:
        return WeekSelection.ahead(weeks_ahead)
    return WeekSelection.all() if default_all else WeekSelection.ahead(1)


def prepare_sync_selections(
    arguments: Namespace,
    *,
    fallback_pace_value: str | None = None,
) -> list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]]:
    """Load, select, and compile weeks without terminal or Garmin I/O."""
    model = load_definition_model(arguments.yaml_file)
    five_k_best = fallback_pace_value or os.getenv(ENV_FIVE_K_BEST, DEFAULT_FIVE_K_BEST)
    fallback_pace = fallback_pace_seconds_per_km(five_k_best)
    presentation_weeks = build_presentation_weeks(model)
    selected_weeks = _resolved_weeks(arguments, model, presentation_weeks)
    selected_items = [
        (week.number, item)
        for week in presentation_weeks
        if week.number in selected_weeks
        for item in week.workouts
    ]
    return [
        _compile_source_week(
            arguments.yaml_file,
            source_week,
            selected_items,
            model.short_name,
            fallback_pace,
        )
        for source_week in sorted({item.source_week for _, item in selected_items})
    ]


def _resolved_weeks(arguments: Namespace, model: Any, presentation_weeks: list[Any]) -> Any:
    selection = (
        WeekSelection.all()
        if getattr(arguments, "delete_all", False)
        and getattr(arguments, "select_weeks", None) is None
        and getattr(arguments, "weeks_ahead", None) is None
        else week_selection(arguments)
    )
    return selection.resolve(
        tuple(week.number for week in presentation_weeks),
        start_date=presentation_start(model),
        today=getattr(arguments, "today", None),
    )


def _compile_source_week(
    path: Any, source_week: int, selected_items: list[Any], short_name: str, pace: float
) -> Any:
    definition = load_definition(path, source_week)
    presented = {
        item.workout.id: (presentation_week, item)
        for presentation_week, item in selected_items
        if item.source_week == source_week
    }
    definition["workouts"] = [
        workout for workout in definition["workouts"] if workout["id"] in presented
    ]
    compiled = [
        _compile_workout(workout, presented[workout["id"]], short_name, pace)
        for workout in definition["workouts"]
    ]
    return definition, compiled


def _compile_workout(
    workout: dict[str, Any], presented: tuple[int, Any], short_name: str, pace: float
) -> Any:
    presentation_week, item = presented
    workout["presentation_week"] = presentation_week
    workout["presentation_name"] = item.name
    workout["base_description"] = workout.get("description")
    estimate = estimate_steps(item.workout.steps, pace)
    workout["estimated_duration_seconds"] = estimate.duration_seconds
    workout["estimated_distance_meters"] = estimate.distance_meters
    workout["estimated_distance_is_approximate"] = estimate.distance_is_approximate
    workout["name"] = garmin_workout_title(
        short_name, presentation_week, item.workout, pace, workout_name=item.name
    )
    return workout, build_workout(workout)
