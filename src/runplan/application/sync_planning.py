"""Build read-only synchronization plans from desired and tracked state."""

from __future__ import annotations

from datetime import date
from typing import Any

from .ports import StateRepository
from .results import SyncPlan
from .sync_support import (
    CLEANUP_STATUSES,
    TERMINAL_STATUSES,
    SyncSelection,
    is_prunable,
    validate_selections,
    workout_content_hash,
)


def _plan_desired_workout(
    plan: SyncPlan,
    record: dict[str, Any] | None,
    definition: dict[str, Any],
    desired_hash: str,
    reference_date: date,
) -> None:
    """Add actions for one desired workout compared with tracked state."""
    if record is None and definition["schedule_date"] < reference_date.isoformat():
        plan.add("missed", definition["name"], date=definition["schedule_date"])
    elif record is None:
        plan.add("create", definition["name"])
        plan.add("schedule", definition["name"], date=definition["schedule_date"])
    elif record.get("status") in TERMINAL_STATUSES:
        plan.add(
            record["status"],
            record.get("name", definition["name"]),
            workout_id=record.get("workout_id"),
            schedule_id=record.get("schedule_id"),
            date=record.get("date"),
            activity_id=record.get("activity_id"),
            completed_at=record.get("completed_at"),
        )
    elif record.get("content_hash") != desired_hash:
        plan.add("update", definition["name"], workout_id=record.get("workout_id"))
        plan.add("schedule", definition["name"], date=definition["schedule_date"])
    else:
        _plan_reusable_workout(plan, record, definition)


def _plan_reusable_workout(
    plan: SyncPlan, record: dict[str, Any], definition: dict[str, Any]
) -> None:
    """Add reuse and any required rescheduling actions."""
    plan.add("reuse", definition["name"], workout_id=record.get("workout_id"))
    if record.get("schedule_id") and record.get("date") == definition["schedule_date"]:
        return
    plan.add("schedule", definition["name"], date=definition["schedule_date"])
    if record.get("schedule_id"):
        plan.add(
            "unschedule",
            definition["name"],
            workout_id=record.get("workout_id"),
            schedule_id=record["schedule_id"],
            date=record.get("date"),
        )


def _plan_record_removal(plan: SyncPlan, key: str, record: dict[str, Any]) -> None:
    """Add safe unschedule and delete actions for one tracked record."""
    name = record.get("name", key)
    if record.get("schedule_id"):
        plan.add(
            "unschedule",
            name,
            workout_id=record.get("workout_id"),
            schedule_id=record["schedule_id"],
            date=record.get("date"),
        )
    if record.get("workout_id"):
        plan.add("delete", name, workout_id=record["workout_id"])


def plan_program_weeks(
    repository: StateRepository,
    selections: list[SyncSelection],
    *,
    prune: bool = False,
    today: date | None = None,
) -> SyncPlan:
    """Build an offline sync diff without mutating state or Garmin."""
    validate_selections(selections)
    program_id = selections[0][0]["program_id"]
    plan = SyncPlan(program_id, tuple(program["week"] for program, _ in selections))
    records: dict[str, Any] = repository.load(program_id)["workouts"]
    desired_keys: set[str] = set()
    reference_date = today or date.today()

    for program, compiled in selections:
        for definition, workout in compiled:
            key = f"week-{program['week']:02d}/{definition['id']}"
            desired_keys.add(key)
            _plan_desired_workout(
                plan,
                records.get(key),
                definition,
                workout_content_hash(workout),
                reference_date,
            )

    for key, record in sorted(records.items()):
        if isinstance(record, dict) and (
            record.get("status") in CLEANUP_STATUSES or record.get("pending_deletion") is True
        ):
            _plan_record_removal(plan, key, record)

    if prune:
        for key in sorted(set(records) - desired_keys):
            record = records[key]
            if is_prunable(record, reference_date):
                _plan_record_removal(plan, key, record)
    return plan
