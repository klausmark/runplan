from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
from io import StringIO

import pytest

from runplan import (
    delete_all_managed,
    load_state,
    save_state,
    state_path,
    sync_program_week,
)
from runplan.application.sync import (
    cleanup_terminal_workouts,
    synchronize_program_weeks,
)
from runplan.state.json_repository import JsonStateRepository
from tests.fakes import FakeGarmin
from tests.helpers import compiled_week
from tests.sync_helpers import SyncTestBase


class TestSyncCleanup(SyncTestBase):
    def test_prune_only_removes_future_active_workouts(self) -> None:
        records = {
            "week-08/past": {
                **self.old_record(),
                "workout_id": 80,
                "schedule_id": 180,
                "date": "2026-09-01",
                "name": "Past workout",
                "status": "scheduled",
            },
            "week-09/future": {
                **self.old_record(),
                "workout_id": 90,
                "schedule_id": 190,
                "date": "2026-11-01",
                "name": "Future workout",
                "status": "scheduled",
            },
            "week-10/completed": {
                **self.old_record(),
                "workout_id": 100,
                "schedule_id": 200,
                "date": "2026-11-08",
                "name": "Completed workout",
                "status": "completed",
                "activity_id": 300,
            },
        }
        save_state(
            "characterization-plan", {"program_id": "characterization-plan", "workouts": records}
        )
        client = FakeGarmin(
            workouts=[
                {
                    "workoutId": record["workout_id"],
                    "workoutName": record["name"],
                    "description": record["description"],
                }
                for record in records.values()
            ]
        )
        synchronize_program_weeks(
            client, JsonStateRepository(), [compiled_week(1)], prune=True, today=date(2026, 10, 1)
        )
        state = load_state("characterization-plan")["workouts"]
        assert "week-08/past" in state
        assert "missed" == state["week-08/past"]["status"]
        assert "week-09/future" not in state
        assert "week-10/completed" in state
        assert ("delete", 90) in client.events
        assert ("delete", 80) in client.events
        assert ("delete", 100) in client.events
        assert "workout_id" not in state["week-08/past"]
        assert "workout_id" not in state["week-10/completed"]

    def test_terminal_cleanup_removes_remote_objects_but_keeps_completed_result(self) -> None:
        record = {
            **self.old_record(),
            "week": 1,
            "workout_id": 10,
            "schedule_id": 20,
            "date": "2026-07-20",
            "name": "Completed workout",
            "status": "completed",
            "activity_id": 900,
            "completed_at": "2026-07-20T18:30:00",
            "actual_distance_meters": 7593.39,
            "actual_duration_seconds": 2489.549,
        }
        save_state(
            "characterization-plan",
            {"program_id": "characterization-plan", "workouts": {"week-01/completed": record}},
        )
        client = FakeGarmin(
            workouts=[
                {
                    "workoutId": 10,
                    "workoutName": record["name"],
                    "description": record["description"],
                }
            ],
            schedules=[
                {
                    "itemType": "workout",
                    "workoutId": 10,
                    "workoutScheduleId": 20,
                    "date": "2026-07-20",
                }
            ],
        )
        actions = cleanup_terminal_workouts(client, JsonStateRepository(), "characterization-plan")
        assert ["unschedule", "delete"] == [action.kind for action in actions]
        cleaned = load_state("characterization-plan")["workouts"]["week-01/completed"]
        assert "completed" == cleaned["status"]
        assert 900 == cleaned["activity_id"]
        assert 7593.39 == cleaned["actual_distance_meters"]
        assert "schedule_id" not in cleaned
        assert "workout_id" not in cleaned
        assert ("delete", 900) not in client.events

    def test_pending_deletion_removes_remote_objects_and_orphaned_record(self) -> None:
        record = {
            **self.old_record(),
            "workout_id": 10,
            "schedule_id": 20,
            "date": "2026-12-28",
            "name": "Deleted from plan",
            "status": "scheduled",
            "pending_deletion": True,
        }
        save_state(
            "characterization-plan",
            {"program_id": "characterization-plan", "workouts": {"week-01/deleted": record}},
        )
        client = FakeGarmin(
            workouts=[
                {
                    "workoutId": 10,
                    "workoutName": record["name"],
                    "description": record["description"],
                }
            ],
            schedules=[
                {
                    "itemType": "workout",
                    "workoutId": 10,
                    "workoutScheduleId": 20,
                    "date": "2026-12-28",
                }
            ],
        )

        actions = cleanup_terminal_workouts(client, JsonStateRepository(), "characterization-plan")

        assert ["unschedule", "delete"] == [action.kind for action in actions]
        assert "week-01/deleted" not in load_state("characterization-plan")["workouts"]

    def test_terminal_cleanup_clears_ids_when_remote_objects_are_already_missing(self) -> None:
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {
                    "week-01/missed": {
                        "week": 1,
                        "workout_id": 10,
                        "schedule_id": 20,
                        "date": "2026-07-20",
                        "name": "Missed workout",
                        "status": "missed",
                    }
                },
            },
        )
        client = FakeGarmin()
        actions = cleanup_terminal_workouts(client, JsonStateRepository(), "characterization-plan")
        assert [] == actions
        cleaned = load_state("characterization-plan")["workouts"]["week-01/missed"]
        assert "schedule_id" not in cleaned
        assert "workout_id" not in cleaned

    def test_terminal_cleanup_trusts_the_tracked_id_after_remote_edits(self) -> None:
        record = {
            **self.old_record(),
            "workout_id": 10,
            "schedule_id": 20,
            "date": "2026-07-20",
            "name": "Completed workout",
            "status": "completed",
        }
        save_state(
            "characterization-plan",
            {"program_id": "characterization-plan", "workouts": {"week-01/completed": record}},
        )
        client = FakeGarmin(
            workouts=[{"workoutId": 10, "workoutName": "Someone else's workout"}],
            schedules=[
                {
                    "itemType": "workout",
                    "workoutId": 10,
                    "workoutScheduleId": 20,
                    "date": "2026-07-20",
                }
            ],
        )
        cleanup_terminal_workouts(client, JsonStateRepository(), "characterization-plan")
        assert ("unschedule", 20) in client.events
        assert ("delete", 10) in client.events

    def test_terminal_cleanup_checkpoints_unschedule_before_delete_failure(self) -> None:
        record = {
            **self.old_record(),
            "workout_id": 10,
            "schedule_id": 20,
            "date": "2026-07-20",
            "name": "Missed workout",
            "status": "missed",
        }
        save_state(
            "characterization-plan",
            {"program_id": "characterization-plan", "workouts": {"week-01/missed": record}},
        )

        class DeleteFailure(FakeGarmin):
            def delete_workout(self, workout_id: int) -> None:
                self.events.append(("delete_failed", workout_id))
                raise RuntimeError("simulated delete failure")

        client = DeleteFailure(
            workouts=[
                {
                    "workoutId": 10,
                    "workoutName": record["name"],
                    "description": record["description"],
                }
            ],
            schedules=[
                {
                    "itemType": "workout",
                    "workoutId": 10,
                    "workoutScheduleId": 20,
                    "date": "2026-07-20",
                }
            ],
        )
        with pytest.raises(RuntimeError, match="simulated delete failure"):
            cleanup_terminal_workouts(client, JsonStateRepository(), "characterization-plan")
        checkpoint = load_state("characterization-plan")["workouts"]["week-01/missed"]
        assert "schedule_id" not in checkpoint
        assert 10 == checkpoint["workout_id"]

    def test_obsolete_workout_is_removed_only_after_new_week_is_complete(self) -> None:
        old = self.old_record()
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "active_week": 9,
                "workouts": {"week-09/old": old},
            },
        )
        client = FakeGarmin(
            workouts=[
                {"workoutId": 99, "workoutName": "Old workout", "description": "Owned description"}
            ]
        )
        program, compiled = compiled_week(1)
        synchronize_program_weeks(client, JsonStateRepository(), [(program, compiled)], prune=True)
        event_names = [event[0] for event in client.events]
        last_schedule = max((index for index, name in enumerate(event_names) if name == "schedule"))
        assert event_names.index("unschedule") > last_schedule
        assert event_names.index("delete") > last_schedule
        state = load_state("characterization-plan")
        assert "week-09/old" not in state["workouts"]

    def test_upload_failure_keeps_previous_week_and_skips_cleanup(self) -> None:
        old = self.old_record()
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "active_week": 9,
                "workouts": {"week-09/old": old},
            },
        )
        client = FakeGarmin(
            workouts=[
                {"workoutId": 99, "workoutName": "Old workout", "description": "Owned description"}
            ],
            fail_upload_number=2,
        )
        program, compiled = compiled_week(1)
        with (
            pytest.raises(RuntimeError, match="simulated upload failure"),
            redirect_stdout(StringIO()),
        ):
            sync_program_week(client, program, compiled)
        assert not any(event[0] == "delete" for event in client.events)
        assert not any(event[0] == "unschedule" for event in client.events)
        state = load_state("characterization-plan")
        assert "week-09/old" in state["workouts"]
        assert "week-01/mixed" in state["workouts"]

    def test_prune_trusts_tracked_id_when_remote_workout_was_edited(self) -> None:
        old = self.old_record()
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "active_week": 9,
                "workouts": {"week-09/old": old},
            },
        )
        client = FakeGarmin(
            workouts=[
                {
                    "workoutId": 99,
                    "workoutName": "Someone else's workout",
                    "description": "Do not delete",
                }
            ]
        )
        program, compiled = compiled_week(1)
        with redirect_stdout(StringIO()):
            synchronize_program_weeks(
                client, JsonStateRepository(), [(program, compiled)], prune=True
            )
        assert ("delete", 99) in client.events
        assert ("unschedule", 199) in client.events
        assert "week-09/old" not in load_state("characterization-plan")["workouts"]

    def test_delete_all_unschedules_then_deletes_only_owned_records(self) -> None:
        old = self.old_record()
        save_state(
            "characterization-plan",
            {"program_id": "characterization-plan", "workouts": {"week-09/old": old}},
        )
        client = FakeGarmin(
            workouts=[
                {"workoutId": 99, "workoutName": "Old workout", "description": "Owned description"},
                {"workoutId": 77, "workoutName": "Unmanaged", "description": "Untouched"},
            ]
        )
        program, compiled = compiled_week(1)
        with redirect_stdout(StringIO()):
            deleted = delete_all_managed(client, program, compiled)
        assert 1 == deleted
        assert client.events.index(("unschedule", 199)) < client.events.index(("delete", 99))
        assert 77 in [item["workoutId"] for item in client.workouts]
        assert not state_path("characterization-plan").exists()
