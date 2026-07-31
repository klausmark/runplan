"""List and persist manual Garmin activity links for web workouts."""

from __future__ import annotations

import logging
from datetime import date, timedelta
from http import HTTPStatus
from typing import TYPE_CHECKING, Any

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
        window_days: Any,
    ) -> dict[str, Any]:
        window = self._window(window_days)
        user = self.sync.users.get(user_id or self.sync.users.default_id)
        program = self.sync.store_for(user.id).get(
            name,
            repository=self.sync.repository_for(user.id, name),
            fallback_pace_value=user.default_pace,
        )
        workout = self._workout(program, week, workout_id)
        if not workout.get("can_link_activity"):
            raise WebError(
                HTTPStatus.CONFLICT, "Only scheduled or missed workouts can link an activity"
            )
        activities = self._activities(name, user.id, program, workout, window)
        return {"revision": program["revision"], "windowDays": window, "activities": activities}

    def link(
        self, name: str, week: str, workout_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        user = self.sync.users.get(request.get("userId") or self.sync.users.default_id)
        self._require_revision(name, user.id, request.get("revision"))
        listing = self.candidates(name, week, workout_id, user.id, request.get("windowDays", 0))
        activity_id = request.get("activityId")
        selected = next((item for item in listing["activities"] if item["id"] == activity_id), None)
        if selected is None:
            raise WebError(HTTPStatus.CONFLICT, "The Garmin activity is no longer available")
        repository = self.sync.repository_for(user.id, name)
        program = self.sync.store_for(user.id).get(
            name, repository=repository, fallback_pace_value=user.default_pace
        )
        workout = self._workout(program, week, workout_id)
        state = repository.load(program["program"]["id"])
        key = self._record_key(week, workout_id)
        record = state["workouts"].get(key)
        if not isinstance(record, dict) or not workout.get("can_link_activity"):
            raise WebError(HTTPStatus.CONFLICT, "The workout can no longer link an activity")
        record.update(
            status="completed",
            activity_id=selected["id"],
            activity_link_source="manual",
            completed_at=selected["startTimeLocal"],
            actual_distance_meters=selected["distanceMeters"],
            actual_duration_seconds=selected["durationSeconds"],
        )
        record.pop("content_hash", None)
        record.pop("description", None)
        repository.save(program["program"]["id"], state)
        logger.info(
            "Garmin activity linked user=%s program_id=%s workout=%s activity_id=%s",
            user.id,
            program["program"]["id"],
            key,
            selected["id"],
        )
        return self.sync.store_for(user.id).get(
            name, repository=repository, fallback_pace_value=user.default_pace
        )

    def unlink(
        self, name: str, week: str, workout_id: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        user = self.sync.users.get(request.get("userId") or self.sync.users.default_id)
        self._require_revision(name, user.id, request.get("revision"))
        repository = self.sync.repository_for(user.id, name)
        program = self.sync.store_for(user.id).get(
            name, repository=repository, fallback_pace_value=user.default_pace
        )
        workout = self._workout(program, week, workout_id)
        if not workout.get("can_unlink_activity"):
            raise WebError(HTTPStatus.CONFLICT, "Only manually linked activities can be unlinked")
        state = repository.load(program["program"]["id"])
        record = state["workouts"].get(self._record_key(week, workout_id))
        if not isinstance(record, dict) or record.get("activity_link_source") != "manual":
            raise WebError(HTTPStatus.CONFLICT, "The activity link can no longer be removed")
        for field in (
            "activity_id",
            "activity_link_source",
            "completed_at",
            "actual_distance_meters",
            "actual_duration_seconds",
        ):
            record.pop(field, None)
        workout_date = date.fromisoformat(workout["date"])
        if workout_date < self.sync.today():
            record["status"] = "missed"
        elif record.get("schedule_id") is not None:
            record["status"] = "scheduled"
        else:
            record["status"] = "planned"
        repository.save(program["program"]["id"], state)
        logger.info(
            "Garmin activity unlinked user=%s program_id=%s workout=%s",
            user.id,
            program["program"]["id"],
            self._record_key(week, workout_id),
        )
        return self.sync.store_for(user.id).get(
            name, repository=repository, fallback_pace_value=user.default_pace
        )

    def _activities(
        self,
        name: str,
        user_id: str,
        program: dict[str, Any],
        workout: dict[str, Any],
        window: int,
    ) -> list[dict[str, Any]]:
        target = date.fromisoformat(workout["date"])
        start = (target - timedelta(days=window)).isoformat()
        end = (target + timedelta(days=window)).isoformat()
        repository = self.sync.repository_for(user_id, name)
        records = list(repository.load(program["program"]["id"])["workouts"].values())
        linked_ids = {
            record["activity_id"]
            for record in records
            if isinstance(record, dict) and record.get("activity_id") is not None
        }
        tracked_workout_ids = {
            record["workout_id"]
            for record in records
            if isinstance(record, dict) and record.get("workout_id") is not None
        }
        try:
            client = self.sync.client_for(user_id)
            summaries = client.get_activities_by_date(start, end, "running")
            result = []
            for item in summaries:
                if not isinstance(item, dict) or not isinstance(item.get("activityId"), int):
                    continue
                detail = client.get_activity(str(item["activityId"]))
                normalized = _candidate(detail, item)
                if normalized is None or normalized["id"] in linked_ids:
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
        result.sort(
            key=lambda item: (
                abs((date.fromisoformat(item["date"]) - target).days),
                item["startTimeLocal"],
            )
        )
        for item in result:
            item.pop("associatedWorkoutId", None)
        return result

    def _require_revision(self, name: str, user_id: str, revision: Any) -> None:
        if revision != self.sync.store_for(user_id).revision(name):
            raise WebError(HTTPStatus.CONFLICT, "The program changed; reload before saving")

    @staticmethod
    def _window(value: Any) -> int:
        try:
            window = int(value)
        except (TypeError, ValueError) as exc:
            raise WebError(HTTPStatus.BAD_REQUEST, "windowDays must be 0 or 3") from exc
        if window not in {0, 3}:
            raise WebError(HTTPStatus.BAD_REQUEST, "windowDays must be 0 or 3")
        return window

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
