"""Logging decorator for Garmin operations performed by the web server."""

from __future__ import annotations

import logging
from time import perf_counter
from typing import Any

from ...application.ports import GarminClient

logger = logging.getLogger(__name__)


class LoggingGarminClient:
    """Log Garmin calls without exposing credentials or response payloads."""

    def __init__(self, client: GarminClient, *, user_id: str) -> None:
        self.client = client
        self.user_id = user_id

    def _call(
        self,
        level: int,
        operation: str,
        callback: Any,
        *,
        context: str = "",
    ) -> Any:
        started = perf_counter()
        suffix = f" {context}" if context else ""
        logger.debug("Garmin %s started user=%s%s", operation, self.user_id, suffix)
        try:
            result = callback()
        except BaseException as exc:
            logger.exception(
                "Garmin %s failed user=%s%s duration_ms=%d",
                operation,
                self.user_id,
                suffix,
                round((perf_counter() - started) * 1000),
            )
            try:
                exc._runplan_logged = True
            except Exception:
                pass
            raise
        logger.log(
            level,
            "Garmin %s succeeded user=%s%s duration_ms=%d",
            operation,
            self.user_id,
            suffix,
            round((perf_counter() - started) * 1000),
        )
        return result

    def get_workouts(self, start: int, limit: int) -> list[dict[str, Any]]:
        return self._call(
            logging.DEBUG,
            "get_workouts",
            lambda: self.client.get_workouts(start=start, limit=limit),
            context=f"start={start} limit={limit}",
        )

    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]:
        return self._call(
            logging.DEBUG,
            "get_scheduled_workouts",
            lambda: self.client.get_scheduled_workouts(year, month),
            context=f"year={year} month={month}",
        )

    def get_activity(self, activity_id: str) -> dict[str, Any]:
        return self._call(
            logging.DEBUG,
            "get_activity",
            lambda: self.client.get_activity(activity_id),
            context=f"activity_id={activity_id}",
        )

    def upload_running_workout(self, workout: Any) -> dict[str, Any]:
        name = getattr(workout, "workoutName", "Unknown workout")
        result = self._call(
            logging.DEBUG,
            "create_workout",
            lambda: self.client.upload_running_workout(workout),
            context=f"workout_name={name!r}",
        )
        logger.info(
            "Garmin workout created user=%s workout_name=%r workout_id=%s",
            self.user_id,
            name,
            result.get("workoutId"),
        )
        return result

    def schedule_workout(self, workout_id: int, scheduled_date: str) -> dict[str, Any]:
        result = self._call(
            logging.DEBUG,
            "schedule_workout",
            lambda: self.client.schedule_workout(workout_id, scheduled_date),
            context=f"workout_id={workout_id} date={scheduled_date}",
        )
        logger.info(
            "Garmin workout scheduled user=%s workout_id=%s schedule_id=%s date=%s",
            self.user_id,
            workout_id,
            result.get("workoutScheduleId", result.get("id")),
            scheduled_date,
        )
        return result

    def unschedule_workout(self, schedule_id: int) -> Any:
        return self._call(
            logging.INFO,
            "unschedule_workout",
            lambda: self.client.unschedule_workout(schedule_id),
            context=f"schedule_id={schedule_id}",
        )

    def delete_workout(self, workout_id: int) -> Any:
        return self._call(
            logging.INFO,
            "delete_workout",
            lambda: self.client.delete_workout(workout_id),
            context=f"workout_id={workout_id}",
        )


__all__ = ["LoggingGarminClient"]
