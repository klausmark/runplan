"""Safely remove tracked Garmin schedules and workout templates."""

from __future__ import annotations

import logging
from typing import Any

from ..integrations.garmin.client import get_all_workouts, scheduled_items_for_dates
from .ports import GarminClient, StateRepository
from .results import SyncAction
from .sync_support import CLEANUP_STATUSES, TERMINAL_STATUSES, is_owned, schedule_for_record

logger = logging.getLogger("runplan.application.sync")


def _verify_owned_templates(
    terminal: list[tuple[str, dict[str, Any]]], remote_by_id: dict[Any, dict[str, Any]]
) -> None:
    """Verify every extant template before the first destructive call."""
    for _, record in terminal:
        remote = remote_by_id.get(record.get("workout_id"))
        if remote is not None and not is_owned(remote, record):
            raise RuntimeError(
                f"Safety stop: workoutId={record.get('workout_id')} does not belong to the program"
            )


def _remove_terminal_record(
    client: GarminClient,
    repository: StateRepository,
    program_id: str,
    state: dict[str, Any],
    key: str,
    record: dict[str, Any],
    scheduled: list[dict[str, Any]],
    remote_by_id: dict[Any, dict[str, Any]],
) -> list[SyncAction]:
    """Remove remote objects and checkpoint one terminal record."""
    actions: list[SyncAction] = []
    name = record.get("name", key)
    workout_id = record.get("workout_id")
    stored_schedule_id = record.get("schedule_id")
    occurrence = schedule_for_record(scheduled, record)
    schedule_id = occurrence.get("workoutScheduleId", occurrence.get("id")) if occurrence else None
    if schedule_id is not None:
        client.unschedule_workout(schedule_id)
        actions.append(
            SyncAction(
                "unschedule",
                name,
                workout_id=workout_id,
                schedule_id=schedule_id,
                date=record.get("date"),
            )
        )
    if record.pop("schedule_id", None) is not None:
        if schedule_id is None:
            logger.warning(
                "Tracked Garmin schedule not found during terminal cleanup program_id=%s workout_id=%s stored_schedule_id=%s",
                program_id,
                workout_id,
                stored_schedule_id,
            )
        repository.save(program_id, state)

    remote = remote_by_id.get(workout_id)
    if workout_id is not None and remote is not None:
        client.delete_workout(workout_id)
        actions.append(SyncAction("delete", name, workout_id=workout_id))
    elif workout_id is not None:
        logger.warning(
            "Tracked Garmin workout not found during terminal cleanup program_id=%s workout_id=%s",
            program_id,
            workout_id,
        )
    changed = False
    for field in ("workout_id", "content_hash", "description"):
        if record.pop(field, None) is not None:
            changed = True
    if changed:
        repository.save(program_id, state)
    return actions


def cleanup_terminal_workouts(
    client: GarminClient,
    repository: StateRepository,
    program_id: str,
) -> list[SyncAction]:
    """Remove Garmin objects while retaining local completed and missed history."""
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    terminal = [
        (key, record)
        for key, record in sorted(records.items())
        if isinstance(record, dict)
        and record.get("status") in CLEANUP_STATUSES
        and (record.get("schedule_id") or record.get("workout_id"))
    ]
    if not terminal:
        return []
    remote_workouts = get_all_workouts(client)
    dates = {record["date"] for _, record in terminal if isinstance(record.get("date"), str)}
    scheduled = scheduled_items_for_dates(client, dates) if dates else []
    remote_by_id = {
        item.get("workoutId"): item for item in remote_workouts if item.get("workoutId") is not None
    }
    _verify_owned_templates(terminal, remote_by_id)
    return [
        action
        for key, record in terminal
        for action in _remove_terminal_record(
            client, repository, program_id, state, key, record, scheduled, remote_by_id
        )
    ]


def _find_schedule_id(
    scheduled: list[dict[str, Any]], record: dict[str, Any], workout_id: Any
) -> Any:
    """Find the stored or recovered schedule ID for one active record."""
    if record.get("schedule_id"):
        return record["schedule_id"]
    occurrence = next(
        (
            item
            for item in scheduled
            if item.get("workoutId") == workout_id and item.get("date") == record.get("date")
        ),
        None,
    )
    return occurrence.get("workoutScheduleId", occurrence.get("id")) if occurrence else None


def delete_managed_workouts(
    client: GarminClient,
    repository: StateRepository,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
) -> tuple[int, list[SyncAction]]:
    """Delete all verified active workouts owned by one program."""
    del compiled  # Retained for compatibility with the existing public signature.
    program_id = program["program_id"]
    actions = cleanup_terminal_workouts(client, repository, program_id)
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    remote_workouts = get_all_workouts(client)
    dates = {
        record["date"]
        for record in records.values()
        if isinstance(record, dict) and isinstance(record.get("date"), str)
    }
    scheduled = scheduled_items_for_dates(client, dates) if dates else []
    deleted = 0
    for key in sorted(list(records)):
        record = records[key]
        if record.get("status") in TERMINAL_STATUSES:
            continue
        workout_id = record.get("workout_id")
        remote = next(
            (item for item in remote_workouts if item.get("workoutId") == workout_id), None
        )
        schedule_id = _find_schedule_id(scheduled, record, workout_id)
        name = record.get("name", key)
        if schedule_id:
            client.unschedule_workout(schedule_id)
            actions.append(SyncAction("unschedule", name, workout_id, schedule_id=schedule_id))
        if workout_id and remote is not None:
            client.delete_workout(workout_id)
            actions.append(SyncAction("delete", name, workout_id))
        elif workout_id:
            logger.warning(
                "Tracked Garmin workout not found during delete program_id=%s key=%s workout_id=%s",
                program_id,
                key,
                workout_id,
            )
        del records[key]
        deleted += 1
        repository.save(program_id, state)
    if not records:
        repository.delete(program_id)
    return deleted, actions
