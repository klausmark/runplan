from pathlib import Path

import yaml

from runplan.state.yaml_repository import YamlStateRepository
from tests.helpers import program_data


def program_repository(tmp_path: Path) -> tuple[Path, YamlStateRepository]:
    path = tmp_path / "plan.yaml"
    path.write_text(yaml.safe_dump(program_data(), sort_keys=False), encoding="utf-8")
    return path, YamlStateRepository(path)


def test_round_trips_completed_tracking_and_actual_totals(tmp_path: Path) -> None:
    path, repository = program_repository(tmp_path)
    state = repository.load("characterization-plan")
    state["workouts"]["week-01/mixed"] = {
        "week": 1,
        "date": "2026-12-28",
        "status": "completed",
        "workout_id": 10,
        "schedule_id": 20,
        "activity_id": 30,
        "activity_link_source": "manual",
        "content_hash": "abc",
        "completed_at": "2026-12-28T12:00:00",
        "actual_distance_meters": 11158.74,
        "actual_duration_seconds": 4057.619,
    }

    repository.save("characterization-plan", state)
    loaded = repository.load("characterization-plan")["workouts"]["week-01/mixed"]

    assert loaded["status"] == "completed"
    assert loaded["activity_id"] == 30
    assert loaded["activity_link_source"] == "manual"
    assert loaded["activities"] == [
        {
            "activity_id": 30,
            "link_source": "manual",
            "completed_at": "2026-12-28T12:00:00",
            "distance_meters": 11158.74,
            "duration_seconds": 4057.619,
        }
    ]
    assert loaded["actual_distance_meters"] == 11158.74
    assert "owner_id" not in loaded
    persisted = path.read_text(encoding="utf-8")
    assert "tracking:" in persisted
    assert "activities:" in persisted
    assert "activity_link_source:" not in persisted


def test_preserves_removed_workout_tracking_as_program_orphan(tmp_path: Path) -> None:
    _, repository = program_repository(tmp_path)
    state = repository.load("characterization-plan")
    state["workouts"]["week-09/removed"] = {
        "week": 9,
        "date": "2027-02-22",
        "status": "scheduled",
        "workout_id": 99,
    }

    repository.save("characterization-plan", state)

    assert "week-09/removed" in repository.load("characterization-plan")["workouts"]
