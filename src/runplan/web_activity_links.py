"""List and persist manual Garmin activity links for web workouts."""

from __future__ import annotations

import logging
from datetime import date
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

from .application.activity_records import (
    apply_linked_activities,
    linked_activities,
    linked_activity_ids,
)
from .users import WebError

if TYPE_CHECKING:
    from .web import WebSyncService

logger = logging.getLogger("runplan.web")


def _positive_number(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0:
        return float(value)
    return None


def _activity_type(activity: dict[str, Any]) -> str | None:
    value = activity.get("activityTypeDTO", activity.get("activityType"))
    if isinstance(value, dict):
        key = value.get("typeKey", value.get("key"))
        return key if isinstance(key, str) else None
    return value if isinstance(value, str) else None


def _candidate(summary: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any] | None:
    details = summary.get("summaryDTO")
    details = details if isinstance(details, dict) else summary
    activity_id = summary.get("activityId", fallback.get("activityId"))
    distance = _positive_number(details.get("distance", fallback.get("distance")))
    duration = _positive_number(details.get("duration", fallback.get("duration")))
    started = details.get("startTimeLocal", fallback.get("startTimeLocal"))
    if (
        not isinstance(activity_id, int)
        or isinstance(activity_id, bool)
        or activity_id <= 0
        or distance is None
        or duration is None
        or not isinstance(started, str)
        or len(started) < 10
    ):
        return None
    explicit_type = _activity_type(summary) or _activity_type(fallback)
    if explicit_type is not None and "run" not in explicit_type.lower():
        return None
    name = summary.get("activityName", fallback.get("activityName", "Garmin run"))
    metadata = summary.get("metadataDTO")
    metadata = metadata if isinstance(metadata, dict) else {}
    return {
        "id": activity_id,
        "name": name if isinstance(name, str) and name.strip() else "Garmin run",
        "startTimeLocal": started,
        "date": started[:10],
        "distanceMeters": distance,
        "durationSeconds": duration,
        "associatedWorkoutId": metadata.get("associatedWorkoutId"),
    }


class WebActivityLinkService:
    """Coordinate read-only Garmin discovery and local activity-link persistence."""

    def __init__(self, sync: WebSyncService) -> None:
        self.sync = sync

    def candidates(
        self,
        name: str,
        week: str,
        workout_id: str,
        user_id: str | None,
    ) -> dict[str, Any]:
        user = self.sync.users.get(user_id or self.sync.users.default_id)
        program = self.sync.store_for(user.id).get(
            name,
            repository=self.sync.repository_for(user.id, name),
            fallback_pace_value=user.default_pace,
        )
        workout = self._workout(program, week, workout_id)
        if not workout.get("can_manage_activities"):
            raise WebError(
                HTTPStatus.CONFLICT, "Only missed or completed workouts can manage activities"
            )
        activities = self._activities(name, user.id, program, week, workout)
        return {"revision": program["revision"], "activities": activities}

    def apply(
        self, name: str, week: str, workout_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        user = self.sync.users.get(request.get("userId") or self.sync.users.default_id)
        self._require_revision(name, user.id, request.get("revision"))
        listing = self.candidates(name, week, workout_id, user.id)
        selected_ids = self._selected_ids(request.get("activityIds"))
        available = {item["id"]: item for item in listing["activities"]}
        if not selected_ids.issubset(available):
            raise WebError(HTTPStatus.CONFLICT, "A Garmin activity is no longer available")
        repository = self.sync.repository_for(user.id, name)
        program = self.sync.store_for(user.id).get(
            name, repository=repository, fallback_pace_value=user.default_pace
        )
        workout = self._workout(program, week, workout_id)
        state = repository.load(program["program"]["id"])
        key = self._record_key(week, workout_id)
        record = state["workouts"].get(key)
        if not isinstance(record, dict) or not workout.get("can_manage_activities"):
            raise WebError(HTTPStatus.CONFLICT, "The workout can no longer manage activities")
        current = {item["activity_id"]: item for item in linked_activities(record)}
        selected = []
        for activity_id in selected_ids:
            item = available[activity_id]
            previous = current.get(activity_id, {})
            selected.append(
                {
                    "activity_id": activity_id,
                    "link_source": previous.get("link_source", "manual"),
                    "name": item["name"],
                    "completed_at": item["startTimeLocal"],
                    "distance_meters": item["distanceMeters"],
                    "duration_seconds": item["durationSeconds"],
                }
            )
        apply_linked_activities(record, selected)
        record["status"] = "completed" if selected else "missed"
        if selected:
            record.pop("content_hash", None)
            record.pop("description", None)
        repository.save(program["program"]["id"], state)
        logger.info(
            "Garmin activity links updated user=%s program_id=%s workout=%s activities=%s",
            user.id,
            program["program"]["id"],
            key,
            ",".join(str(value) for value in sorted(selected_ids)) or "none",
        )
        return self.sync.store_for(user.id).get(
            name, repository=repository, fallback_pace_value=user.default_pace
        )

    def _activities(
        self,
        name: str,
        user_id: str,
        program: dict[str, Any],
        week: str,
        workout: dict[str, Any],
    ) -> list[dict[str, Any]]:
        target = date.fromisoformat(workout["date"])
        activity_date = target.isoformat()
        repository = self.sync.repository_for(user_id, name)
        records_by_key = repository.load(program["program"]["id"])["workouts"]
        target_key = self._record_key(week, workout["id"])
        target_record = records_by_key.get(target_key, {})
        current = {
            item["activity_id"]: item
            for item in linked_activities(target_record)
            if isinstance(item.get("activity_id"), int)
        }
        linked_elsewhere = {
            activity_id
            for key, record in records_by_key.items()
            if key != target_key and isinstance(record, dict)
            for activity_id in linked_activity_ids(record)
        }
        tracked_workout_ids = {
            record["workout_id"]
            for key, record in records_by_key.items()
            if key != target_key
            if isinstance(record, dict) and record.get("workout_id") is not None
        }
        try:
            client = self.sync.client_for(user_id)
            summaries = client.get_activities_by_date(activity_date, activity_date, "running")
            result = []
            for item in summaries:
                if not isinstance(item, dict) or not isinstance(item.get("activityId"), int):
                    continue
                detail = client.get_activity(str(item["activityId"]))
                normalized = _candidate(detail, item)
                if normalized is None or normalized["id"] in linked_elsewhere:
                    continue
                if normalized["associatedWorkoutId"] in tracked_workout_ids:
                    continue
                result.append(normalized)
        except WebError:
            raise
        except BaseException as exc:
            raise WebError(
                HTTPStatus.BAD_GATEWAY, f"Could not read Garmin activities: {exc}"
            ) from exc
        by_id = {item["id"]: item for item in result}
        for activity_id, entry in current.items():
            by_id.setdefault(activity_id, self._stored_candidate(entry, activity_date))
        result = list(by_id.values())
        result.sort(key=lambda item: (item["startTimeLocal"], item["id"]))
        for item in result:
            item.pop("associatedWorkoutId", None)
            previous = current.get(item["id"])
            item["selected"] = previous is not None
            item["linkSource"] = previous.get("link_source") if previous else None
        return result

    @staticmethod
    def _stored_candidate(entry: dict[str, Any], activity_date: str) -> dict[str, Any]:
        return {
            "id": entry["activity_id"],
            "name": entry.get("name", f"Garmin activity {entry['activity_id']}"),
            "startTimeLocal": entry.get("completed_at", f"{activity_date}T00:00:00"),
            "date": str(entry.get("completed_at", activity_date))[:10],
            "distanceMeters": entry["distance_meters"],
            "durationSeconds": entry["duration_seconds"],
        }

    @staticmethod
    def _selected_ids(value: Any) -> set[int]:
        if not isinstance(value, list):
            raise WebError(HTTPStatus.BAD_REQUEST, "activityIds must be a list")
        if any(not isinstance(item, int) or isinstance(item, bool) or item <= 0 for item in value):
            raise WebError(HTTPStatus.BAD_REQUEST, "activityIds must contain positive integers")
        if len(set(value)) != len(value):
            raise WebError(HTTPStatus.BAD_REQUEST, "activityIds must be unique")
        return set(value)

    def _require_revision(self, name: str, user_id: str, revision: Any) -> None:
        if revision != self.sync.store_for(user_id).revision(name):
            raise WebError(HTTPStatus.CONFLICT, "The program changed; reload before saving")

    @staticmethod
    def _record_key(week: str, workout_id: str) -> str:
        try:
            number = int(week)
        except ValueError as exc:
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid workout week") from exc
        return f"week-{number:02d}/{workout_id}"

    @staticmethod
    def _workout(program: dict[str, Any], week: str, workout_id: str) -> dict[str, Any]:
        try:
            number = int(week)
        except ValueError as exc:
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid workout week") from exc
        for program_week in program["weeks"]:
            if program_week["week"] == number:
                for workout in program_week["workouts"]:
                    if workout["id"] == workout_id:
                        return workout
        raise WebError(HTTPStatus.NOT_FOUND, "Workout not found")


__all__ = ["WebActivityLinkService"]
