"""Ensure a resolved Garmin workout has the desired schedule."""

from __future__ import annotations

import logging
from typing import Any

from .ports import GarminClient
from .results import SyncResult

logger = logging.getLogger("runplan.application.sync")


def ensure_schedule(
    client: GarminClient,
    scheduled: list[dict[str, Any]],
    result: SyncResult,
    program_id: str,
    definition: dict[str, Any],
    previous: Any,
    workout_id: Any,
    *,
    reused: bool,
) -> Any:
    """Reuse the desired schedule when present, otherwise create it.

    Structural rationale: lookup, creation, result recording, and ID validation are one
    schedule-ensuring operation.
    """
    schedule = next(
        (
            item
            for item in scheduled
            if item.get("workoutId") == workout_id
            and item.get("date") == definition["schedule_date"]
        ),
        None,
    )
    if schedule is None:
        if reused and previous and previous.get("schedule_id"):
            logger.warning(
                "Tracked Garmin schedule not found or moved; recreating program_id=%s workout_id=%s schedule_id=%s date=%s",
                program_id,
                workout_id,
                previous.get("schedule_id"),
                definition["schedule_date"],
            )
        schedule = client.schedule_workout(workout_id, definition["schedule_date"])
        result.add(
            "schedule",
            definition["name"],
            workout_id=workout_id,
            date=definition["schedule_date"],
        )
    else:
        result.add(
            "already_scheduled",
            definition["name"],
            workout_id=workout_id,
            date=definition["schedule_date"],
        )
    schedule_id = schedule.get("workoutScheduleId", schedule.get("id"))
    if not schedule_id:
        raise RuntimeError(f"Scheduling {definition['name']!r} did not return a schedule ID")
    return schedule_id


def remove_superseded_schedule(
    client: GarminClient,
    result: SyncResult,
    definition: dict[str, Any],
    previous: Any,
    workout_id: Any,
    schedule_id: Any,
    *,
    workout_replaced: bool,
) -> None:
    """Remove an old schedule when the workout itself was retained."""
    if (
        previous
        and previous.get("schedule_id")
        and previous["schedule_id"] != schedule_id
        and not workout_replaced
    ):
        client.unschedule_workout(previous["schedule_id"])
        result.add(
            "unschedule",
            definition["name"],
            workout_id=previous.get("workout_id", workout_id),
            schedule_id=previous["schedule_id"],
            date=previous.get("date"),
        )
