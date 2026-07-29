import pytest

from runplan.integrations.garmin.client import get_all_workouts, scheduled_items_for_dates
from tests.fakes import FakeGarmin


def test_workout_pagination_uses_pages_of_one_hundred() -> None:
    workouts = [{"workoutId": value, "workoutName": f"Workout {value}"} for value in range(205)]
    client = FakeGarmin(workouts=workouts)

    result = get_all_workouts(client)

    assert result == workouts
    assert [event for event in client.events if event[0] == "get_workouts"] == [
        ("get_workouts", 0, 100),
        ("get_workouts", 100, 100),
        ("get_workouts", 200, 100),
    ]


def test_scheduled_lookup_queries_each_month_and_filters_non_workouts() -> None:
    client = FakeGarmin(
        schedules=[
            {"itemType": "workout", "workoutId": 1, "date": "2026-12-31", "id": 11},
            {"itemType": "workout", "workoutId": 2, "date": "2027-01-01", "id": 12},
            {"itemType": "race", "workoutId": 3, "date": "2027-01-02", "id": 13},
        ]
    )

    result = scheduled_items_for_dates(client, {"2026-12-31", "2027-01-01"})

    assert [item["workoutId"] for item in result] == [1, 2]
    assert [event for event in client.events if event[0] == "get_scheduled_workouts"] == [
        ("get_scheduled_workouts", 2026, 12),
        ("get_scheduled_workouts", 2027, 1),
    ]


class CalendarClient:
    def __init__(self, items, activities=None) -> None:
        self.items = items
        self.activities = activities or {}
        self.activity_calls = []

    def get_scheduled_workouts(self, year: int, month: int) -> dict:
        return {"calendarItems": self.items}

    def get_activity(self, activity_id: str) -> dict:
        self.activity_calls.append(activity_id)
        return self.activities.get(
            activity_id,
            {
                "activityId": int(activity_id),
                "summaryDTO": {"distance": 5000, "duration": 1800},
            },
        )


def test_scheduled_lookup_normalizes_garmin_calendar_shape() -> None:
    client = CalendarClient(
        [
            {
                "itemType": "workout",
                "calendarDate": "2026-07-20",
                "workoutScheduleId": 20,
                "workout": {"workoutId": 10},
                "associatedActivityId": 900,
            }
        ],
        {"900": {"activityId": 900, "summaryDTO": {"distance": 5000, "duration": 1800}}},
    )

    result = scheduled_items_for_dates(client, {"2026-07-20"})

    assert result[0]["date"] == "2026-07-20"
    assert result[0]["workoutId"] == 10
    assert result[0]["workoutScheduleId"] == 20
    assert result[0]["associatedActivityId"] == 900


def test_calendar_activity_is_joined_to_workout_through_activity_summary() -> None:
    items = [
        {"itemType": "workout", "date": "2026-07-28", "id": 20, "workoutId": 10},
        {"itemType": "activity", "date": "2026-07-28", "id": 900},
        {"itemType": "activity", "date": "2026-07-28", "id": 901},
    ]
    activities = {
        "900": {
            "activityId": 900,
            "metadataDTO": {"associatedWorkoutId": 10},
            "summaryDTO": {"distance": 11158.74, "duration": 4057.619},
        },
        "901": {"activityId": 901, "metadataDTO": {}, "summaryDTO": {}},
    }

    result = scheduled_items_for_dates(CalendarClient(items, activities), {"2026-07-28"})

    assert result[0]["associatedActivityId"] == 900
    assert result[0]["actualDistanceMeters"] == 11158.74
    assert result[0]["actualDurationSeconds"] == 4057.619


def test_overlapping_month_results_deduplicate_the_same_calendar_activity() -> None:
    items = [
        {"itemType": "workout", "date": "2026-07-27", "id": 20, "workoutId": 10},
        {"itemType": "activity", "date": "2026-07-27", "id": 900},
    ]
    activities = {
        "900": {
            "activityId": 900,
            "metadataDTO": {"associatedWorkoutId": 10},
            "summaryDTO": {"distance": 7593.39, "duration": 2489.549},
        }
    }
    client = CalendarClient(items, activities)

    result = scheduled_items_for_dates(client, {"2026-07-27", "2026-08-02"})

    assert client.activity_calls == ["900"]
    assert result[0]["associatedActivityId"] == 900


def test_distinct_activities_for_same_workout_and_date_remain_a_conflict() -> None:
    items = [
        {"itemType": "workout", "date": "2026-07-27", "id": 20, "workoutId": 10},
        {"itemType": "activity", "date": "2026-07-27", "id": 900},
        {"itemType": "activity", "date": "2026-07-27", "id": 901},
    ]
    activities = {
        value: {
            "activityId": int(value),
            "metadataDTO": {"associatedWorkoutId": 10},
            "summaryDTO": {"distance": 5000, "duration": 1800},
        }
        for value in ("900", "901")
    }

    with pytest.raises(RuntimeError, match="workoutId=10 on 2026-07-27"):
        scheduled_items_for_dates(CalendarClient(items, activities), {"2026-07-27"})
