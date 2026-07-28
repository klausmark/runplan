from __future__ import annotations

import copy
import json
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

from runplan import (
    build_workout,
    delete_all_managed,
    load_state,
    save_state,
    state_path,
    sync_program_week,
)
from runplan.application.sync import (
    discover_sync_state,
    plan_program_weeks,
    reconcile_program,
    rebuild_sync_state,
    synchronize_program_week,
    synchronize_program_weeks,
)
from runplan.domain.ownership import parse_ownership
from runplan.state.json_repository import CURRENT_STATE_VERSION, JsonStateRepository
from runplan.integrations.garmin.client import (
    get_all_workouts,
    scheduled_items_for_dates,
)
from tests.helpers import compiled_week


class FakeGarmin:
    def __init__(
        self,
        workouts: list[dict] | None = None,
        schedules: list[dict] | None = None,
        fail_upload_number: int | None = None,
    ) -> None:
        self.workouts = copy.deepcopy(workouts or [])
        self.schedules = copy.deepcopy(schedules or [])
        self.fail_upload_number = fail_upload_number
        self.upload_count = 0
        self.events: list[tuple] = []
        self.next_workout_id = 1000
        self.next_schedule_id = 2000

    def get_workouts(self, start: int, limit: int) -> list[dict]:
        self.events.append(("get_workouts", start, limit))
        return copy.deepcopy(self.workouts[start : start + limit])

    def get_scheduled_workouts(self, year: int, month: int) -> dict:
        self.events.append(("get_scheduled_workouts", year, month))
        prefix = f"{year:04d}-{month:02d}"
        return {
            "calendarItems": copy.deepcopy(
                [item for item in self.schedules if item["date"].startswith(prefix)]
            )
        }

    def get_activity(self, activity_id: str) -> dict:
        self.events.append(("get_activity", activity_id))
        return {
            "activityId": int(activity_id),
            "summaryDTO": {
                "distance": 10_000.0,
                "duration": 3_600.0,
                "startTimeLocal": "2026-07-20T18:30:00",
            },
            "metadataDTO": {},
        }

    def upload_running_workout(self, workout) -> dict:
        self.upload_count += 1
        self.events.append(("upload", workout.workoutName))
        if self.fail_upload_number == self.upload_count:
            raise RuntimeError("simulated upload failure")
        payload = workout.to_dict()
        result = {
            "workoutId": self.next_workout_id,
            "workoutName": payload["workoutName"],
            "description": payload.get("description"),
        }
        self.next_workout_id += 1
        self.workouts.append(result)
        return copy.deepcopy(result)

    def schedule_workout(self, workout_id: int, scheduled_date: str) -> dict:
        self.events.append(("schedule", workout_id, scheduled_date))
        result = {
            "itemType": "workout",
            "workoutId": workout_id,
            "date": scheduled_date,
            "workoutScheduleId": self.next_schedule_id,
            "id": self.next_schedule_id,
        }
        self.next_schedule_id += 1
        self.schedules.append(result)
        return copy.deepcopy(result)

    def unschedule_workout(self, schedule_id: int) -> None:
        self.events.append(("unschedule", schedule_id))
        self.schedules = [
            item
            for item in self.schedules
            if item.get("id") != schedule_id
            and item.get("workoutScheduleId") != schedule_id
        ]

    def delete_workout(self, workout_id: int) -> None:
        self.events.append(("delete", workout_id))
        self.workouts = [
            item for item in self.workouts if item.get("workoutId") != workout_id
        ]


class SyncCharacterizationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary_directory.cleanup)
        self.environment = patch.dict(
            os.environ,
            {"GARMIN_STATE_DIR": self.temporary_directory.name},
        )
        self.environment.start()
        self.addCleanup(self.environment.stop)

    def _sync(self, client: FakeGarmin, week: int = 1):
        program, compiled = compiled_week(week)
        with redirect_stdout(StringIO()):
            sync_program_week(client, program, compiled)
        return program, compiled

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

        self.assertEqual(2, len([event for event in client.events if event[0] == "upload"]))
        self.assertEqual(2, len([event for event in client.events if event[0] == "schedule"]))
        state = load_state(program["program_id"])
        self.assertEqual(1, state["active_week"])
        self.assertEqual(
            {"week-01/mixed", "week-01/easy"}, set(state["workouts"])
        )
        self.assertEqual(1000, state["workouts"]["week-01/mixed"]["workout_id"])
        self.assertTrue(state_path(program["program_id"]).exists())

    def test_second_sync_reuses_remote_workouts_and_schedules(self) -> None:
        client = FakeGarmin()
        self._sync(client)
        client.events.clear()

        self._sync(client)

        self.assertFalse(any(event[0] == "upload" for event in client.events))
        self.assertFalse(any(event[0] == "schedule" for event in client.events))
        self.assertFalse(any(event[0] == "delete" for event in client.events))
        self.assertFalse(any(event[0] == "unschedule" for event in client.events))

    def test_moving_workout_schedules_new_date_and_unschedules_old_date(self) -> None:
        client = FakeGarmin()
        program, compiled = self._sync(client)
        old_date = compiled[0][0]["schedule_date"]
        old_schedule_id = load_state(program["program_id"])["workouts"][
            "week-01/mixed"
        ]["schedule_id"]
        client.events.clear()

        moved_program, moved_compiled = compiled_week(1)
        moved_compiled[0][0]["schedule_date"] = "2026-12-29"
        result = synchronize_program_week(
            client,
            JsonStateRepository(),
            moved_program,
            moved_compiled,
        )

        self.assertIn(("schedule", 1002, "2026-12-29"), client.events)
        self.assertIn(("unschedule", old_schedule_id), client.events)
        self.assertLess(
            client.events.index(("schedule", 1002, "2026-12-29")),
            client.events.index(("unschedule", old_schedule_id)),
        )
        self.assertIn(("upload", moved_compiled[0][0]["name"]), client.events)
        self.assertIn(("delete", 1000), client.events)
        self.assertNotIn(
            (1000, old_date),
            [(item["workoutId"], item["date"]) for item in client.schedules],
        )
        record = load_state(program["program_id"])["workouts"]["week-01/mixed"]
        self.assertEqual("2026-12-29", record["date"])
        self.assertEqual(
            ["create", "schedule", "reuse", "already_scheduled", "unschedule", "delete"],
            [action.kind for action in result.actions],
        )

    def test_sync_plan_reports_unschedule_when_workout_moves(self) -> None:
        client = FakeGarmin()
        self._sync(client)
        moved_program, moved_compiled = compiled_week(1)
        moved_compiled[0][0]["schedule_date"] = "2026-12-29"

        plan = plan_program_weeks(
            JsonStateRepository(), [(moved_program, moved_compiled)]
        )

        self.assertEqual(
            ["reuse", "schedule", "unschedule", "reuse"],
            [action.kind for action in plan.actions],
        )

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
            client,
            JsonStateRepository(),
            "characterization-plan",
            today=date(2026, 7, 22),
        )

        self.assertEqual(["completed", "missed"], [a.kind for a in result.actions])
        state = load_state("characterization-plan")["workouts"]
        self.assertEqual("completed", state["week-01/completed"]["status"])
        self.assertEqual(900, state["week-01/completed"]["activity_id"])
        self.assertNotIn("content_hash", state["week-01/completed"])
        self.assertNotIn("description", state["week-01/completed"])
        self.assertEqual("missed", state["week-01/missed"]["status"])

        repeated = reconcile_program(
            client,
            JsonStateRepository(),
            "characterization-plan",
            today=date(2026, 7, 22),
        )
        self.assertEqual([], repeated.actions)

    def test_selected_workout_is_completed_today_from_garmin_after_state_loss(self) -> None:
        client = FakeGarmin()
        selection = compiled_week(1)
        synchronize_program_weeks(
            client,
            JsonStateRepository(),
            [selection],
            owner_id="klaus",
            today=date(2026, 12, 28),
        )
        mixed_schedule = next(
            item for item in client.schedules if item["date"] == "2026-12-28"
        )
        mixed_schedule["associatedActivityId"] = 901
        mixed_schedule["associatedActivityDateTime"] = "2026-12-28T10:00:00"
        JsonStateRepository().delete("characterization-plan")

        results = synchronize_program_weeks(
            client,
            JsonStateRepository(),
            [selection],
            owner_id="klaus",
            today=date(2026, 12, 28),
        )

        completed = [action for result in results for action in result.actions if action.kind == "completed"]
        self.assertEqual([901], [action.activity_id for action in completed])
        record = load_state("characterization-plan")["workouts"]["week-01/mixed"]
        self.assertEqual("completed", record["status"])
        self.assertEqual(901, record["activity_id"])

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
            "characterization-plan",
            {"program_id": "characterization-plan", "workouts": records},
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
            client,
            JsonStateRepository(),
            [compiled_week(1)],
            prune=True,
            today=date(2026, 10, 1),
        )

        state = load_state("characterization-plan")["workouts"]
        self.assertIn("week-08/past", state)
        self.assertEqual("missed", state["week-08/past"]["status"])
        self.assertNotIn("week-09/future", state)
        self.assertIn("week-10/completed", state)
        self.assertIn(("delete", 90), client.events)
        self.assertNotIn(("delete", 80), client.events)
        self.assertNotIn(("delete", 100), client.events)

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
                {
                    "workoutId": 99,
                    "workoutName": "Old workout",
                    "description": "Owned description",
                }
            ]
        )

        program, compiled = compiled_week(1)
        synchronize_program_weeks(
            client, JsonStateRepository(), [(program, compiled)], prune=True
        )

        event_names = [event[0] for event in client.events]
        last_schedule = max(
            index for index, name in enumerate(event_names) if name == "schedule"
        )
        self.assertGreater(event_names.index("unschedule"), last_schedule)
        self.assertGreater(event_names.index("delete"), last_schedule)
        state = load_state("characterization-plan")
        self.assertNotIn("week-09/old", state["workouts"])

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
                {
                    "workoutId": 99,
                    "workoutName": "Old workout",
                    "description": "Owned description",
                }
            ],
            fail_upload_number=2,
        )
        program, compiled = compiled_week(1)

        with self.assertRaisesRegex(RuntimeError, "simulated upload failure"), redirect_stdout(
            StringIO()
        ):
            sync_program_week(client, program, compiled)

        self.assertFalse(any(event[0] == "delete" for event in client.events))
        self.assertFalse(any(event[0] == "unschedule" for event in client.events))
        state = load_state("characterization-plan")
        self.assertIn("week-09/old", state["workouts"])
        self.assertIn("week-01/mixed", state["workouts"])

    def test_cleanup_stops_if_remote_workout_no_longer_matches_state(self) -> None:
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

        with self.assertRaisesRegex(RuntimeError, "does not belong to the program"), redirect_stdout(
            StringIO()
        ):
            synchronize_program_weeks(
                client, JsonStateRepository(), [(program, compiled)], prune=True
            )

        self.assertNotIn(("delete", 99), client.events)
        self.assertNotIn(("unschedule", 199), client.events)
        self.assertIn("week-09/old", load_state("characterization-plan")["workouts"])

    def test_delete_all_unschedules_then_deletes_only_owned_records(self) -> None:
        old = self._old_record()
        save_state(
            "characterization-plan",
            {
                "program_id": "characterization-plan",
                "workouts": {"week-09/old": old},
            },
        )
        client = FakeGarmin(
            workouts=[
                {
                    "workoutId": 99,
                    "workoutName": "Old workout",
                    "description": "Owned description",
                },
                {
                    "workoutId": 77,
                    "workoutName": "Unmanaged",
                    "description": "Untouched",
                },
            ]
        )
        program, compiled = compiled_week(1)

        with redirect_stdout(StringIO()):
            deleted = delete_all_managed(client, program, compiled)

        self.assertEqual(1, deleted)
        self.assertLess(client.events.index(("unschedule", 199)), client.events.index(("delete", 99)))
        self.assertIn(77, [item["workoutId"] for item in client.workouts])
        self.assertFalse(state_path("characterization-plan").exists())

    def test_changed_step_content_replaces_same_name_and_description(self) -> None:
        client = FakeGarmin()
        program, compiled = compiled_week(1)
        existing_definition, existing_workout = compiled[0]
        existing_payload = existing_workout.to_dict()
        client.workouts.append(
            {
                "workoutId": 50,
                **existing_payload,
            }
        )
        changed_program, changed_compiled = compiled_week(1)
        changed_compiled[0][0]["steps"][0] = {"warmup": {"distance": "2km"}}
        changed_definition = changed_compiled[0][0]
        changed_compiled[0] = (changed_definition, build_workout(changed_definition))

        with redirect_stdout(StringIO()):
            sync_program_week(client, changed_program, changed_compiled)

        self.assertIn(("upload", existing_definition["name"]), client.events)
        self.assertIn(("delete", 50), client.events)

    def test_application_sync_returns_actions_without_writing_to_stdout(self) -> None:
        client = FakeGarmin()
        program, compiled = compiled_week(1)

        output = StringIO()
        with redirect_stdout(output):
            result = synchronize_program_week(
                client, JsonStateRepository(), program, compiled
            )

        self.assertEqual("", output.getvalue())
        self.assertEqual(program["program_id"], result.program_id)
        self.assertEqual(
            ["create", "schedule", "create", "schedule"],
            [action.kind for action in result.actions],
        )
        self.assertIn(
            "content_hash",
            load_state(program["program_id"])["workouts"]["week-01/mixed"],
        )

    def test_multi_week_sync_is_additive_by_default(self) -> None:
        client = FakeGarmin()
        week_one = compiled_week(1)
        week_two = compiled_week(2)

        results = synchronize_program_weeks(
            client,
            JsonStateRepository(),
            [week_one, week_two],
        )

        self.assertEqual([1, 2], [result.week for result in results])
        self.assertFalse(any(event[0] == "delete" for event in client.events))
        self.assertFalse(any(event[0] == "unschedule" for event in client.events))
        self.assertEqual(
            {"week-01/mixed", "week-01/easy", "week-02/long"},
            set(load_state("characterization-plan")["workouts"]),
        )

    def test_skipping_then_syncing_a_later_week_preserves_existing_state(self) -> None:
        client = FakeGarmin()

        synchronize_program_weeks(
            client, JsonStateRepository(), [compiled_week(1)]
        )
        client.events.clear()
        synchronize_program_weeks(
            client, JsonStateRepository(), [compiled_week(2)]
        )

        self.assertFalse(any(event[0] in ("delete", "unschedule") for event in client.events))
        self.assertEqual(
            {"week-01/mixed", "week-01/easy", "week-02/long"},
            set(load_state("characterization-plan")["workouts"]),
        )

    def test_empty_and_overlapping_batches_are_rejected_before_garmin_io(self) -> None:
        client = FakeGarmin()
        week_one = compiled_week(1)

        for selections, message in (
            ([], "at least one selected week"),
            ([week_one, week_one], "overlapping weeks"),
            ([(week_one[0], [])], "no workouts"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                synchronize_program_weeks(client, JsonStateRepository(), selections)

        self.assertEqual([], client.events)
        self.assertFalse(state_path("characterization-plan").exists())

    def test_batch_cannot_mix_program_ids(self) -> None:
        client = FakeGarmin()
        other_program, other_compiled = copy.deepcopy(compiled_week(2))
        other_program["program_id"] = "other-plan"

        with self.assertRaisesRegex(ValueError, "one program"):
            synchronize_program_weeks(
                client,
                JsonStateRepository(),
                [compiled_week(1), (other_program, other_compiled)],
            )

        self.assertEqual([], client.events)

    def test_remote_ownership_conflict_stops_before_mutation(self) -> None:
        client = FakeGarmin()
        synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(1)])
        client.workouts[0]["description"] = "Conflicting remote workout"
        client.events.clear()

        with self.assertRaisesRegex(RuntimeError, "does not belong to the program"):
            synchronize_program_weeks(client, JsonStateRepository(), [compiled_week(1)])

        self.assertFalse(any(event[0] in ("upload", "schedule", "delete", "unschedule") for event in client.events))
        self.assertEqual(
            {"week-01/mixed", "week-01/easy"},
            set(load_state("characterization-plan")["workouts"]),
        )

    def test_rebuild_recovers_state_from_owned_garmin_metadata(self) -> None:
        client = FakeGarmin()
        selection = compiled_week(1)
        synchronize_program_weeks(
            client, JsonStateRepository(), [selection], owner_id="test-owner"
        )
        metadata = parse_ownership(client.workouts[0]["description"])
        self.assertIsNotNone(metadata)
        self.assertEqual("test-owner", metadata.owner_id)
        self.assertTrue(client.workouts[0]["description"].split("\n\n", 1)[0])

        empty = JsonStateRepository()
        empty.delete("characterization-plan")
        event_count = len(client.events)
        discovery = discover_sync_state(
            client, [selection], owner_id="test-owner", today=date(2026, 12, 1)
        )
        rebuilt = rebuild_sync_state(empty, discovery)

        self.assertEqual(2, len(discovery["recovered"]))
        self.assertEqual(
            {"week-01/mixed", "week-01/easy"}, set(rebuilt["workouts"])
        )
        self.assertEqual(1000, rebuilt["workouts"]["week-01/mixed"]["workout_id"])
        self.assertEqual("scheduled", rebuilt["workouts"]["week-01/mixed"]["status"])
        self.assertFalse(any(
            event[0] in ("upload", "schedule", "delete", "unschedule")
            for event in client.events[event_count:]
        ))

        second = discover_sync_state(
            client, [selection], owner_id="test-owner", today=date(2026, 12, 1)
        )
        self.assertEqual(discovery["records"], second["records"])

    def test_rebuild_rejects_wrong_owner_duplicates_and_unmarked_legacy(self) -> None:
        client = FakeGarmin()
        selection = compiled_week(1)
        synchronize_program_weeks(
            client, JsonStateRepository(), [selection], owner_id="alice"
        )
        duplicate = copy.deepcopy(client.workouts[0])
        duplicate["workoutId"] = 9000
        client.workouts.append(duplicate)
        client.workouts.append({
            "workoutId": 9001,
            "workoutName": selection[1][1][0]["name"],
            "description": "Old Runplan description",
        })

        wrong_owner = discover_sync_state(client, [selection], owner_id="bob")
        self.assertEqual([], wrong_owner["recovered"])
        self.assertTrue(any(item["code"] == "wrong_owner" for item in wrong_owner["issues"]))

        alice = discover_sync_state(client, [selection], owner_id="alice")
        self.assertTrue(any(item["code"] == "duplicate_identity" for item in alice["issues"]))
        self.assertEqual(1, len(alice["legacyCandidates"]))
        self.assertNotIn("week-01/mixed", alice["records"])

    def test_rebuild_uses_only_supported_lifecycle_evidence(self) -> None:
        client = FakeGarmin()
        selection = compiled_week(1)
        synchronize_program_weeks(
            client, JsonStateRepository(), [selection], owner_id="test-owner"
        )
        client.schedules[0]["associatedActivityId"] = 700
        client.schedules[0]["associatedActivityDateTime"] = "2026-12-28T08:00:00"

        discovery = discover_sync_state(
            client, [selection], owner_id="test-owner", today=date(2027, 1, 5)
        )

        completed = discovery["records"]["week-01/mixed"]
        missed = discovery["records"]["week-01/easy"]
        self.assertEqual("completed", completed["status"])
        self.assertEqual(700, completed["activity_id"])
        self.assertEqual("missed", missed["status"])

    def test_rebuild_reports_corrupt_and_unsupported_metadata(self) -> None:
        program, compiled = compiled_week(1)
        client = FakeGarmin(workouts=[
            {"workoutId": 1, "workoutName": compiled[0][0]["name"], "description": "[runplan:v1:%%%]"},
            {"workoutId": 2, "workoutName": compiled[1][0]["name"], "description": "[runplan:v2:e30]"},
        ])

        discovery = discover_sync_state(client, [(program, compiled)], owner_id="test-owner")

        self.assertEqual([], discovery["recovered"])
        self.assertEqual(
            {"invalid", "unsupported_version", "not_found"},
            {item["code"] for item in discovery["issues"]},
        )

    def test_retry_after_partial_failure_reuses_completed_work(self) -> None:
        client = FakeGarmin(fail_upload_number=2)
        selection = compiled_week(1)

        with self.assertRaisesRegex(RuntimeError, "simulated upload failure"):
            synchronize_program_weeks(client, JsonStateRepository(), [selection])

        self.assertEqual(
            {"week-01/mixed"},
            set(load_state("characterization-plan")["workouts"]),
        )
        client.fail_upload_number = None
        client.events.clear()

        results = synchronize_program_weeks(
            client, JsonStateRepository(), [compiled_week(1)]
        )

        self.assertEqual(["reuse", "already_scheduled", "create", "schedule"],
                         [action.kind for action in results[0].actions])
        self.assertEqual(
            [("upload", "Week 1 - Easy")],
            [event for event in client.events if event[0] == "upload"],
        )
        self.assertEqual(
            {"week-01/mixed", "week-01/easy"},
            set(load_state("characterization-plan")["workouts"]),
        )

    def test_sync_plan_is_structured_and_read_only(self) -> None:
        selections = [compiled_week(1), compiled_week(2)]
        repository = JsonStateRepository()

        plan = plan_program_weeks(repository, selections)

        self.assertEqual((1, 2), plan.weeks)
        self.assertEqual(
            ["create", "schedule", "create", "schedule", "create", "schedule"],
            [action.kind for action in plan.actions],
        )
        self.assertFalse(state_path("characterization-plan").exists())
        self.assertEqual("characterization-plan", plan.to_dict()["programId"])

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
            client,
            JsonStateRepository(),
            [selection],
            today=date(2026, 12, 29),
        )

        self.assertEqual("completed", plan.actions[0].kind)
        self.assertEqual("completed", results[0].actions[0].kind)
        uploads = [event for event in client.events if event[0] == "upload"]
        self.assertEqual([("upload", "Week 1 - Easy")], uploads)

    def test_untracked_past_workouts_become_missed_instead_of_being_scheduled(self) -> None:
        selection = compiled_week(1)
        plan = plan_program_weeks(
            JsonStateRepository(), [selection], today=date(2027, 1, 1)
        )
        client = FakeGarmin()

        results = synchronize_program_weeks(
            client,
            JsonStateRepository(),
            [selection],
            today=date(2027, 1, 1),
        )

        self.assertEqual(["missed", "missed"], [a.kind for a in plan.actions])
        self.assertEqual(
            ["missed", "missed"], [a.kind for a in results[0].actions]
        )
        self.assertFalse(any(event[0] == "upload" for event in client.events))
        self.assertFalse(any(event[0] == "schedule" for event in client.events))
        state = load_state("characterization-plan")["workouts"]
        self.assertEqual("missed", state["week-01/mixed"]["status"])
        self.assertEqual("missed", state["week-01/easy"]["status"])

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
        self.assertEqual(["Old workout"], deleted)
        self.assertNotIn("Week 1 - Mixed", deleted)
        self.assertNotIn("Week 2 - Long", deleted)


class StateCharacterizationTests(unittest.TestCase):
    def test_state_round_trip_is_utf8_and_atomic_temp_file_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GARMIN_STATE_DIR": directory}
        ):
            state = {
                "program_id": "unicode-plan",
                "workouts": {"week-01/a": {"name": "Løb med overskud"}},
            }
            save_state("unicode-plan", state)

            loaded = load_state("unicode-plan")
            self.assertEqual(CURRENT_STATE_VERSION, loaded.pop("schema_version"))
            self.assertEqual("planned", loaded["workouts"]["week-01/a"]["status"])
            loaded["workouts"]["week-01/a"].pop("status")
            self.assertEqual(state, loaded)
            self.assertIn("ø", state_path("unicode-plan").read_text(encoding="utf-8"))
            self.assertFalse(Path(directory, "unicode-plan.tmp").exists())

    def test_invalid_state_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GARMIN_STATE_DIR": directory}
        ):
            path = Path(directory, "expected.json")
            path.write_text(
                json.dumps({"program_id": "other", "workouts": {}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(SystemExit, "invalid format"):
                load_state("expected")

    def test_legacy_state_without_version_is_migrated_in_memory(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GARMIN_STATE_DIR": directory}
        ):
            path = Path(directory, "legacy.json")
            path.write_text(
                json.dumps({"program_id": "legacy", "workouts": {}}),
                encoding="utf-8",
            )

            state = load_state("legacy")

            self.assertEqual(CURRENT_STATE_VERSION, state["schema_version"])
            self.assertNotIn("schema_version", json.loads(path.read_text()))

    def test_version_one_state_gains_lifecycle_status(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GARMIN_STATE_DIR": directory}
        ):
            path = Path(directory, "legacy.json")
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "program_id": "legacy",
                        "workouts": {
                            "scheduled": {"schedule_id": 10},
                            "planned": {},
                        },
                    }
                ),
                encoding="utf-8",
            )

            state = load_state("legacy")

        self.assertEqual(CURRENT_STATE_VERSION, state["schema_version"])
        self.assertEqual("scheduled", state["workouts"]["scheduled"]["status"])
        self.assertEqual("planned", state["workouts"]["planned"]["status"])

    def test_state_from_newer_schema_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GARMIN_STATE_DIR": directory}
        ):
            path = Path(directory, "future.json")
            path.write_text(
                json.dumps(
                    {
                        "schema_version": CURRENT_STATE_VERSION + 1,
                        "program_id": "future",
                        "workouts": {},
                    }
                ),
                encoding="utf-8",
            )

            with self.assertRaisesRegex(SystemExit, "newer than supported"):
                load_state("future")

    def test_non_object_state_is_rejected_as_invalid_format(self) -> None:
        with tempfile.TemporaryDirectory() as directory, patch.dict(
            os.environ, {"GARMIN_STATE_DIR": directory}
        ):
            Path(directory, "list-state.json").write_text("[]", encoding="utf-8")

            with self.assertRaisesRegex(SystemExit, "invalid format"):
                load_state("list-state")


class GarminBoundaryCharacterizationTests(unittest.TestCase):
    def test_workout_pagination_uses_pages_of_one_hundred(self) -> None:
        workouts = [
            {"workoutId": value, "workoutName": f"Workout {value}"}
            for value in range(205)
        ]
        client = FakeGarmin(workouts=workouts)

        result = get_all_workouts(client)

        self.assertEqual(workouts, result)
        self.assertEqual(
            [
                ("get_workouts", 0, 100),
                ("get_workouts", 100, 100),
                ("get_workouts", 200, 100),
            ],
            [event for event in client.events if event[0] == "get_workouts"],
        )

    def test_scheduled_lookup_queries_each_month_and_filters_non_workouts(self) -> None:
        client = FakeGarmin(
            schedules=[
                {
                    "itemType": "workout",
                    "workoutId": 1,
                    "date": "2026-12-31",
                    "id": 11,
                },
                {
                    "itemType": "workout",
                    "workoutId": 2,
                    "date": "2027-01-01",
                    "id": 12,
                },
                {
                    "itemType": "race",
                    "workoutId": 3,
                    "date": "2027-01-02",
                    "id": 13,
                },
            ]
        )

        result = scheduled_items_for_dates(
            client, {"2026-12-31", "2027-01-01"}
        )

        self.assertEqual([1, 2], [item["workoutId"] for item in result])
        self.assertEqual(
            [
                ("get_scheduled_workouts", 2026, 12),
                ("get_scheduled_workouts", 2027, 1),
            ],
            [
                event
                for event in client.events
                if event[0] == "get_scheduled_workouts"
            ],
        )

    def test_scheduled_lookup_normalizes_garmin_calendar_shape(self) -> None:
        class CalendarClient:
            def get_scheduled_workouts(self, year: int, month: int) -> dict:
                return {
                    "calendarItems": [
                        {
                            "itemType": "workout",
                            "calendarDate": "2026-07-20",
                            "workoutScheduleId": 20,
                            "workout": {"workoutId": 10},
                            "associatedActivityId": 900,
                        }
                    ]
                }

            def get_activity(self, activity_id: str) -> dict:
                return {
                    "activityId": int(activity_id),
                    "summaryDTO": {"distance": 5000, "duration": 1800},
                }

        result = scheduled_items_for_dates(CalendarClient(), {"2026-07-20"})

        self.assertEqual("2026-07-20", result[0]["date"])
        self.assertEqual(10, result[0]["workoutId"])
        self.assertEqual(20, result[0]["workoutScheduleId"])
        self.assertEqual(900, result[0]["associatedActivityId"])

    def test_calendar_activity_is_joined_to_workout_through_activity_summary(self) -> None:
        class CalendarClient:
            def get_scheduled_workouts(self, year: int, month: int) -> dict:
                return {"calendarItems": [
                    {"itemType": "workout", "date": "2026-07-28", "id": 20, "workoutId": 10},
                    {"itemType": "activity", "date": "2026-07-28", "id": 900, "startTimestampLocal": "2026-07-28T17:35:02.0"},
                    {"itemType": "activity", "date": "2026-07-28", "id": 901},
                ]}

            def get_activity(self, activity_id: str) -> dict:
                if activity_id == "901":
                    return {"activityId": 901, "metadataDTO": {}, "summaryDTO": {}}
                return {
                    "activityId": 900,
                    "metadataDTO": {"associatedWorkoutId": 10},
                    "summaryDTO": {
                        "distance": 11158.74,
                        "duration": 4057.619,
                        "startTimeLocal": "2026-07-28T17:35:02.0",
                    },
                }

        result = scheduled_items_for_dates(CalendarClient(), {"2026-07-28"})

        self.assertEqual(900, result[0]["associatedActivityId"])
        self.assertEqual(11158.74, result[0]["actualDistanceMeters"])
        self.assertEqual(4057.619, result[0]["actualDurationSeconds"])

    def test_overlapping_month_results_deduplicate_the_same_calendar_activity(self) -> None:
        class CalendarClient:
            def __init__(self) -> None:
                self.activity_calls: list[str] = []

            def get_scheduled_workouts(self, year: int, month: int) -> dict:
                return {"calendarItems": [
                    {"itemType": "workout", "date": "2026-07-27", "id": 20, "workoutId": 10},
                    {"itemType": "activity", "date": "2026-07-27", "id": 900},
                ]}

            def get_activity(self, activity_id: str) -> dict:
                self.activity_calls.append(activity_id)
                return {
                    "activityId": 900,
                    "metadataDTO": {"associatedWorkoutId": 10},
                    "summaryDTO": {"distance": 7593.39, "duration": 2489.549},
                }

        client = CalendarClient()
        result = scheduled_items_for_dates(client, {"2026-07-27", "2026-08-02"})

        self.assertEqual(["900"], client.activity_calls)
        self.assertEqual(900, result[0]["associatedActivityId"])

    def test_distinct_activities_for_the_same_workout_and_date_remain_a_conflict(self) -> None:
        class CalendarClient:
            def get_scheduled_workouts(self, year: int, month: int) -> dict:
                return {"calendarItems": [
                    {"itemType": "workout", "date": "2026-07-27", "id": 20, "workoutId": 10},
                    {"itemType": "activity", "date": "2026-07-27", "id": 900},
                    {"itemType": "activity", "date": "2026-07-27", "id": 901},
                ]}

            def get_activity(self, activity_id: str) -> dict:
                return {
                    "activityId": int(activity_id),
                    "metadataDTO": {"associatedWorkoutId": 10},
                    "summaryDTO": {"distance": 5000, "duration": 1800},
                }

        with self.assertRaisesRegex(
            RuntimeError, "workoutId=10 on 2026-07-27"
        ):
            scheduled_items_for_dates(CalendarClient(), {"2026-07-27"})


if __name__ == "__main__":
    unittest.main()
