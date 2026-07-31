from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
import yaml

from runplan.application.sync import workout_content_hash
from runplan.state.yaml_repository import YamlStateRepository
from runplan.web import (
    ProgramStore,
    WebError,
    WebSyncService,
)
from tests.helpers import program_data
from tests.web_helpers import MemoryStateRepository


class TestProgramStore:
    @pytest.fixture(autouse=True)
    def program_store(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.path = self.root / "plan.yaml"
        self.path.write_text(
            yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        self.repository = MemoryStateRepository()
        self.store = ProgramStore(self.root, repository=self.repository)

    def test_lists_and_loads_valid_programs(self) -> None:
        programs = self.store.list()
        assert programs[0]["file"] == "plan.yaml"
        loaded = self.store.get("plan.yaml")
        assert loaded["program"]["name"] == "Characterization Plan"
        assert loaded["program"]["short_name"] == "CHAR"
        assert "2026-12-28" == loaded["weeks"][0]["start_date"]
        assert "2027-01-04" == loaded["weeks"][1]["start_date"]
        assert "id: mixed" in loaded["weeks"][0]["workouts"][0]["yaml"]

    def test_loads_workout_and_week_calendar_summaries(self) -> None:
        loaded = self.store.get("plan.yaml")
        week = loaded["weeks"][0]
        mixed, easy = week["workouts"]
        assert 2633.33 == pytest.approx(mixed["estimated_distance_meters"], rel=0.1)
        assert 1062 == pytest.approx(mixed["estimated_duration_seconds"])
        assert mixed["distance_is_approximate"]
        assert mixed["duration_is_approximate"]
        assert 5000 == easy["estimated_distance_meters"]
        assert not easy["distance_is_approximate"]
        assert easy["duration_is_approximate"]
        assert 7633.33 == pytest.approx(week["estimated_distance_meters"], rel=0.1)
        assert week["distance_is_approximate"]

    def test_completed_actual_and_missed_zero_replace_estimates_in_week_totals(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        raw["weeks"][0]["workouts"][0]["tracking"] = {
            "status": "completed",
            "actual": {
                "completed_at": "2026-12-28T12:00:00",
                "distance_meters": 3000.0,
                "duration_seconds": 1200.0,
            },
        }
        raw["weeks"][0]["workouts"][1]["tracking"] = {"status": "missed"}
        self.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        loaded = ProgramStore(self.root, repository=YamlStateRepository(self.path)).get("plan.yaml")
        week = loaded["weeks"][0]
        assert 3000.0 == week["effective_distance_meters"]
        assert 1200.0 == week["effective_duration_seconds"]
        assert week["workouts"][0]["totals_are_actual"]
        assert "tracking:" in week["workouts"][0]["yaml"]
        assert "distance_meters: 3000.0" in week["workouts"][0]["yaml"]
        edited_yaml = week["workouts"][0]["yaml"].replace(
            "distance_meters: 3000.0", "distance_meters: 3500.0"
        )
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "workout": {"week": 1, "workout_id": "mixed", "yaml": edited_yaml},
            },
            repository=YamlStateRepository(self.path),
        )
        assert 3500.0 == updated["weeks"][0]["effective_distance_meters"]

    def test_editor_can_remove_tracking_to_reset_a_workout_to_planned(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        raw["weeks"][0]["workouts"][0]["tracking"] = {
            "status": "missed",
            "scheduled_date": "2026-12-28",
        }
        self.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        repository = YamlStateRepository(self.path)
        loaded = ProgramStore(self.root, repository=repository).get("plan.yaml")
        editable = yaml.safe_load(loaded["weeks"][0]["workouts"][0]["yaml"])
        editable.pop("tracking")
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "workout": {
                    "week": 1,
                    "workout_id": "mixed",
                    "yaml": yaml.safe_dump(editable, sort_keys=False),
                },
            },
            repository=repository,
        )
        assert "planned" == updated["weeks"][0]["workouts"][0]["status"]

    def test_editor_includes_tracking_merged_from_legacy_state(self) -> None:
        state = self.repository.load("characterization-plan")
        state["workouts"]["week-01/mixed"] = {
            "week": 1,
            "date": "2026-12-28",
            "status": "completed",
            "workout_id": 10,
            "schedule_id": 20,
            "activity_id": 30,
            "completed_at": "2026-12-28T12:00:00",
            "actual_distance_meters": 3100.0,
            "actual_duration_seconds": 1250.0,
        }
        loaded = self.store.get("plan.yaml")
        editor_yaml = loaded["weeks"][0]["workouts"][0]["yaml"]
        assert "tracking:" in editor_yaml
        assert "activity_id: 30" in editor_yaml
        assert "distance_meters: 3100.0" in editor_yaml
        assert "duration_seconds: 1250.0" in editor_yaml

    def test_editor_rejects_invalid_tracking_without_changing_the_program(self) -> None:
        loaded = self.store.get("plan.yaml")
        base = yaml.safe_load(loaded["weeks"][0]["workouts"][0]["yaml"])
        invalid_values = (
            {"status": "scheduled", "synced_week": 0},
            {"status": "scheduled", "scheduled_date": "not-a-date"},
            {"status": "scheduled", "synced_content_hash": "short"},
            {"status": "scheduled", "garmin": {"workout_id": -1}},
            {"status": "completed", "actual": {"distance_meters": 10, "duration_seconds": 0}},
            {
                "status": "completed",
                "actual": {
                    "distance_meters": 10,
                    "duration_seconds": 20,
                    "completed_at": "not-a-time",
                },
            },
        )
        for tracking in invalid_values:
            replacement = {**base, "tracking": tracking}
            with pytest.raises(WebError):
                self.store.edit(
                    "plan.yaml",
                    {
                        "revision": loaded["revision"],
                        "workout": {
                            "week": 1,
                            "workout_id": "mixed",
                            "yaml": yaml.safe_dump(replacement, sort_keys=False),
                        },
                    },
                )
        assert loaded["revision"] == self.store.get("plan.yaml")["revision"]

    def test_user_default_pace_changes_time_based_estimates(self) -> None:
        normal = self.store.get("plan.yaml", fallback_pace_value="6:00 min/km")
        faster = self.store.get("plan.yaml", fallback_pace_value="5:00 min/km")
        normal_mixed = normal["weeks"][0]["workouts"][0]
        faster_mixed = faster["weeks"][0]["workouts"][0]
        assert faster_mixed["estimated_distance_meters"] > normal_mixed["estimated_distance_meters"]

    def test_loads_lifecycle_and_changed_since_sync_statuses(self) -> None:
        service = WebSyncService(
            self.store,
            repository=self.repository,
            client_factory=lambda: object(),
            today=lambda: date(2026, 12, 30),
        )
        selections = service._selections("plan.yaml")
        first_definition, first_workout = selections[0][1][0]
        state = self.repository.load("characterization-plan")
        state["workouts"] = {
            "week-01/mixed": {
                "status": "scheduled",
                "date": first_definition["schedule_date"],
                "schedule_id": 10,
                "content_hash": workout_content_hash(first_workout),
            },
            "week-01/easy": {"status": "completed", "date": "2026-12-31", "schedule_id": 11},
            "week-02/long": {
                "status": "scheduled",
                "date": "2027-01-03",
                "schedule_id": 12,
                "content_hash": "outdated",
            },
        }
        loaded = self.store.get("plan.yaml")
        statuses = {
            workout["id"]: workout["status"]
            for week in loaded["weeks"]
            for workout in week["workouts"]
        }
        movable = {
            workout["id"]: workout["can_move"]
            for week in loaded["weeks"]
            for workout in week["workouts"]
        }
        assert "scheduled" == statuses["mixed"]
        assert "completed" == statuses["easy"]
        assert "changed" == statuses["long"]
        assert movable == {"mixed": True, "easy": False, "long": True}

    def test_edits_metadata_and_rejects_stale_revision(self) -> None:
        loaded = self.store.get("plan.yaml")
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "program": {
                    "name": "My plan",
                    "short_name": "MYP",
                    "description": "Changed",
                    "start_week": "2027-W01",
                },
            },
        )
        assert updated["program"]["name"] == "My plan"
        assert updated["program"]["short_name"] == "MYP"
        with pytest.raises(WebError) as context:
            self.store.edit("plan.yaml", {"revision": loaded["revision"], "program": {}})
        assert context.value.status == 409

    def test_moves_to_empty_day_and_swaps_occupied_days(self) -> None:
        loaded = self.store.get("plan.yaml")
        moved = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "move": {"from_week": 1, "workout_id": "mixed", "to_week": 1, "to_day": 2},
            },
        )
        days = {item["id"]: item["day"] for item in moved["weeks"][0]["workouts"]}
        assert days == {"mixed": 2, "easy": 4}
        swapped = self.store.edit(
            "plan.yaml",
            {
                "revision": moved["revision"],
                "move": {"from_week": 1, "workout_id": "mixed", "to_week": 1, "to_day": 4},
            },
        )
        days = {item["id"]: item["day"] for item in swapped["weeks"][0]["workouts"]}
        assert days == {"mixed": 4, "easy": 2}

    def test_completed_workout_moves_require_direct_yaml_editing(self) -> None:
        state = self.repository.load("characterization-plan")
        state["workouts"]["week-01/easy"] = {
            "status": "completed",
            "date": "2026-12-31",
            "activity_id": 30,
            "actual_distance_meters": 5000.0,
            "actual_duration_seconds": 1800.0,
        }
        loaded = self.store.get("plan.yaml")

        with pytest.raises(WebError, match="Completed workouts"):
            self.store.edit(
                "plan.yaml",
                {
                    "revision": loaded["revision"],
                    "move": {
                        "from_week": 1,
                        "workout_id": "easy",
                        "to_week": 1,
                        "to_day": 5,
                    },
                },
            )
        with pytest.raises(WebError, match="completed workout"):
            self.store.edit(
                "plan.yaml",
                {
                    "revision": loaded["revision"],
                    "move": {
                        "from_week": 1,
                        "workout_id": "mixed",
                        "to_week": 1,
                        "to_day": 4,
                    },
                },
            )

        completed = loaded["weeks"][0]["workouts"][1]
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "workout": {
                    "week": 1,
                    "workout_id": "easy",
                    "yaml": completed["yaml"].replace("day: 4", "day: 5"),
                },
            },
        )
        assert updated["weeks"][0]["workouts"][1]["day"] == 5

    def test_moving_between_weeks_recalculates_week_distances(self) -> None:
        loaded = self.store.get("plan.yaml")
        moved = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "move": {"from_week": 1, "workout_id": "mixed", "to_week": 2, "to_day": 1},
            },
        )
        assert 5000 == moved["weeks"][0]["estimated_distance_meters"]
        assert 12633.33 == pytest.approx(moved["weeks"][1]["estimated_distance_meters"], rel=0.1)

    def test_replaces_workout_yaml_but_not_stable_id(self) -> None:
        loaded = self.store.get("plan.yaml")
        source = loaded["weeks"][0]["workouts"][0]["yaml"].replace(
            "name: Week 1 - Mixed", "name: Week 1 - Updated"
        )
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "workout": {"week": 1, "workout_id": "mixed", "yaml": source},
            },
        )
        assert updated["weeks"][0]["workouts"][0]["name"] == "Week 1 - Updated"
        invalid = source.replace("id: mixed", "id: changed")
        with pytest.raises(WebError):
            self.store.edit(
                "plan.yaml",
                {
                    "revision": updated["revision"],
                    "workout": {"week": 1, "workout_id": "mixed", "yaml": invalid},
                },
            )

    def test_adds_a_valid_workout_and_sorts_the_week_by_day(self) -> None:
        loaded = self.store.get("plan.yaml")
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "add_workout": {
                    "week": 1,
                    "yaml": (
                        "id: workout-1\n"
                        "day: 2\n"
                        "name: New workout\n"
                        "description: Keep this easy.\n"
                        "steps:\n"
                        "  - warmup: 5m\n"
                        "  - run: 20m\n"
                        "  - cooldown: 5m\n"
                    ),
                },
            },
        )

        assert [1, 2, 4] == [item["day"] for item in updated["weeks"][0]["workouts"]]
        assert "New workout" == updated["weeks"][0]["workouts"][1]["name"]

    @pytest.mark.parametrize(
        ("yaml_text", "message"),
        [
            ("id: mixed\nday: 2\nname: Duplicate ID\nsteps:\n  - run: 5m\n", "already used"),
            ("id: workout-1\nday: 1\nname: Duplicate day\nsteps:\n  - run: 5m\n", "already used"),
            ("program: [", "Invalid workout YAML"),
        ],
    )
    def test_rejects_invalid_workout_additions_without_changing_the_file(
        self, yaml_text: str, message: str
    ) -> None:
        loaded = self.store.get("plan.yaml")
        original = self.path.read_text(encoding="utf-8")

        with pytest.raises(WebError, match=message):
            self.store.edit(
                "plan.yaml",
                {
                    "revision": loaded["revision"],
                    "add_workout": {"week": 1, "yaml": yaml_text},
                },
            )

        assert original == self.path.read_text(encoding="utf-8")

    def test_deletes_a_workout_and_preserves_synced_tracking_for_cleanup(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        raw["weeks"][0]["workouts"][0]["tracking"] = {
            "status": "scheduled",
            "scheduled_date": "2026-12-28",
            "garmin": {"workout_id": 42, "schedule_id": 43},
        }
        self.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        loaded = self.store.get("plan.yaml")

        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "delete_workout": {"week": 1, "workout_id": "mixed"},
            },
        )

        assert ["easy"] == [item["id"] for item in updated["weeks"][0]["workouts"]]
        saved = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        orphan = saved["program"]["tracking"]["orphaned_workouts"]["week-01/mixed"]
        assert orphan["pending_deletion"] is True
        assert orphan["workout_id"] == 42
        assert orphan["schedule_id"] == 43

    def test_rejects_deleting_the_last_workout_in_a_week(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        raw["weeks"][1]["workouts"] = raw["weeks"][1]["workouts"][:1]
        self.path.write_text(yaml.safe_dump(raw, sort_keys=False), encoding="utf-8")
        loaded = self.store.get("plan.yaml")

        with pytest.raises(WebError, match="at least one workout"):
            self.store.edit(
                "plan.yaml",
                {
                    "revision": loaded["revision"],
                    "delete_workout": {
                        "week": 2,
                        "workout_id": loaded["weeks"][1]["workouts"][0]["id"],
                    },
                },
            )

    def test_editor_round_trips_yaml_formatting_and_comments(self) -> None:
        self.path.write_text(
            "# Program document comment\nprogram:\n  id: characterization-plan\n  name: Characterization Plan\n  short_name: CHAR\n  description: >-\n    Keep this folded program description\n    formatted as a block.\n  start_week: 2026-W53\nweeks:\n  - week: 1\n    focus: Mixed steps\n    workouts:\n      # Workout comment\n      - id: mixed\n        day: 1\n        name: Week 1 - Mixed\n        description: >-\n          Keep this workout description\n          formatted as a block.\n        steps:\n          - warmup: 5m\n          - run: 10m\n          - cooldown: 5m\n",
            encoding="utf-8",
        )
        loaded = self.store.get("plan.yaml")
        editor_yaml = loaded["weeks"][0]["workouts"][0]["yaml"]
        assert "description: >-\n  Keep this workout" in editor_yaml
        assert "steps:\n  - warmup: 5m" in editor_yaml
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "workout": {
                    "week": 1,
                    "workout_id": "mixed",
                    "yaml": editor_yaml.replace("name: Week 1 - Mixed", "name: Week 1 - Updated"),
                },
            },
        )
        saved = self.path.read_text(encoding="utf-8")
        assert "Week 1 - Updated" == updated["weeks"][0]["workouts"][0]["name"]
        assert "# Program document comment" in saved
        assert "# Workout comment" in saved
        assert "description: >-\n    Keep this folded program" in saved
        assert "steps:\n          - warmup: 5m" in saved

    def test_exports_yaml_markdown_and_pdf(self) -> None:
        for format_name, content_type in (
            ("yaml", "application/yaml"),
            ("markdown", "text/markdown"),
            ("pdf", "application/pdf"),
        ):
            content, actual_type, filename = self.store.export("plan.yaml", format_name)
            assert content
            assert actual_type.startswith(content_type)
            assert filename.startswith("plan.")

    def test_confines_program_files_to_root(self) -> None:
        with pytest.raises(WebError):
            self.store.get("../plan.yaml")

    def test_user_scoped_store_isolates_programs_and_allows_empty_users(self) -> None:
        scoped = ProgramStore(self.root, user_scoped=True)
        alice = scoped.for_user("alice")
        bob = scoped.for_user("bob")
        assert [] == alice.list()
        assert [] == bob.list()
        alice.upload("alice-plan.yaml", self.path.read_text(encoding="utf-8"))
        assert ["alice-plan.yaml"] == [item["file"] for item in alice.list()]
        assert [] == bob.list()

    def test_upload_validates_yaml_and_does_not_overwrite(self) -> None:
        empty_root = self.root / "uploads"
        empty_root.mkdir()
        uploads = ProgramStore(empty_root)
        uploaded = uploads.upload("new-plan.yaml", self.path.read_text(encoding="utf-8"))
        assert "Characterization Plan" == uploaded["program"]["name"]
        with pytest.raises(WebError) as conflict:
            uploads.upload("new-plan.yaml", self.path.read_text(encoding="utf-8"))
        assert conflict.value.status == 409
        with pytest.raises(WebError) as invalid:
            uploads.upload("broken.yaml", "program: [")
        assert invalid.value.status == 422
        assert not (empty_root / "broken.yaml").exists()
        with pytest.raises(WebError) as duplicate_id:
            uploads.upload("same-id.yaml", self.path.read_text(encoding="utf-8"))
        assert duplicate_id.value.status == 409
