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
        "distance": 10_000.0,
        "duration": 3_600.0,
        "activityType": {"typeKey": activity_type},
        "summaryDTO": {
            "startTimeLocal": started,
            "distance": 10_000.0,
            "duration": 3_600.0,
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
    }
    client = FakeGarmin(
        activities=[
            activity(900, "2026-12-28T18:30:00"),
            activity(901, "2026-12-27T09:00:00"),
            activity(902, "2026-12-28T10:00:00"),
            activity(903, "2026-12-28T11:00:00", associated_workout_id=11),
            activity(904, "2026-12-28T12:00:00", activity_type="cycling"),
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


def test_candidates_only_query_running_activities_on_workout_date(activity_service) -> None:
    service, _, client = activity_service

    result = service.activity_links.candidates("plan.yaml", "1", "mixed", None)

    assert [item["id"] for item in result["activities"]] == [900]
    assert [event for event in client.events if event[0] == "get_activities_by_date"] == [
        ("get_activities_by_date", "2026-12-28", "2026-12-28", "running"),
    ]


def test_link_persists_manual_completed_result_without_mutating_garmin(activity_service) -> None:
    service, repository, client = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    result = service.activity_links.link(
        "plan.yaml",
        "1",
        "mixed",
        {"revision": revision, "activityId": 900},
    )

    record = repository.load("characterization-plan")["workouts"]["week-01/mixed"]
    assert record["status"] == "completed"
    assert record["activity_id"] == 900
    assert record["activity_link_source"] == "manual"
    assert record["workout_id"] == 10
    assert record["schedule_id"] == 20
    workout = result["weeks"][0]["workouts"][0]
    assert workout["can_unlink_activity"]
    assert not [event for event in client.events if event[0] in {"delete", "unschedule"}]


def test_unlink_manual_activity_restores_missed_status(activity_service) -> None:
    service, repository, _ = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]
    linked = service.activity_links.link(
        "plan.yaml",
        "1",
        "mixed",
        {"revision": revision, "activityId": 900},
    )

    service.activity_links.unlink("plan.yaml", "1", "mixed", {"revision": linked["revision"]})

    record = repository.load("characterization-plan")["workouts"]["week-01/mixed"]
    assert record["status"] == "missed"
    assert "activity_id" not in record
    assert "activity_link_source" not in record


def test_link_rejects_stale_revision_and_activity_from_another_date(activity_service) -> None:
    service, repository, _ = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    with pytest.raises(WebError, match="program changed"):
        service.activity_links.link(
            "plan.yaml", "1", "mixed", {"revision": "stale", "activityId": 900}
        )
    with pytest.raises(WebError, match="no longer available"):
        service.activity_links.link(
            "plan.yaml",
            "1",
            "mixed",
            {"revision": revision, "activityId": 901},
        )


def test_scheduled_workout_cannot_link_activity(activity_service) -> None:
    service, repository, _ = activity_service
    repository.load("characterization-plan")["workouts"]["week-01/mixed"]["status"] = "scheduled"

    with pytest.raises(WebError, match="Only missed workouts"):
        service.activity_links.candidates("plan.yaml", "1", "mixed", None)


def test_automatic_activity_link_cannot_be_unlinked(activity_service) -> None:
    service, repository, _ = activity_service
    revision = service.store.get("plan.yaml", repository=repository)["revision"]

    with pytest.raises(WebError, match="manually linked"):
        service.activity_links.unlink("plan.yaml", "1", "easy", {"revision": revision})
