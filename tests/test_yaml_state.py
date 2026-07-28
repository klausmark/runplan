from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import yaml

from runplan.state.yaml_repository import YamlStateRepository
from tests.helpers import program_data


class YamlStateRepositoryTests(unittest.TestCase):
    def test_round_trips_completed_tracking_and_actual_totals(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.yaml"
            path.write_text(yaml.safe_dump(program_data(), sort_keys=False), encoding="utf-8")
            repository = YamlStateRepository(path, owner_id="alice")
            state = repository.load("characterization-plan")
            state["workouts"]["week-01/mixed"] = {
                "week": 1,
                "date": "2026-12-28",
                "status": "completed",
                "workout_id": 10,
                "schedule_id": 20,
                "activity_id": 30,
                "content_hash": "abc",
                "completed_at": "2026-12-28T12:00:00",
                "actual_distance_meters": 11158.74,
                "actual_duration_seconds": 4057.619,
            }

            repository.save("characterization-plan", state)
            loaded = repository.load("characterization-plan")["workouts"]["week-01/mixed"]

            self.assertEqual("completed", loaded["status"])
            self.assertEqual(30, loaded["activity_id"])
            self.assertEqual(11158.74, loaded["actual_distance_meters"])
            self.assertEqual("alice", loaded["owner_id"])
            self.assertIn("tracking:", path.read_text(encoding="utf-8"))

    def test_preserves_removed_workout_tracking_as_program_orphan(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "plan.yaml"
            path.write_text(yaml.safe_dump(program_data(), sort_keys=False), encoding="utf-8")
            repository = YamlStateRepository(path)
            state = repository.load("characterization-plan")
            state["workouts"]["week-09/removed"] = {
                "week": 9, "date": "2027-02-22", "status": "scheduled", "workout_id": 99
            }

            repository.save("characterization-plan", state)

            self.assertIn(
                "week-09/removed",
                repository.load("characterization-plan")["workouts"],
            )


if __name__ == "__main__":
    unittest.main()
