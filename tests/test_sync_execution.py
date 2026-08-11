from __future__ import annotations

from contextlib import redirect_stdout
from datetime import date
from io import StringIO

import pytest

from runplan import (
    build_workout,
    load_state,
    save_state,
    state_path,
    sync_program_week,
)
from runplan.application.sync import (
    plan_program_weeks,
    synchronize_program_week,
    synchronize_program_weeks,
)
from runplan.state.json_repository import JsonStateRepository
from tests.fakes import FakeGarmin
from tests.helpers import compiled_week
from tests.sync_helpers import SyncTestBase


class TestSyncExecution(SyncTestBase):
    def test_first_sync_uploads_schedules_and_persists_each_workout(self) -> None:
        client = FakeGarmin()
        program, _ = self.sync(client)
        assert 2 == len([event for event in client.events if event[0] == "upload"])
        assert 2 == len([event for event in client.events if event[0] == "schedule"])
        state = load_state(program["program_id"])
        assert 1 == state["active_week"]
        assert {"week-01/mixed", "week-01/easy"} == set(state["workouts"])
        assert 1000 == state["workouts"]["week-01/mixed"]["workout_id"]
        assert state_path(program["program_id"]).exists()

    def test_second_sync_reuses_remote_workouts_and_schedules(self) -> None:
        client = FakeGarmin()
        self.sync(client)
        client.events.clear()
        self.sync(client)
        assert not any(event[0] == "upload" for event in client.events)
        assert not any(event[0] == "schedule" for event in client.events)
        assert not any(event[0] == "delete" for event in client.events)
        assert not any(event[0] == "unschedule" for event in client.events)

    def test_moving_workout_schedules_new_date_and_unschedules_old_date(self) -> None:
        client = FakeGarmin()
        program, compiled = self.sync(client)
        old_date = compiled[0][0]["schedule_date"]
        old_schedule_id = load_state(program["program_id"])["workouts"]["week-01/mixed"][
            "schedule_id"
        ]
        client.events.clear()
        moved_program, moved_compiled = compiled_week(1)
        moved_compiled[0][0]["schedule_date"] = "2026-12-29"
        result = synchronize_program_week(
            client, JsonStateRepository(), moved_program, moved_compiled
        )
        assert ("schedule", 1000, "2026-12-29") in client.events
        assert ("unschedule", old_schedule_id) in client.events
        assert client.events.index(("schedule", 1000, "2026-12-29")) < client.events.index(
            ("unschedule", old_schedule_id)
        )
        assert ("upload", moved_compiled[0][0]["name"]) not in client.events
        assert ("delete", 1000) not in client.events
        assert (1000, old_date) not in [
            (item["workoutId"], item["date"]) for item in client.schedules
        ]
        record = load_state(program["program_id"])["workouts"]["week-01/mixed"]
        assert "2026-12-29" == record["date"]
        assert ["reuse", "schedule", "unschedule", "reuse", "already_scheduled"] == [
            action.kind for action in result.actions
        ]

    def test_state_loss_creates_new_objects_instead_of_adopting_remote_matches(self) -> None:
        client = FakeGarmin()
        selection = compiled_week(1)
        synchronize_program_weeks(
            client, JsonStateRepository(), [selection], today=date(2026, 12, 28)
        )
        original_ids = {item["workoutId"] for item in client.workouts}
        JsonStateRepository().delete("characterization-plan")
        synchronize_program_weeks(
            client, JsonStateRepository(), [selection], today=date(2026, 12, 28)
        )
        tracked_ids = {
            record["workout_id"]
            for record in load_state("characterization-plan")["workouts"].values()
        }
        assert tracked_ids.isdisjoint(original_ids)
        assert original_ids.issubset({item["workoutId"] for item in client.workouts})

    def test_missing_tracked_garmin_id_is_logged_before_recreation(self, caplog) -> None:
        client = FakeGarmin()
        selection = compiled_week(1)
        synchronize_program_weeks(client, JsonStateRepository(), [selection])
        missing_id = load_state("characterization-plan")["workouts"]["week-01/mixed"]["workout_id"]
        client.workouts = [item for item in client.workouts if item["workoutId"] != missing_id]
        with caplog.at_level("WARNING", logger="runplan.application.sync"):
            synchronize_program_weeks(client, JsonStateRepository(), [selection])
        assert f"workout_id={missing_id}" in caplog.text
        assert "Tracked Garmin workout not found; recreating" in caplog.text

    def test_untracked_same_name_and_description_is_not_adopted_or_deleted(self) -> None:
        client = FakeGarmin()
        program, compiled = compiled_week(1)
        existing_definition, existing_workout = compiled[0]
        existing_payload = existing_workout.to_dict()
        client.workouts.append({"workoutId": 50, **existing_payload})
        changed_program, changed_compiled = compiled_week(1)
        changed_compiled[0][0]["steps"][0] = {"warmup": {"distance": "2km"}}
        changed_definition = changed_compiled[0][0]
        changed_compiled[0] = (changed_definition, build_workout(changed_definition))
        with redirect_stdout(StringIO()):
            sync_program_week(client, changed_program, changed_compiled)
        assert ("upload", existing_definition["name"]) in client.events
        assert ("delete", 50) not in client.events
        assert 50 in [item["workoutId"] for item in client.workouts]

    def test_application_sync_returns_actions_without_writing_to_stdout(self) -> None:
        client = FakeGarmin()
        program, compiled = compiled_week(1)
        output = StringIO()
        with redirect_stdout(output):
            result = synchronize_program_week(client, JsonStateRepository(), program, compiled)
        assert "" == output.getvalue()
        assert program["program_id"] == result.program_id
        assert ["create", "schedule", "create", "schedule"] == [
            action.kind for action in result.actions
        ]
        assert "content_hash" in load_state(program["program_id"])["workouts"]["week-01/mixed"]

    def test_multi_week_sync_is_additive_by_default(self) -> None:
        client = FakeGarmin()
        week_one = compiled_week(1)
        week_two = compiled_week(2)
        results = synchronize_program_weeks(client, JsonStateRepository(), [week_one, week_two])
        assert [1, 2] == [result.week for result in results]
        assert not any(event[0] == "delete" for event in client.events)
        assert not any(event[0] == "unschedule" for event in client.events)
        assert {"week-01/mixed", "week-01/easy", "week-02/long"} == set(
            load_state("characterization-plan")["workouts"]
        )

    def test_skipping_then_syncing_a_later_week_preserves_existing_state(self) -> None:
        client = FakeGarmin()
        synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(1)])
        client.events.clear()
        synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(2)])
        assert not any(event[0] in ("delete", "unschedule") for event in client.events)
        assert {"week-01/mixed", "week-01/easy", "week-02/long"} == set(
            load_state("characterization-plan")["workouts"]
        )

    def test_remote_edits_are_replaced_using_the_tracked_id(self, caplog) -> None:
        client = FakeGarmin()
        synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(1)])
        old_id = client.workouts[0]["workoutId"]
        client.workouts[0]["description"] = "Conflicting remote workout"
        client.events.clear()
        with caplog.at_level("WARNING", logger="runplan.application.sync"):
            synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(1)])
        assert ("delete", old_id) in client.events
        record = load_state("characterization-plan")["workouts"]["week-01/mixed"]
        assert old_id != record["workout_id"]
        replacement = next(
            item for item in client.workouts if item["workoutId"] == record["workout_id"]
        )
        assert "[runplan:" not in (replacement.get("description") or "")
        assert "Tracked Garmin workout changed; replacing" in caplog.text

    def test_missing_ids_in_garmin_responses_are_logged_as_errors(self, caplog) -> None:

        class MissingWorkoutId(FakeGarmin):
            def upload_running_workout(self, workout) -> dict:
                self.events.append(("upload", workout.workoutName))
                return {}

        with caplog.at_level("ERROR", logger="runplan.application.sync"):
            with pytest.raises(RuntimeError, match="did not return workoutId"):
                synchronize_program_weeks(
                    MissingWorkoutId(), JsonStateRepository(), [compiled_week(1)]
                )
        assert "create response missing workout ID" in caplog.text

    def test_retry_after_partial_failure_reuses_completed_work(self) -> None:
        client = FakeGarmin(fail_upload_number=2)
        selection = compiled_week(1)
        with pytest.raises(RuntimeError, match="simulated upload failure"):
            synchronize_program_weeks(client, JsonStateRepository(), [selection])
        assert {"week-01/mixed"} == set(load_state("characterization-plan")["workouts"])
        client.fail_upload_number = None
        client.events.clear()
        results = synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(1)])
        assert ["reuse", "already_scheduled", "create", "schedule"] == [
            action.kind for action in results[0].actions
        ]
        assert [("upload", "Week 1 - Easy")] == [
            event for event in client.events if event[0] == "upload"
        ]
        assert {"week-01/mixed", "week-01/easy"} == set(
            load_state("characterization-plan")["workouts"]
        )

    def test_completed_workout_is_reported_and_never_recreated(self) -> None:
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {
                    "week-01/mixed": {
                        "week": 1,
                        "date": "2026-12-28",
                        "name": "Week 1 - Mixed",
                        "status": "completed",
                        "activity_id": 900,
                    }
                },
            },
        )
        selection = compiled_week(1)
        plan = plan_program_weeks(JsonStateRepository(), [selection])
        client = FakeGarmin()
        results = synchronize_program_weeks(
            client, JsonStateRepository(), [selection], today=date(2026, 12, 29)
        )
        assert "completed" == plan.actions[0].kind
        assert "completed" == results[0].actions[0].kind
        uploads = [event for event in client.events if event[0] == "upload"]
        assert [("upload", "Week 1 - Easy")] == uploads

    def test_untracked_past_workouts_become_missed_instead_of_being_scheduled(self) -> None:
        selection = compiled_week(1)
        plan = plan_program_weeks(JsonStateRepository(), [selection], today=date(2027, 1, 1))
        client = FakeGarmin()
        results = synchronize_program_weeks(
            client, JsonStateRepository(), [selection], today=date(2027, 1, 1)
        )
        assert ["missed", "missed"] == [a.kind for a in plan.actions]
        assert ["missed", "missed"] == [a.kind for a in results[0].actions]
        assert not any(event[0] == "upload" for event in client.events)
        assert not any(event[0] == "schedule" for event in client.events)
        state = load_state("characterization-plan")["workouts"]
        assert "missed" == state["week-01/mixed"]["status"]
        assert "missed" == state["week-01/easy"]["status"]

    def test_replaced_workout_cleanup_ignores_missing_garmin_objects(self) -> None:
        old_record = {
            "week": 1,
            "workout_id": 42,
            "schedule_id": 142,
            "date": "2026-12-28",
            "name": "Week 1 - Mixed",
            "description": "Stale description",
            "content_hash": "stale",
            "status": "scheduled",
        }
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {"week-01/mixed": old_record},
            },
        )
        client = FakeGarmin(
            workouts=[
                {
                    "workoutId": 42,
                    "workoutName": "Week 1 - Mixed",
                    "description": "Stale description",
                    "workoutSegments": [],
                    "estimatedDurationInSecs": 1,
                }
            ],
            not_found_workout_ids={42},
            not_found_schedule_ids={142},
        )
        selection = compiled_week(1)
        synchronize_program_weeks(client, JsonStateRepository(), [selection])
        assert ("delete", 42) in client.events
        assert ("unschedule", 142) in client.events
