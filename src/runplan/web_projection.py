"""Build web-facing program and workout lifecycle projections."""

from __future__ import annotations

import copy
import hashlib
import os
from argparse import Namespace
from datetime import timedelta
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .application.activity_records import linked_activities
from .application.ports import StateRepository
from .application.sync import workout_content_hash
from .domain.errors import WorkoutDefinitionError
from .domain.estimates import estimate_steps
from .domain.models import CoachingGuide
from .parsing.values import parse_pace
from .parsing.yaml_loader import load_program_model
from .presentation.text import step_view
from .state.yaml_repository import tracking_from_record
from .users import WebError
from .web_yaml import dump_editable_yaml

if TYPE_CHECKING:
    from .web_programs import ProgramStore


def _revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _effective_values(status: str, record: dict[str, Any], estimate: Any) -> tuple[Any, Any, bool]:
    actual_distance = record.get("actual_distance_meters")
    actual_duration = record.get("actual_duration_seconds")
    if status == "completed" and actual_distance is not None and actual_duration is not None:
        return actual_distance, actual_duration, True
    if status in ("missed", "retired"):
        return 0.0, 0.0, False
    return estimate.distance_meters, estimate.duration_seconds, False


def _workout_view(
    workout: Any, raw: dict[str, Any], record: dict[str, Any], pace: float
) -> dict[str, Any]:
    estimate = estimate_steps(workout.steps, pace)
    status = record.get("display_status", record.get("status", "planned"))
    distance, duration, actual = _effective_values(status, record, estimate)
    editable = copy.deepcopy(raw)
    if "tracking" not in editable and record:
        editable["tracking"] = tracking_from_record(record)
    return {
        "id": workout.id,
        "day": workout.day,
        "name": workout.name,
        "description": workout.description,
        "date": workout.schedule_date.isoformat(),
        "estimated_distance_meters": estimate.distance_meters,
        "estimated_duration_seconds": estimate.duration_seconds,
        "distance_is_approximate": estimate.distance_is_approximate,
        "duration_is_approximate": estimate.duration_is_approximate,
        "status": status,
        "can_move": status != "completed",
        "activity_link_source": record.get("activity_link_source"),
        "can_link_activity": status == "missed",
        "can_manage_activities": status in {"missed", "completed"},
        "activities": linked_activities(record),
        "actual_distance_meters": record.get("actual_distance_meters"),
        "actual_duration_seconds": record.get("actual_duration_seconds"),
        "effective_distance_meters": distance,
        "effective_duration_seconds": duration,
        "totals_are_actual": actual,
        "steps": step_view(workout.steps),
        "yaml": dump_editable_yaml(editable),
    }


def _week_view(
    model: Any, week: Any, raw_week: dict[str, Any], lifecycle: dict[Any, Any], pace: float
) -> dict[str, Any]:
    workouts = [
        _workout_view(workout, raw, lifecycle.get((week.number, workout.id), {}), pace)
        for workout, raw in zip(week.workouts, raw_week["workouts"], strict=True)
    ]
    return {
        "week": week.number,
        "start_date": (model.start_date + timedelta(weeks=week.number - 1)).isoformat(),
        "focus": week.focus,
        "effective_distance_meters": sum(item["effective_distance_meters"] for item in workouts),
        "effective_duration_seconds": sum(item["effective_duration_seconds"] for item in workouts),
        "estimated_distance_meters": sum(item["effective_distance_meters"] for item in workouts),
        "distance_is_approximate": any(item["distance_is_approximate"] for item in workouts),
        "workouts": workouts,
    }


def _lifecycle_record(
    record: Any, definition: dict[str, Any], workout: Any
) -> dict[str, Any] | None:
    if not isinstance(record, dict):
        return None
    view = dict(record)
    if record.get("status") in {"completed", "missed", "retired"}:
        return view
    if record.get("date") != definition["schedule_date"]:
        view["display_status"] = "changed"
        return view
    if record.get("content_hash") and record["content_hash"] != workout_content_hash(workout):
        view["display_status"] = "changed"
        return view
    if record.get("schedule_id"):
        view["status"] = "scheduled"
        return view
    return None


def _coaching_view(guide: CoachingGuide | None) -> dict[str, Any] | None:
    if guide is None:
        return None
    pace_chart = None
    if guide.pace_chart is not None:
        pace_chart = {
            "title": guide.pace_chart.title,
            "intro": guide.pace_chart.intro,
            "headers": [
                {"label": col.label, "description": col.description}
                for col in guide.pace_chart.headers
            ],
            "rows": [list(row) for row in guide.pace_chart.rows],
            "examples": [
                {
                    "title": ex.title,
                    "row": list(ex.row),
                    "targets": list(ex.targets),
                }
                for ex in guide.pace_chart.examples
            ],
        }
    return {
        "tagline": guide.tagline,
        "introSections": [{"title": sec.title, "body": sec.body} for sec in guide.intro_sections],
        "weeklyWorkouts": [{"title": sec.title, "body": sec.body} for sec in guide.weekly_workouts],
        "planTips": [
            {"title": tip.title, "body": tip.body, "items": list(tip.items)}
            for tip in guide.plan_tips
        ],
        "paceChart": pace_chart,
        "glossary": [
            {"term": entry.term, "definition": entry.definition} for entry in guide.glossary
        ],
        "paceTypes": [
            {"name": pt.name, "effort": pt.effort, "description": pt.description}
            for pt in guide.pace_types
        ],
        "thingsToKnow": list(guide.things_to_know),
        "situationalAdvice": [
            {"title": tip.title, "body": tip.body, "items": list(tip.items)}
            for tip in guide.situational_advice
        ],
    }


class ProgramProjector:
    """Build the read model for documents owned by one program store.

    Structural rationale: projection and lifecycle derivation jointly define the web
    read model and do not perform document mutation.
    """

    def __init__(self, store: ProgramStore) -> None:
        self.store = store

    @property
    def repository(self) -> StateRepository:
        return self.store.repository

    def path(self, name: str) -> Path:
        return self.store.path(name)

    def _read(self, path: Path) -> tuple[dict[str, Any], str]:
        return self.store._read(path)

    def get(
        self,
        name: str,
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
    ) -> dict[str, Any]:
        """Build one complete web read model.

        Structural rationale: loading, lifecycle lookup, and week projection are the
        inputs of one read-model operation and perform no mutation.
        """
        path = self.path(name)
        raw, text = self._read(path)
        try:
            model = load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        try:
            pace = parse_pace(
                fallback_pace_value or os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"),
                "RUNPLAN_DEFAULT_PACE",
            )
        except ValueError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        fallback_pace = sum(pace) / len(pace)
        lifecycle = self._lifecycle(
            name,
            model.id,
            repository or self.repository,
            fallback_pace_value=fallback_pace_value,
        )
        weeks = [
            _week_view(model, week, raw_week, lifecycle, fallback_pace)
            for week, raw_week in zip(model.weeks, raw["weeks"], strict=True)
        ]
        return {
            "file": path.name,
            "revision": _revision(text),
            "program": {
                "id": model.id,
                "name": model.name,
                "short_name": model.short_name,
                "description": model.description,
                "start_week": model.start_week,
                "coaching": _coaching_view(model.coaching),
            },
            "weeks": weeks,
        }

    def _lifecycle(
        self,
        name: str,
        program_id: str,
        repository: StateRepository,
        *,
        fallback_pace_value: str | None = None,
    ) -> dict[tuple[int, str], dict[str, Any]]:
        """Derive offline calendar states from the current plan and sync state."""
        from .cli import prepare_sync_selections

        try:
            selections = prepare_sync_selections(
                Namespace(
                    yaml_file=self.path(name),
                    select_weeks="all",
                    weeks_ahead=None,
                    delete_all=False,
                    today=None,
                ),
                fallback_pace_value=fallback_pace_value,
            )
            records = repository.load(program_id)["workouts"]
        except (SystemExit, WorkoutDefinitionError, ValueError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

        statuses: dict[tuple[int, str], dict[str, Any]] = {}
        for program, compiled in selections:
            week = program["week"]
            for definition, workout in compiled:
                record = records.get(f"week-{week:02d}/{definition['id']}")
                view = _lifecycle_record(record, definition, workout)
                if view is not None:
                    statuses[(week, definition["id"])] = view
        return statuses
