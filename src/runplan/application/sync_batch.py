"""Coordinate reconciliation, cleanup, and week synchronization for one batch."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..integrations.garmin.client import get_all_workouts
from .ports import GarminClient, StateRepository
from .reconciliation import reconcile_program, reconcile_selected_program
from .results import SyncAction, SyncResult
from .sync_cleanup import cleanup_terminal_workouts
from .sync_support import SyncSelection, is_owned, is_prunable, validate_selections
from .sync_week import synchronize_program_week

logger = logging.getLogger("runplan.application.sync")


def _prepend_unique_actions(
    results: list[SyncResult], action_groups: tuple[list[SyncAction], ...]
) -> None:
    """Prepend reconciliation actions not already reported by week execution."""
    if not results:
        return
    reported = {
        (action.kind, action.name, action.date, action.activity_id)
        for result in results
        for action in result.actions
    }
    unique: list[SyncAction] = []
    for action in (action for group in action_groups for action in group):
        identity = (action.kind, action.name, action.date, action.activity_id)
        if identity not in reported:
            unique.append(action)
            reported.add(identity)
    results[0].actions[0:0] = unique


def _prune_unselected(
    client: GarminClient,
    repository: StateRepository,
    program_id: str,
    selections: list[SyncSelection],
    result: SyncResult,
    reference_date: date,
) -> None:
    """Remove future active records outside the selected desired set.

    Structural rationale: candidate selection and ordered remote/state cleanup are one
    batch-pruning transaction.
    """
    desired_keys = {
        f"week-{program['week']:02d}/{definition['id']}"
        for program, compiled in selections
        for definition, _ in compiled
    }
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    remote_workouts = get_all_workouts(client)
    for key in sorted(set(records) - desired_keys):
        record = records[key]
        if not is_prunable(record, reference_date):
            continue
        workout_id = record.get("workout_id")
        remote = next(
            (item for item in remote_workouts if item.get("workoutId") == workout_id), None
        )
        if remote is not None and not is_owned(remote, record):
            raise RuntimeError(
                f"Safety stop: workoutId={workout_id} does not belong to the program"
            )
        name = record.get("name", key)
        schedule_id = record.get("schedule_id")
        if schedule_id:
            client.unschedule_workout(schedule_id)
            result.add("unschedule", name, workout_id=workout_id, schedule_id=schedule_id)
        if workout_id and remote is not None:
            client.delete_workout(workout_id)
            result.add("delete", name, workout_id=workout_id)
        elif workout_id:
            logger.warning(
                "Tracked Garmin workout not found during prune program_id=%s key=%s workout_id=%s",
                program_id,
                key,
                workout_id,
            )
        del records[key]
        repository.save(program_id, state)


def synchronize_program_weeks(
    client: GarminClient,
    repository: StateRepository,
    selections: list[SyncSelection],
    *,
    prune: bool = False,
    today: date | None = None,
) -> list[SyncResult]:
    """Synchronize selected weeks additively, then optionally prune other weeks."""
    validate_selections(selections)
    program_id = selections[0][0]["program_id"]
    reconciled = reconcile_program(client, repository, program_id, today=today)
    selected = reconcile_selected_program(client, repository, selections, today=today)
    cleanup = cleanup_terminal_workouts(client, repository, program_id)
    results = [
        synchronize_program_week(client, repository, program, compiled, prune=False, today=today)
        for program, compiled in selections
    ]
    _prepend_unique_actions(results, (reconciled.actions, selected.actions, cleanup))
    if prune and results:
        _prune_unselected(
            client,
            repository,
            program_id,
            selections,
            results[-1],
            today or date.today(),
        )
    return results
