"""Compatibility facade for Runplan synchronization use cases."""

from __future__ import annotations

from typing import Any

from ..state.json_repository import JsonStateRepository
from .ports import GarminClient, StateRepository
from .reconciliation import reconcile_program, reconcile_selected_program
from .results import SyncAction
from .sync_batch import synchronize_program_weeks
from .sync_cleanup import cleanup_terminal_workouts, delete_managed_workouts
from .sync_planning import plan_program_weeks
from .sync_support import workout_content_hash
from .sync_week import synchronize_program_week


def _print_actions(actions: list[SyncAction]) -> None:
    """Render legacy synchronization actions for compatibility callers."""
    labels = {
        "create": "Created",
        "reuse": "Reused",
        "unschedule": "Removed schedule",
        "delete": "Deleted workout",
        "completed": "Completed",
        "missed": "Missed",
        "retired": "Retired",
    }
    for action in actions:
        if action.kind == "schedule":
            print(f"Scheduled for {action.date}.")
        elif action.kind == "already_scheduled":
            print(f"Already scheduled for {action.date}.")
        else:
            suffix = (
                f" (workoutId={action.workout_id})" if action.kind in {"create", "reuse"} else ""
            )
            date_suffix = f" ({action.date})" if action.kind in {"completed", "missed"} else ""
            print(f"{labels[action.kind]}: {action.name}{suffix}{date_suffix}.")


def sync_program_week(
    client: GarminClient,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
) -> None:
    """Run one legacy CLI sync using the default JSON repository."""
    result = synchronize_program_week(client, JsonStateRepository(), program, compiled)
    _print_actions(result.actions)
    print(f"\nWeek {result.week} was synced with Garmin Connect.")


def delete_all_managed(
    client: GarminClient,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
    *,
    repository: StateRepository | None = None,
) -> int:
    """Run legacy deletion and print its structured actions."""
    deleted, actions = delete_managed_workouts(
        client, repository or JsonStateRepository(), program, compiled
    )
    _print_actions(actions)
    return deleted


__all__ = [
    "cleanup_terminal_workouts",
    "delete_all_managed",
    "delete_managed_workouts",
    "plan_program_weeks",
    "reconcile_program",
    "reconcile_selected_program",
    "sync_program_week",
    "synchronize_program_week",
    "synchronize_program_weeks",
    "workout_content_hash",
]
