from __future__ import annotations

from datetime import date

from runplan import (
    load_state,
    save_state,
)
from runplan.application.sync import (
    reconcile_program,
)
from runplan.state.json_repository import JsonStateRepository
from tests.fakes import FakeGarmin
from tests.sync_helpers import SyncTestBase


class TestSyncReconciliation(SyncTestBase):
    def test_reconcile_marks_completed_and_missed_historical_workouts(self) -> None:
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {
                    "week-01/completed": {
                        "week": 1,
                        "workout_id": 10,
                        "schedule_id": 20,
                        "date": "2026-07-20",
                        "name": "Completed workout",
                        "description": "No longer needed after completion",
                        "content_hash": "old-hash",
                        "status": "scheduled",
                    },
                    "week-01/missed": {
                        "week": 1,
                        "workout_id": 11,
                        "schedule_id": 21,
                        "date": "2026-07-21",
                        "name": "Missed workout",
                        "status": "scheduled",
                    },
                },
            },
        )
        client = FakeGarmin(
            schedules=[
                {
                    "itemType": "workout",
                    "workoutId": 10,
                    "date": "2026-07-20",
                    "workoutScheduleId": 20,
                    "associatedActivityId": 900,
                    "associatedActivityDateTime": "2026-07-20T18:30:00",
                },
                {
                    "itemType": "workout",
                    "workoutId": 11,
                    "date": "2026-07-21",
                    "workoutScheduleId": 21,
                    "associatedActivityId": None,
                },
            ]
        )
        result = reconcile_program(
            client, JsonStateRepository(), "characterization-plan", today=date(2026, 7, 22)
        )
        assert ["completed", "missed"] == [a.kind for a in result.actions]
        state = load_state("characterization-plan")["workouts"]
        assert "completed" == state["week-01/completed"]["status"]
        assert 900 == state["week-01/completed"]["activity_id"]
        assert state["week-01/completed"]["activities"][0]["link_source"] == "automatic"
        assert "content_hash" not in state["week-01/completed"]
        assert "description" not in state["week-01/completed"]
        assert "missed" == state["week-01/missed"]["status"]
        repeated = reconcile_program(
            client, JsonStateRepository(), "characterization-plan", today=date(2026, 7, 22)
        )
        assert [] == repeated.actions
