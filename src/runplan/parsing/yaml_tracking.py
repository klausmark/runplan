"""Validate and normalize persisted workout tracking metadata."""

from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..domain.errors import WorkoutDefinitionError


def normalize_tracking(raw: Any, location: str) -> dict[str, Any]:
    """Normalize one tracking mapping, including Garmin and actual fields."""
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(f"{location}: must be an object")
    status = raw.get("status")
    if status not in {"planned", "scheduled", "completed", "missed", "retired"}:
        raise WorkoutDefinitionError(f"{location}.status: invalid status")
    result = dict(raw)
    _validate_synced_week(raw.get("synced_week"), location)
    if raw.get("scheduled_date") is not None:
        result["scheduled_date"] = _iso_date(raw["scheduled_date"], location)
    _validate_content_hash(raw.get("synced_content_hash"), location)
    _validate_garmin(raw.get("garmin"), location)
    actual = raw.get("actual")
    _validate_actual(actual, status, location)
    if isinstance(actual, dict):
        result["actual"] = _normalize_actual(actual, location)
    return result


def _validate_synced_week(value: Any, location: str) -> None:
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value <= 0):
        raise WorkoutDefinitionError(f"{location}.synced_week: must be a positive integer")


def _iso_date(value: Any, location: str) -> str:
    try:
        if isinstance(value, datetime):
            raise ValueError
        parsed = value if isinstance(value, date) else date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise WorkoutDefinitionError(f"{location}.scheduled_date: must be an ISO date") from exc
    return parsed.isoformat()


def _validate_content_hash(value: Any, location: str) -> None:
    if value is not None and (
        not isinstance(value, str) or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None
    ):
        raise WorkoutDefinitionError(f"{location}.synced_content_hash: must be a SHA-256 hash")


def _validate_garmin(value: Any, location: str) -> None:
    if value is None:
        return
    if not isinstance(value, dict):
        raise WorkoutDefinitionError(f"{location}.garmin: must be an object")
    for field in ("workout_id", "schedule_id", "activity_id"):
        item = value.get(field)
        if item is not None and (not isinstance(item, int) or isinstance(item, bool) or item <= 0):
            raise WorkoutDefinitionError(f"{location}.garmin.{field}: must be a positive integer")


def _validate_actual(actual: Any, status: str, location: str) -> None:
    if actual is not None and not isinstance(actual, dict):
        raise WorkoutDefinitionError(f"{location}.actual: must be an object")
    if status == "completed" and not isinstance(actual, dict):
        raise WorkoutDefinitionError(f"{location}.actual: required when completed")
    if not isinstance(actual, dict):
        return
    for field in ("distance_meters", "duration_seconds"):
        value = actual.get(field)
        required = status == "completed"
        if (required or value is not None) and (
            not isinstance(value, (int, float)) or isinstance(value, bool) or value <= 0
        ):
            raise WorkoutDefinitionError(f"{location}.actual.{field}: must be positive")


def _normalize_actual(actual: dict[str, Any], location: str) -> dict[str, Any]:
    result = dict(actual)
    completed_at = actual.get("completed_at")
    if completed_at is None:
        return result
    try:
        parsed = (
            completed_at
            if isinstance(completed_at, datetime)
            else datetime.fromisoformat(completed_at)
        )
    except (TypeError, ValueError) as exc:
        raise WorkoutDefinitionError(
            f"{location}.actual.completed_at: must be an ISO timestamp"
        ) from exc
    result["completed_at"] = parsed.isoformat()
    return result
