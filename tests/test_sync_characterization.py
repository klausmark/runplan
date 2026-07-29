from __future__ import annotations

import copy
from contextlib import redirect_stdout
from datetime import date
from io import StringIO

import pytest

from runplan import (
    build_workout,
    delete_all_managed,
    load_state,
    save_state,
    state_path,
    sync_program_week,
)
from runplan.application.sync import (
    cleanup_terminal_workouts,
    plan_program_weeks,
    reconcile_program,
    synchronize_program_week,
    synchronize_program_weeks,
)
from runplan.state.json_repository import JsonStateRepository
from tests.fakes import FakeGarmin
from tests.helpers import compiled_week


class TestSyncCharacterization:
    @pytest.fixture(autouse=True)
    def isolated_state_directory(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("GARMIN_STATE_DIR", str(tmp_path))

    def _sync(self, client: FakeGarmin, week: int = 1):
        program, compiled = compiled_week(week)
        with redirect_stdout(StringIO()):
            sync_program_week(client, program, compiled)
        return (program, compiled)

    def _old_record(self) -> dict:
        return {
            "week": 9,
            "workout_id": 99,
            "schedule_id": 199,
            "date": "2026-11-01",
            "name": "Old workout",
            "description": "Owned description",
        }

    def test_first_sync_uploads_schedules_and_persists_each_workout(self) -> None:
        client = FakeGarmin()
        program, _ = self._sync(client)
        assert 2 == len([event for event in client.events if event[0] == "upload"])
        assert 2 == len([event for event in client.events if event[0] == "schedule"])
        state = load_state(program["program_id"])
        assert 1 == state["active_week"]
        assert {"week-01/mixed", "week-01/easy"} == set(state["workouts"])
        assert 1000 == state["workouts"]["week-01/mixed"]["workout_id"]
        assert state_path(program["program_id"]).exists()

    def test_second_sync_reuses_remote_workouts_and_schedules(self) -> None:
        client = FakeGarmin()
        self._sync(client)
        client.events.clear()
        self._sync(client)
        assert not any(event[0] == "upload" for event in client.events)
        assert not any(event[0] == "schedule" for event in client.events)
        assert not any(event[0] == "delete" for event in client.events)
        assert not any(event[0] == "unschedule" for event in client.events)

    def test_moving_workout_schedules_new_date_and_unschedules_old_date(self) -> None:
        client = FakeGarmin()
        program, compiled = self._sync(client)
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

    def test_sync_plan_reports_unschedule_when_workout_moves(self) -> None:
        client = FakeGarmin()
        self._sync(client)
        moved_program, moved_compiled = compiled_week(1)
        moved_compiled[0][0]["schedule_date"] = "2026-12-29"
        plan = plan_program_weeks(JsonStateRepository(), [(moved_program, moved_compiled)])
        assert ["reuse", "schedule", "unschedule", "reuse"] == [
            action.kind for action in plan.actions
        ]

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
        assert "content_hash" not in state["week-01/completed"]
        assert "description" not in state["week-01/completed"]
        assert "missed" == state["week-01/missed"]["status"]
        repeated = reconcile_program(
            client, JsonStateRepository(), "characterization-plan", today=date(2026, 7, 22)
        )
        assert [] == repeated.actions

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

    def test_prune_only_removes_future_active_workouts(self) -> None:
        records = {
            "week-08/past": {
                **self._old_record(),
                "workout_id": 80,
                "schedule_id": 180,
                "date": "2026-09-01",
                "name": "Past workout",
                "status": "scheduled",
            },
            "week-09/future": {
                **self._old_record(),
                "workout_id": 90,
                "schedule_id": 190,
                "date": "2026-11-01",
                "name": "Future workout",
                "status": "scheduled",
            },
            "week-10/completed": {
                **self._old_record(),
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
            **self._old_record(),
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
            **self._old_record(),
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
            **self._old_record(),
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
        old = self._old_record()
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
        old = self._old_record()
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
        old = self._old_record()
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
        old = self._old_record()
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

    def test_prune_plan_uses_union_of_all_selected_week_keys(self) -> None:
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {
                    "week-01/mixed": {"name": "Week 1 - Mixed"},
                    "week-02/long": {"name": "Week 2 - Long"},
                    "week-09/old": self._old_record(),
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
