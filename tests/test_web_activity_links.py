from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from runplan.web import ProgramStore, WebError, WebSyncService
from tests.fakes import FakeGarmin
from tests.helpers import program_data
from tests.web_helpers import MemoryStateRepository


def activity(
    activity_id: int,
    started: str,
    *,
    distance: float = 10_000.0,
    duration: float = 3_600.0,
    associated_workout_id: int | None = None,
    activity_type: str = "running",
) -> dict:
    metadata = {}
    if associated_workout_id is not None:
        metadata["associatedWorkoutId"] = associated_workout_id
    return {
        "activityId": activity_id,
        "activityName": f"Run {activity_id}",
        "startTimeLocal": started,
        "distance": distance,
        "duration": duration,
        "activityType": {"typeKey": activity_type},
        "summaryDTO": {
            "startTimeLocal": started,
            "distance": distance,
            "duration": duration,
        },
        "metadataDTO": metadata,
    }


@pytest.fixture
def activity_service(tmp_path: Path):
    path = tmp_path / "plan.yaml"
    path.write_text(
        yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    repository = MemoryStateRepository()
    state = repository.load("characterization-plan")
    state["workouts"]["week-01/mixed"] = {
        "week": 1,
        "date": "2026-12-28",
        "name": "Week 1 - Mixed",
        "status": "missed",
        "workout_id": 10,
        "schedule_id": 20,
    }
    state["workouts"]["week-01/easy"] = {
        "week": 1,
        "date": "2026-12-31",
        "name": "Week 1 - Easy",
        "status": "completed",
        "workout_id": 11,
        "activity_id": 902,
        "actual_distance_meters": 5_000.0,
        "actual_duration_seconds": 1_800.0,
        "completed_at": "2026-12-31T08:00:00",
    }
    client = FakeGarmin(
        activities=[
            activity(900, "2026-12-28T18:30:00", distance=6_000, duration=2_100),
            activity(901, "2026-12-27T09:00:00"),
            activity(902, "2026-12-31T08:00:00", distance=5_000, duration=1_800),
            activity(903, "2026-12-28T11:00:00", associated_workout_id=11),
            activity(904, "2026-12-28T12:00:00", activity_type="cycling"),
            activity(905, "2026-12-28T17:00:00", distance=4_000, duration=1_500),
        ]
    )
    store = ProgramStore(tmp_path, repository=repository)
    service = WebSyncService(
        store,
        repository=repository,
        client_factory=lambda: client,
        today=lambda: date(2026, 12, 30),
    )
    return service, repository, client


def test_candidates_query_same_day_and_mark_current_links(activity_service) -> None:
    service, _, client = activity_service

    missed = service.activity_links.candidates("plan.yaml", "1", "mixed", None)
    completed = service.activity_links.candidates("plan.yaml", "1", "easy", None)

    assert [item["id"] for item in missed["activities"]] == [905, 900]
    assert not any(item["selected"] for item in missed["activities"])
    assert [item["id"] for item in completed["activities"]] == [902]
    assert completed["activities"][0]["selected"]
    assert completed["activities"][0]["linkSource"] == "automatic"
    assert [event for event in client.events if event[0] == "get_activities_by_date"] == [
        ("get_activities_by_date", "2026-12-28", "2026-12-28", "running"),
        ("get_activities_by_date", "2026-12-31", "2026-12-31", "running"),
    ]


def test_apply_multiple_activities_sums_actual_result(activity_service) -> None:
    service, repository, client = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    result = service.activity_links.apply(
        "plan.yaml",
        "1",
        "mixed",
        {"revision": revision, "activityIds": [900, 905]},
    )

    record = repository.load("characterization-plan")["workouts"]["week-01/mixed"]
    assert record["status"] == "completed"
    assert [item["activity_id"] for item in record["activities"]] == [905, 900]
    assert {item["link_source"] for item in record["activities"]} == {"manual"}
    assert record["actual_distance_meters"] == 10_000
    assert record["actual_duration_seconds"] == 3_600
    assert record["completed_at"] == "2026-12-28T17:00:00"
    workout = result["weeks"][0]["workouts"][0]
    assert len(workout["activities"]) == 2
    assert not [event for event in client.events if event[0] in {"delete", "unschedule"}]


def test_apply_can_remove_automatic_activity_and_mark_workout_missed(activity_service) -> None:
    service, repository, _ = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    service.activity_links.apply(
        "plan.yaml", "1", "easy", {"revision": revision, "activityIds": []}
    )

    record = repository.load("characterization-plan")["workouts"]["week-01/easy"]
    assert record["status"] == "missed"
    assert "activities" not in record
    assert "activity_id" not in record
    assert "actual_distance_meters" not in record


def test_apply_preserves_automatic_source_and_adds_manual_source(activity_service) -> None:
    service, repository, client = activity_service
    client.activities.append(activity(906, "2026-12-31T09:00:00", distance=2_000, duration=700))
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    service.activity_links.apply(
        "plan.yaml",
        "1",
        "easy",
        {"revision": revision, "activityIds": [902, 906]},
    )

    activities = repository.load("characterization-plan")["workouts"]["week-01/easy"]["activities"]
    assert [(item["activity_id"], item["link_source"]) for item in activities] == [
        (902, "automatic"),
        (906, "manual"),
    ]


def test_apply_rejects_stale_revision_invalid_ids_and_other_date(activity_service) -> None:
    service, repository, _ = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    with pytest.raises(WebError, match="program changed"):
        service.activity_links.apply(
            "plan.yaml", "1", "mixed", {"revision": "stale", "activityIds": [900]}
        )
    with pytest.raises(WebError, match="positive integers"):
        service.activity_links.apply(
            "plan.yaml", "1", "mixed", {"revision": revision, "activityIds": ["900"]}
        )
    with pytest.raises(WebError, match="no longer available"):
        service.activity_links.apply(
            "plan.yaml", "1", "mixed", {"revision": revision, "activityIds": [901]}
        )


def test_scheduled_workout_can_manage_activities(activity_service) -> None:
    service, repository, _ = activity_service
    repository.load("characterization-plan")["workouts"]["week-01/mixed"]["status"] = "scheduled"

    result = service.activity_links.candidates("plan.yaml", "1", "mixed", None)

    assert [item["id"] for item in result["activities"]] == [905, 900]


def test_apply_links_scheduled_workout_as_completed(activity_service) -> None:
    service, repository, _ = activity_service
    repository.load("characterization-plan")["workouts"]["week-01/mixed"]["status"] = "scheduled"
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    service.activity_links.apply(
        "plan.yaml",
        "1",
        "mixed",
        {"revision": revision, "activityIds": [900]},
    )

    record = repository.load("characterization-plan")["workouts"]["week-01/mixed"]
    assert record["status"] == "completed"
    assert [item["activity_id"] for item in record["activities"]] == [900]
    assert {item["link_source"] for item in record["activities"]} == {"manual"}


def test_apply_with_no_selection_keeps_scheduled_status(activity_service) -> None:
    service, repository, _ = activity_service
    repository.load("characterization-plan")["workouts"]["week-01/mixed"]["status"] = "scheduled"
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    service.activity_links.apply(
        "plan.yaml", "1", "mixed", {"revision": revision, "activityIds": []}
    )

    record = repository.load("characterization-plan")["workouts"]["week-01/mixed"]
    assert record["status"] == "scheduled"
    assert "activities" not in record
