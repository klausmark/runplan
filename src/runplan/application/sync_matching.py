"""Resolve whether a planned workout can reuse a tracked Garmin workout."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from .ports import GarminClient
from .results import SyncResult
from .sync_support import content_hash, remote_has_content

logger = logging.getLogger("runplan.application.sync")


@dataclass(frozen=True)
class WorkoutResolution:
    """The Garmin workout selected for scheduling and any record it replaced."""

    workout_id: Any
    replaced: dict[str, Any] | None


def resolve_workout(
    client: GarminClient,
    remote_workouts: list[dict[str, Any]],
    result: SyncResult,
    program_id: str,
    key: str,
    definition: dict[str, Any],
    workout: Any,
    previous: Any,
    payload: dict[str, Any],
    desired_hash: str,
) -> WorkoutResolution:
    """Reuse the tracked workout when unchanged; otherwise upload its replacement."""
    matching = _matching_workout(previous, remote_workouts)
    reusable = _is_reusable(previous, matching, payload, desired_hash)
    _log_match_state(
        program_id, key, definition, previous, matching, reusable, payload, desired_hash
    )
    if reusable:
        workout_id = matching.get("workoutId") if matching else None
        if not workout_id:
            raise RuntimeError(f"Existing workout {definition['name']!r} has no workoutId")
        result.add("reuse", definition["name"], workout_id=workout_id)
        return WorkoutResolution(workout_id, None)

    uploaded = client.upload_running_workout(workout)
    workout_id = uploaded.get("workoutId")
    if not workout_id:
        logger.error(
            "Garmin create response missing workout ID program_id=%s key=%s workout_name=%r",
            program_id,
            key,
            definition["name"],
        )
        raise RuntimeError(f"Upload of {definition['name']!r} did not return workoutId")
    remote_workouts.append({**payload, **uploaded})
    result.add("create", definition["name"], workout_id=workout_id)
    replaced = previous.copy() if previous else None
    return WorkoutResolution(workout_id, replaced)


def _matching_workout(
    previous: Any, remote_workouts: list[dict[str, Any]]
) -> dict[str, Any] | None:
    tracked_id = previous.get("workout_id") if isinstance(previous, dict) else None
    if tracked_id is None:
        return None
    return next((item for item in remote_workouts if item.get("workoutId") == tracked_id), None)


def _is_reusable(
    previous: Any,
    matching: dict[str, Any] | None,
    payload: dict[str, Any],
    desired_hash: str,
) -> bool:
    reusable = bool(
        matching
        and matching.get("workoutName") == payload.get("workoutName")
        and matching.get("description") == payload.get("description")
        and previous
        and previous.get("content_hash") == desired_hash
    )
    if matching and remote_has_content(matching):
        reusable = reusable and content_hash(matching) == desired_hash
    return reusable


def _log_match_state(
    program_id: str,
    key: str,
    definition: dict[str, Any],
    previous: Any,
    matching: dict[str, Any] | None,
    reusable: bool,
    payload: dict[str, Any],
    desired_hash: str,
) -> None:
    tracked_id = previous.get("workout_id") if isinstance(previous, dict) else None
    if isinstance(previous, dict) and tracked_id is None:
        logger.warning(
            "Active workout has no tracked Garmin ID; creating workout program_id=%s key=%s workout_name=%r",
            program_id,
            key,
            definition["name"],
        )
    elif tracked_id is not None and matching is None:
        logger.warning(
            "Tracked Garmin workout not found; recreating program_id=%s key=%s workout_id=%s workout_name=%r",
            program_id,
            key,
            tracked_id,
            definition["name"],
        )
    elif matching is not None and not reusable:
        fields = _changed_fields(previous, matching, payload, desired_hash)
        logger.warning(
            "Tracked Garmin workout changed; replacing program_id=%s key=%s workout_id=%s fields=%s",
            program_id,
            key,
            tracked_id,
            ",".join(fields) or "unknown",
        )


def _changed_fields(
    previous: Any,
    matching: dict[str, Any],
    payload: dict[str, Any],
    desired_hash: str,
) -> list[str]:
    fields = []
    if matching.get("workoutName") != payload.get("workoutName"):
        fields.append("name")
    if matching.get("description") != payload.get("description"):
        fields.append("description")
    if previous and previous.get("content_hash") != desired_hash:
        fields.append("planned_content")
    if remote_has_content(matching) and content_hash(matching) != desired_hash:
        fields.append("remote_content")
    return fields
