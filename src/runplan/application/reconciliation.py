"""Reconcile tracked workout state from Garmin calendar evidence."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..integrations.garmin.client import scheduled_items_for_dates
from .activity_records import apply_linked_activities
from .ports import GarminClient, StateRepository
from .results import ReconcileResult
from .sync_support import TERMINAL_STATUSES, SyncSelection, schedule_for_record, validate_selections

logger = logging.getLogger("runplan.application.sync")


def _complete_record(
    record: dict[str, Any], occurrence: dict[str, Any], result: ReconcileResult
) -> None:
    """Apply one completed Garmin occurrence to an existing tracked record."""
    activity_id = occurrence["associatedActivityId"]
    completed_at = occurrence.get("associatedActivityDateTime")
    activity = {
        "activity_id": activity_id,
        "link_source": "automatic",
        "distance_meters": occurrence["actualDistanceMeters"],
        "duration_seconds": occurrence["actualDurationSeconds"],
    }
    if completed_at:
        activity["completed_at"] = completed_at
    if occurrence.get("associatedActivityName"):
        activity["name"] = occurrence["associatedActivityName"]
    record["status"] = "completed"
    apply_linked_activities(record, [activity])
    record.pop("content_hash", None)
    record.pop("description", None)
    result.add(
        "completed",
        record.get("name", "Unknown workout"),
        workout_id=record.get("workout_id"),
        schedule_id=record.get("schedule_id"),
        date=record.get("date"),
        activity_id=activity_id,
        completed_at=completed_at,
        actual_distance_meters=record["actual_distance_meters"],
        actual_duration_seconds=record["actual_duration_seconds"],
    )


def _miss_record(record: dict[str, Any], result: ReconcileResult) -> None:
    """Mark one historical record missed and report the transition."""
    record["status"] = "missed"
    result.add(
        "missed",
        record.get("name", "Unknown workout"),
        workout_id=record.get("workout_id"),
        schedule_id=record.get("schedule_id"),
        date=record.get("date"),
    )


def reconcile_program(
    client: GarminClient,
    repository: StateRepository,
    program_id: str,
    *,
    today: date | None = None,
) -> ReconcileResult:
    """Update tracked historical workouts from Garmin calendar associations."""
    reference_date = today or date.today()
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    historical_dates = {
        record["date"]
        for record in records.values()
        if isinstance(record, dict)
        and isinstance(record.get("date"), str)
        and record["date"] < reference_date.isoformat()
        and record.get("status") not in TERMINAL_STATUSES
    }
    scheduled = scheduled_items_for_dates(client, historical_dates) if historical_dates else []
    result = ReconcileResult(program_id)
    changed = False
    for record in records.values():
        if not isinstance(record, dict) or record.get("date") not in historical_dates:
            continue
        occurrence = schedule_for_record(scheduled, record)
        if occurrence and occurrence.get("associatedActivityId") is not None:
            _complete_record(record, occurrence, result)
        else:
            _miss_record(record, result)
        changed = True
    if changed:
        repository.save(program_id, state)
    return result


def _completed_selected_record(
    week: int, definition: dict[str, Any], occurrence: dict[str, Any]
) -> dict[str, Any]:
    """Build tracked state for a selected workout completed outside local state."""
    completed: dict[str, Any] = {
        "week": week,
        "date": definition["schedule_date"],
        "name": definition["name"],
        "status": "completed",
    }
    activity = {
        "activity_id": occurrence["associatedActivityId"],
        "link_source": "automatic",
        "distance_meters": occurrence["actualDistanceMeters"],
        "duration_seconds": occurrence["actualDurationSeconds"],
    }
    if occurrence.get("associatedActivityDateTime"):
        activity["completed_at"] = occurrence["associatedActivityDateTime"]
    if occurrence.get("associatedActivityName"):
        activity["name"] = occurrence["associatedActivityName"]
    apply_linked_activities(completed, [activity])
    optional = {
        "workout_id": occurrence.get("workoutId"),
        "schedule_id": occurrence.get("workoutScheduleId", occurrence.get("id")),
        "completed_at": occurrence.get("associatedActivityDateTime"),
    }
    completed.update({key: value for key, value in optional.items() if value is not None})
    return completed


def reconcile_selected_program(
    client: GarminClient,
    repository: StateRepository,
    selections: list[SyncSelection],
    *,
    today: date | None = None,
) -> ReconcileResult:
    """Reconcile Garmin evidence for every selected plan occurrence.

    Structural rationale: discovery, matching, and checkpointing form one guarded
    reconciliation transaction and preserve remote-call order.
    """
    validate_selections(selections)
    reference_date = today or date.today()
    program_id = selections[0][0]["program_id"]
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    selected = [
        (program["week"], definition)
        for program, compiled in selections
        for definition, _ in compiled
    ]
    dates = {definition["schedule_date"] for _, definition in selected}
    scheduled = scheduled_items_for_dates(client, dates) if dates else []
    result = ReconcileResult(program_id)
    changed = False
    for week, definition in selected:
        key = f"week-{week:02d}/{definition['id']}"
        record = records.get(key)
        occurrence = schedule_for_record(scheduled, record) if isinstance(record, dict) else None
        if occurrence and occurrence.get("associatedActivityId") is not None:
            if isinstance(record, dict) and record.get("status") == "completed":
                continue
            records[key] = completed = _completed_selected_record(week, definition, occurrence)
            result.add(
                "completed",
                definition["name"],
                workout_id=completed.get("workout_id"),
                schedule_id=completed.get("schedule_id"),
                date=definition["schedule_date"],
                activity_id=completed["activity_id"],
                completed_at=completed.get("completed_at"),
                actual_distance_meters=completed["actual_distance_meters"],
                actual_duration_seconds=completed["actual_duration_seconds"],
            )
            changed = True
        elif (
            definition["schedule_date"] < reference_date.isoformat()
            and isinstance(record, dict)
            and record.get("status") not in TERMINAL_STATUSES
        ):
            record["status"] = "missed"
            result.add(
                "missed",
                record.get("name", definition["name"]),
                workout_id=record.get("workout_id"),
                schedule_id=record.get("schedule_id"),
                date=definition["schedule_date"],
            )
            changed = True
    if changed:
        repository.save(program_id, state)
    return result
