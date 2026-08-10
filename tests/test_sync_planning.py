from __future__ import annotations

import copy

import pytest

from runplan import (
    save_state,
    state_path,
)
from runplan.application.sync import (
    plan_program_weeks,
    synchronize_program_weeks,
)
from runplan.state.json_repository import JsonStateRepository
from tests.fakes import FakeGarmin
from tests.helpers import compiled_week
from tests.sync_helpers import SyncTestBase


class TestSyncPlanning(SyncTestBase):
    def test_sync_plan_reports_unschedule_when_workout_moves(self) -> None:
        client = FakeGarmin()
        self.sync(client)
        moved_program, moved_compiled = compiled_week(1)
        moved_compiled[0][0]["schedule_date"] = "2026-12-29"
        plan = plan_program_weeks(JsonStateRepository(), [(moved_program, moved_compiled)])
        assert ["reuse", "schedule", "unschedule", "reuse"] == [
            action.kind for action in plan.actions
        ]

    def test_empty_and_overlapping_batches_are_rejected_before_garmin_io(self) -> None:
        client = FakeGarmin()
        week_one = compiled_week(1)
        for selections, message in (
            ([], "at least one selected week"),
            ([week_one, week_one], "overlapping weeks"),
            ([(week_one[0], [])], "no workouts"),
        ):
            with pytest.raises(ValueError, match=message):
                synchronize_program_weeks(client, JsonStateRepository(), selections)
        assert [] == client.events
        assert not state_path("characterization-plan").exists()

    def test_batch_cannot_mix_program_ids(self) -> None:
        client = FakeGarmin()
        other_program, other_compiled = copy.deepcopy(compiled_week(2))
        other_program["program_id"] = "other-plan"
        with pytest.raises(ValueError, match="one program"):
            synchronize_program_weeks(
                client, JsonStateRepository(), [compiled_week(1), (other_program, other_compiled)]
            )
        assert [] == client.events

    def test_sync_plan_is_structured_and_read_only(self) -> None:
        selections = [compiled_week(1), compiled_week(2)]
        repository = JsonStateRepository()
        plan = plan_program_weeks(repository, selections)
        assert (1, 2) == plan.weeks
        assert ["create", "schedule", "create", "schedule", "create", "schedule"] == [
            action.kind for action in plan.actions
        ]
        assert not state_path("characterization-plan").exists()
        assert "characterization-plan" == plan.to_dict()["programId"]

    def test_sync_plan_includes_terminal_cleanup_outside_selected_weeks(self) -> None:
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {
                    "week-09/completed": {
                        "week": 9,
                        "date": "2026-10-20",
                        "name": "Old completed workout",
                        "status": "completed",
                        "workout_id": 90,
                        "schedule_id": 190,
                        "activity_id": 900,
                    }
                },
            },
        )
        plan = plan_program_weeks(JsonStateRepository(), [compiled_week(1)])
        cleanup = [
            (action.kind, action.workout_id, action.schedule_id)
            for action in plan.actions
            if action.name == "Old completed workout"
        ]
        assert [("unschedule", 90, 190), ("delete", 90, None)] == cleanup

    def test_prune_plan_uses_union_of_all_selected_week_keys(self) -> None:
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {
                    "week-01/mixed": {"name": "Week 1 - Mixed"},
                    "week-02/long": {"name": "Week 2 - Long"},
                    "week-09/old": self.old_record(),
                },
            },
        )
        plan = plan_program_weeks(
            JsonStateRepository(), [compiled_week(1), compiled_week(2)], prune=True
        )
        deleted = [action.name for action in plan.actions if action.kind == "delete"]
        assert ["Old workout"] == deleted
        assert "Week 1 - Mixed" not in deleted
        assert "Week 2 - Long" not in deleted

    def test_sync_plan_includes_unschedule_and_delete_for_replaced_workouts(self) -> None:
        client = FakeGarmin()
        self.sync(client)
        changed_program, changed_compiled = compiled_week(1)
        # Mutate the typed Garmin workout's name so its hash no longer matches.
        changed_compiled[0][1].workoutName = "Updated workout name"
        plan = plan_program_weeks(JsonStateRepository(), [(changed_program, changed_compiled)])
        kinds = [action.kind for action in plan.actions]
        # The replacement surfaces update + schedule for the new workout and
        # unschedule + delete for the previously synced Garmin-owned workout.
        assert kinds[:4] == ["update", "schedule", "unschedule", "delete"]
        unschedule = next(action for action in plan.actions if action.kind == "unschedule")
        delete = next(action for action in plan.actions if action.kind == "delete")
        assert unschedule.schedule_id is not None
        assert delete.workout_id is not None
        # The remaining workouts in the program are reused, not duplicated.
        assert "reuse" in kinds[4:]
