"""Shared identity and validation rules for synchronization use cases."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable
from datetime import date
from typing import Any

from garminconnect.exceptions import GarminConnectConnectionError

type SyncSelection = tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]

CONTENT_FIELDS = (
    "workoutName",
    "description",
    "estimatedDurationInSecs",
    "workoutSegments",
)
TERMINAL_STATUSES = {"completed", "missed", "retired"}
CLEANUP_STATUSES = {"completed", "missed"}
_NOT_FOUND_MARKERS = ("404", "not found")

logger = logging.getLogger("runplan.application.sync")


def ignore_garmin_not_found(
    operation: str, context: dict[str, Any]
) -> Callable[[Callable[[], Any]], Any]:
    """Run a destructive Garmin call; treat 'object missing' as success.

    Garmin returns 404 when a workout or schedule was already removed by the
    user, a previous partial sync, or the current transaction. Local state is
    the source of truth for what should exist, so 'already gone' satisfies the
    cleanup intent and must not abort the batch. Other failures still raise.
    """

    def _wrap(call: Callable[[], Any]) -> Any:
        try:
            return call()
        except GarminConnectConnectionError as exc:
            message = str(exc).lower()
            if any(marker in message for marker in _NOT_FOUND_MARKERS):
                logger.warning(
                    "Garmin %s already gone during cleanup; treating as success %s",
                    operation,
                    context,
                )
                return None
            raise

    return _wrap


def schedule_for_record(
    scheduled: list[dict[str, Any]], record: dict[str, Any]
) -> dict[str, Any] | None:
    """Find the Garmin calendar occurrence belonging to a tracked workout."""
    schedule_id = record.get("schedule_id")
    if schedule_id:
        match = next(
            (
                item
                for item in scheduled
                if item.get("workoutScheduleId", item.get("id")) == schedule_id
            ),
            None,
        )
        if match is not None:
            return match
    return next(
        (
            item
            for item in scheduled
            if item.get("workoutId") == record.get("workout_id")
            and item.get("date") == record.get("date")
        ),
        None,
    )


def is_prunable(record: Any, reference_date: date) -> bool:
    """Return whether prune may remove this future active record."""
    return (
        isinstance(record, dict)
        and record.get("status") not in TERMINAL_STATUSES
        and isinstance(record.get("date"), str)
        and record["date"] >= reference_date.isoformat()
    )


def validate_selections(selections: list[SyncSelection]) -> None:
    """Reject ambiguous batches before state or Garmin can be mutated."""
    if not selections:
        raise ValueError("sync requires at least one selected week")
    program_ids = {program.get("program_id") for program, _ in selections}
    if len(program_ids) != 1:
        raise ValueError("sync selections must belong to one program")
    weeks = [program.get("week") for program, _ in selections]
    if len(weeks) != len(set(weeks)):
        raise ValueError("sync selections contain overlapping weeks")
    empty = [program.get("week") for program, compiled in selections if not compiled]
    if empty:
        raise ValueError(f"selected weeks contain no workouts: {empty}")


def workout_payload(workout: Any) -> dict[str, Any]:
    """Return the Garmin fields used to compare workout content."""
    payload = workout.to_dict()
    return {field: payload.get(field) for field in CONTENT_FIELDS}


def content_hash(payload: dict[str, Any]) -> str:
    """Hash canonical Garmin workout content."""
    canonical = {field: payload.get(field) for field in CONTENT_FIELDS}
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def workout_content_hash(workout: Any) -> str:
    """Return the canonical sync hash for a compiled Garmin workout."""
    return content_hash(workout_payload(workout))


def remote_has_content(remote: dict[str, Any]) -> bool:
    """Return whether a Garmin summary contains fields needed for a full comparison."""
    return "workoutSegments" in remote and "estimatedDurationInSecs" in remote


def is_owned(remote: dict[str, Any], record: dict[str, Any]) -> bool:
    """Treat a remote object as owned only when its ID is tracked locally."""
    workout_id = record.get("workout_id")
    return workout_id is not None and remote.get("workoutId") == workout_id
