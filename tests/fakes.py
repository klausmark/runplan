from __future__ import annotations

import copy

from garminconnect.exceptions import GarminConnectConnectionError


class FakeGarmin:
    def __init__(
        self,
        workouts=None,
        schedules=None,
        fail_upload_number=None,
        activities=None,
        not_found_workout_ids=None,
        not_found_schedule_ids=None,
    ) -> None:
        self.workouts = copy.deepcopy(workouts or [])
        self.schedules = copy.deepcopy(schedules or [])
        self.fail_upload_number = fail_upload_number
        self.upload_count = 0
        self.events: list[tuple] = []
        self.next_workout_id = 1000
        self.next_schedule_id = 2000
        self.activities = copy.deepcopy(activities or [])
        self.not_found_workout_ids = set(not_found_workout_ids or ())
        self.not_found_schedule_ids = set(not_found_schedule_ids or ())

    def get_workouts(self, start: int, limit: int) -> list[dict]:
        self.events.append(("get_workouts", start, limit))
        return copy.deepcopy(self.workouts[start : start + limit])

    def get_scheduled_workouts(self, year: int, month: int) -> dict:
        self.events.append(("get_scheduled_workouts", year, month))
        prefix = f"{year:04d}-{month:02d}"
        return {
            "calendarItems": copy.deepcopy(
                [item for item in self.schedules if item["date"].startswith(prefix)]
            )
        }

    def get_activity(self, activity_id: str) -> dict:
        self.events.append(("get_activity", activity_id))
        match = next(
            (item for item in self.activities if item.get("activityId") == int(activity_id)), None
        )
        if match is not None:
            return copy.deepcopy(match)
        return {
            "activityId": int(activity_id),
            "summaryDTO": {
                "distance": 10_000.0,
                "duration": 3_600.0,
                "startTimeLocal": "2026-07-20T18:30:00",
            },
            "metadataDTO": {},
        }

    def get_activities_by_date(
        self, startdate: str, enddate: str | None = None, activitytype: str | None = None
    ) -> list[dict]:
        self.events.append(("get_activities_by_date", startdate, enddate, activitytype))
        last = enddate or startdate
        return copy.deepcopy(
            [
                item
                for item in self.activities
                if startdate <= str(item.get("startTimeLocal", ""))[:10] <= last
            ]
        )

    def upload_running_workout(self, workout) -> dict:
        self.upload_count += 1
        self.events.append(("upload", workout.workoutName))
        if self.fail_upload_number == self.upload_count:
            raise RuntimeError("simulated upload failure")
        payload = workout.to_dict()
        result = {
            "workoutId": self.next_workout_id,
            "workoutName": payload["workoutName"],
            "description": payload.get("description"),
        }
        self.next_workout_id += 1
        self.workouts.append(result)
        return copy.deepcopy(result)

    def schedule_workout(self, workout_id: int, scheduled_date: str) -> dict:
        self.events.append(("schedule", workout_id, scheduled_date))
        result = {
            "itemType": "workout",
            "workoutId": workout_id,
            "date": scheduled_date,
            "workoutScheduleId": self.next_schedule_id,
            "id": self.next_schedule_id,
        }
        self.next_schedule_id += 1
        self.schedules.append(result)
        return copy.deepcopy(result)

    def unschedule_workout(self, schedule_id: int) -> None:
        self.events.append(("unschedule", schedule_id))
        if schedule_id in self.not_found_schedule_ids:
            raise GarminConnectConnectionError(
                f"API Error 404 - No workout found for workout schedule = {schedule_id}"
            )
        self.schedules = [
            item
            for item in self.schedules
            if item.get("id") != schedule_id and item.get("workoutScheduleId") != schedule_id
        ]

    def delete_workout(self, workout_id: int) -> None:
        self.events.append(("delete", workout_id))
        if workout_id in self.not_found_workout_ids:
            raise GarminConnectConnectionError(
                f"API Error 404 - No workout found for workout = {workout_id}"
            )
        self.workouts = [item for item in self.workouts if item.get("workoutId") != workout_id]
