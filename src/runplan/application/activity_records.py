"""Normalize linked activities and their aggregate workout result."""

from __future__ import annotations

from typing import Any


def linked_activities(record: dict[str, Any]) -> list[dict[str, Any]]:
    """Return canonical activity entries, adapting legacy scalar tracking."""
    activities = record.get("activities")
    if isinstance(activities, list):
        return [dict(item) for item in activities if isinstance(item, dict)]
    activity_id = record.get("activity_id")
    if activity_id is None:
        return []
    entry = {
        "activity_id": activity_id,
        "link_source": (
            "manual" if record.get("activity_link_source") == "manual" else "automatic"
        ),
        "completed_at": record.get("completed_at"),
        "distance_meters": record.get("actual_distance_meters"),
        "duration_seconds": record.get("actual_duration_seconds"),
    }
    return [{key: value for key, value in entry.items() if value is not None}]


def linked_activity_ids(record: dict[str, Any]) -> set[int]:
    """Return all valid Garmin activity IDs associated with one record."""
    return {
        item["activity_id"]
        for item in linked_activities(record)
        if isinstance(item.get("activity_id"), int)
    }


def apply_linked_activities(record: dict[str, Any], activities: list[dict[str, Any]]) -> None:
    """Replace activity entries and recompute compatibility and actual fields."""
    ordered = sorted(
        (dict(item) for item in activities),
        key=lambda item: (
            item.get("link_source") != "automatic",
            item.get("completed_at", ""),
            item.get("activity_id", 0),
        ),
    )
    for field in (
        "activities",
        "activity_id",
        "activity_link_source",
        "completed_at",
        "actual_distance_meters",
        "actual_duration_seconds",
    ):
        record.pop(field, None)
    if not ordered:
        return
    record["activities"] = ordered
    primary = ordered[0]
    record["activity_id"] = primary["activity_id"]
    if primary.get("link_source") == "manual":
        record["activity_link_source"] = "manual"
    timestamps = [
        item["completed_at"] for item in ordered if isinstance(item.get("completed_at"), str)
    ]
    if timestamps:
        record["completed_at"] = min(timestamps)
    record["actual_distance_meters"] = sum(item["distance_meters"] for item in ordered)
    record["actual_duration_seconds"] = sum(item["duration_seconds"] for item in ordered)


__all__ = ["apply_linked_activities", "linked_activities", "linked_activity_ids"]
