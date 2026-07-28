from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from datetime import date
from unittest.mock import Mock, patch

import yaml

from helpers import program_data
from runplan.application.results import SyncResult
from runplan.application.sync import workout_content_hash
from runplan.state.json_repository import new_state
from runplan.state.yaml_repository import YamlStateRepository
from runplan.web import (
    ASSET_DIR,
    ProgramStore,
    RunplanUser,
    UserRegistry,
    WebError,
    WebSyncService,
    load_user_registry,
)


class MemoryStateRepository:
    def __init__(self) -> None:
        self.states = {}

    def load(self, program_id: str) -> dict:
        return self.states.setdefault(program_id, new_state(program_id))

    def save(self, program_id: str, state: dict) -> None:
        self.states[program_id] = state

    def delete(self, program_id: str) -> None:
        self.states.pop(program_id, None)


class WebAssetTests(unittest.TestCase):
    def test_theme_control_and_dark_palette_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="theme-button"', html)
        self.assertIn('localStorage.getItem("runplan-theme")', html)
        self.assertIn('localStorage.setItem("runplan-theme"', script)
        self.assertIn('[data-theme="dark"]', styles)
        self.assertNotIn('notify("Workout moved', script)
        self.assertNotIn('notify("Plan settings saved', script)

    def test_user_choice_is_local_and_active_program_is_server_backed(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="user-dialog"', html)
        self.assertIn('id="user-select"', html)
        self.assertIn('id="add-user-button"', html)
        self.assertIn('id="user-cancel"', html)
        self.assertIn('$("#add-user-button").addEventListener', script)
        self.assertIn('const USER_STORAGE_KEY = "runplan-user"', script)
        self.assertIn('`runplan-program:${userId}`', script)
        self.assertIn("state.user.activeProgram", script)
        self.assertIn("/active-program", script)
        self.assertIn('request("/api/users")', script)
        self.assertIn('$("#user-dialog").showModal()', script)
        self.assertIn('id="user-settings-dialog"', html)
        self.assertIn('id="user-settings-default-pace"', html)
        self.assertIn('id="user-settings-garmin-password"', html)
        self.assertIn("hasGarminPassword", script)

    def test_empty_program_state_and_yaml_upload_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="empty-programs"', html)
        self.assertIn('id="program-file-input"', html)
        self.assertIn("showEmptyPrograms()", script)
        self.assertIn('request("/api/programs", {', script)
        self.assertIn("filename: file.name", script)

    def test_recovery_review_ui_is_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")

        self.assertIn('id="recovery-button"', html)
        self.assertIn('id="recovery-dialog"', html)
        self.assertIn("/sync/recovery/preview", script)
        self.assertIn("recoveryPreview.confirmationToken", script)

    def test_yaml_editor_uses_horizontal_scrolling_instead_of_wrapping(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="workout-yaml" class="code-editor" wrap="off"', html)
        self.assertIn("overflow-x: auto", styles)
        self.assertIn("white-space: pre", styles)

    def test_calendar_undo_and_explicit_operation_states_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('id="app-status"', html)
        self.assertIn('id="undo-move"', html)
        self.assertIn("async function undoLastMove()", script)
        self.assertIn("state.undoMove = { fromWeek: toWeek", script)
        self.assertGreaterEqual(script.count("userId: state.user.id"), 5)
        self.assertIn('payload.workout ? "validation" : "saving"', script)
        self.assertIn('setAppStatus("garmin", "Syncing Garmin…")', script)
        self.assertIn('[data-status="failed"]', styles)
        self.assertNotIn('showError("Saved', script)

    def test_mobile_header_uses_a_compact_menu_and_bottom_sheet(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")

        self.assertIn('class="topbar-primary"', html)
        self.assertIn('id="mobile-menu-button"', html)
        self.assertIn('id="mobile-menu-backdrop"', html)
        self.assertEqual(1, html.count("data-theme-toggle"))
        self.assertIn("function setMobileMenu(open", script)
        self.assertIn('event.key === "Escape"', script)
        self.assertNotIn("updateHeaderForScroll", script)
        self.assertIn('.topbar.menu-open .topbar-actions-shell', styles)
        self.assertIn('body.mobile-menu-open .mobile-menu-backdrop', styles)
        self.assertIn("prefers-reduced-motion: reduce", styles)


class UserRegistryTests(unittest.TestCase):
    def test_missing_registry_can_create_and_reload_first_user(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "users.toml"
            registry = load_user_registry(config)

            self.assertEqual([], registry.list())
            created = registry.create("sample-runner", "Sample Runner")
            second = registry.create("runner-two", "Runner Two")
            reloaded = load_user_registry(config)

            self.assertEqual(
                {"id": "sample-runner", "name": "Sample Runner", "activeProgram": None},
                created,
            )
            self.assertEqual([created, second], reloaded.list())
            user = reloaded.get("sample-runner")
            self.assertEqual(
                config.parent / "users/sample-runner/credentials.toml",
                user.credentials_file,
            )
            self.assertFalse(user.credentials_file.exists())

    def test_create_validates_names_and_rejects_duplicates(self) -> None:
        with TemporaryDirectory() as directory:
            registry = load_user_registry(Path(directory) / "users.toml")
            with self.assertRaises(WebError):
                registry.create("Invalid User", "Valid Name")
            with self.assertRaises(WebError):
                registry.create("valid", "")
            registry.create("valid", "Valid Name")
            with self.assertRaises(WebError) as context:
                registry.create("valid", "Another Name")
            self.assertEqual(409, context.exception.status)

    def test_settings_store_credentials_without_returning_password(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "users.toml"
            registry = load_user_registry(config)
            registry.create("runner", "Runner One")

            result = registry.update_settings("runner", {
                "fullName": "Runner Updated",
                "defaultPace": "5:45 min/km",
                "garminEmail": "runner@example.com",
                "garminPassword": "secret-value",
            })
            preserved = registry.update_settings("runner", {
                "fullName": "Runner Updated",
                "defaultPace": "5:30 min/km",
                "garminEmail": "new@example.com",
                "garminPassword": "",
            })

            self.assertNotIn("garminPassword", result["settings"])
            self.assertTrue(result["settings"]["hasGarminPassword"])
            self.assertEqual("5:30 min/km", preserved["settings"]["defaultPace"])
            reloaded = load_user_registry(config)
            self.assertEqual("5:30 min/km", reloaded.get("runner").default_pace)
            credentials = reloaded.get("runner").credentials_file.read_text(encoding="utf-8")
            self.assertIn('email = "new@example.com"', credentials)
            self.assertIn('password = "secret-value"', credentials)

    def test_settings_require_valid_pace_and_initial_password(self) -> None:
        with TemporaryDirectory() as directory:
            registry = load_user_registry(Path(directory) / "users.toml")
            registry.create("runner", "Runner")
            base = {
                "fullName": "Runner",
                "garminEmail": "runner@example.com",
                "garminPassword": "",
            }
            with self.assertRaises(WebError):
                registry.update_settings("runner", {**base, "defaultPace": "fast"})
            with self.assertRaises(WebError) as context:
                registry.update_settings("runner", {**base, "defaultPace": "6:00 min/km"})
            self.assertIn("password", str(context.exception).lower())

    def test_loads_relative_profile_paths_without_exposing_them(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / "users.toml"
            config.write_text(
                """
[[users]]
id = "sample-runner"
name = "Sample Runner"
credentials_file = "secrets/sample-runner.toml"
token_store = "tokens/sample-runner"
state_dir = "state/sample-runner"
""".strip(),
                encoding="utf-8",
            )

            registry = load_user_registry(config)
            user = registry.get("sample-runner")

            self.assertEqual(
                [{"id": "sample-runner", "name": "Sample Runner", "activeProgram": None}],
                registry.list(),
            )
            self.assertEqual(root / "secrets/sample-runner.toml", user.credentials_file)
            self.assertEqual(root / "tokens/sample-runner", user.token_store)
            self.assertEqual(root / "state/sample-runner", user.state_directory)

    def test_rejects_unknown_user(self) -> None:
        registry = UserRegistry([RunplanUser(
            "known", "Known", Path("credentials"), Path("tokens"), Path("state")
        )])
        with self.assertRaises(WebError) as context:
            registry.get("unknown")
        self.assertEqual(400, context.exception.status)

    def test_active_program_round_trips_without_exposing_profile_paths(self) -> None:
        with TemporaryDirectory() as directory:
            config = Path(directory) / "users.toml"
            registry = load_user_registry(config)
            registry.create("runner", "Runner")

            updated = registry.set_active_program("runner", "marathon.yaml")
            reloaded = load_user_registry(config)

            self.assertEqual("marathon.yaml", updated.active_program)
            self.assertEqual("marathon.yaml", reloaded.get("runner").active_program)
            self.assertEqual("marathon.yaml", reloaded.list()[0]["activeProgram"])


class ProgramStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.path = self.root / "plan.yaml"
        self.path.write_text(
            yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self.repository = MemoryStateRepository()
        self.store = ProgramStore(self.root, repository=self.repository)

    def tearDown(self) -> None:
        self.directory.cleanup()

    def test_lists_and_loads_valid_programs(self) -> None:
        programs = self.store.list()
        self.assertEqual(programs[0]["file"], "plan.yaml")
        loaded = self.store.get("plan.yaml")
        self.assertEqual(loaded["program"]["name"], "Characterization Plan")
        self.assertEqual(loaded["program"]["short_name"], "CHAR")
        self.assertEqual("2026-12-28", loaded["weeks"][0]["start_date"])
        self.assertEqual("2027-01-04", loaded["weeks"][1]["start_date"])
        self.assertIn("id: mixed", loaded["weeks"][0]["workouts"][0]["yaml"])

    def test_loads_workout_and_week_calendar_summaries(self) -> None:
        loaded = self.store.get("plan.yaml")
        week = loaded["weeks"][0]
        mixed, easy = week["workouts"]

        self.assertAlmostEqual(2633.33, mixed["estimated_distance_meters"], places=1)
        self.assertAlmostEqual(1062, mixed["estimated_duration_seconds"])
        self.assertTrue(mixed["distance_is_approximate"])
        self.assertTrue(mixed["duration_is_approximate"])
        self.assertEqual(5000, easy["estimated_distance_meters"])
        self.assertFalse(easy["distance_is_approximate"])
        self.assertTrue(easy["duration_is_approximate"])
        self.assertAlmostEqual(7633.33, week["estimated_distance_meters"], places=1)
        self.assertTrue(week["distance_is_approximate"])

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

        self.assertEqual(3000.0, week["effective_distance_meters"])
        self.assertEqual(1200.0, week["effective_duration_seconds"])
        self.assertTrue(week["workouts"][0]["totals_are_actual"])
        self.assertIn("tracking:", week["workouts"][0]["yaml"])
        self.assertIn("distance_meters: 3000.0", week["workouts"][0]["yaml"])

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
        self.assertEqual(3500.0, updated["weeks"][0]["effective_distance_meters"])

    def test_editor_can_remove_tracking_to_reset_a_workout_to_planned(self) -> None:
        raw = yaml.safe_load(self.path.read_text(encoding="utf-8"))
        raw["weeks"][0]["workouts"][0]["tracking"] = {
            "status": "missed", "scheduled_date": "2026-12-28"
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

        self.assertEqual("planned", updated["weeks"][0]["workouts"][0]["status"])

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

        self.assertIn("tracking:", editor_yaml)
        self.assertIn("activity_id: 30", editor_yaml)
        self.assertIn("distance_meters: 3100.0", editor_yaml)
        self.assertIn("duration_seconds: 1250.0", editor_yaml)

    def test_editor_rejects_invalid_tracking_without_changing_the_program(self) -> None:
        loaded = self.store.get("plan.yaml")
        base = yaml.safe_load(loaded["weeks"][0]["workouts"][0]["yaml"])
        invalid_values = (
            {"status": "scheduled", "synced_week": 0},
            {"status": "scheduled", "scheduled_date": "not-a-date"},
            {"status": "scheduled", "synced_content_hash": "short"},
            {"status": "scheduled", "garmin": {"workout_id": -1}},
            {"status": "completed", "actual": {"distance_meters": 10, "duration_seconds": 0}},
            {"status": "completed", "actual": {"distance_meters": 10, "duration_seconds": 20, "completed_at": "not-a-time"}},
        )

        for tracking in invalid_values:
            replacement = {**base, "tracking": tracking}
            with self.subTest(tracking=tracking), self.assertRaises(WebError):
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
        self.assertEqual(loaded["revision"], self.store.get("plan.yaml")["revision"])

    def test_user_default_pace_changes_time_based_estimates(self) -> None:
        normal = self.store.get("plan.yaml", fallback_pace_value="6:00 min/km")
        faster = self.store.get("plan.yaml", fallback_pace_value="5:00 min/km")

        normal_mixed = normal["weeks"][0]["workouts"][0]
        faster_mixed = faster["weeks"][0]["workouts"][0]
        self.assertGreater(
            faster_mixed["estimated_distance_meters"],
            normal_mixed["estimated_distance_meters"],
        )

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
            "week-01/easy": {
                "status": "completed",
                "date": "2026-12-31",
                "schedule_id": 11,
            },
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

        self.assertEqual("scheduled", statuses["mixed"])
        self.assertEqual("completed", statuses["easy"])
        self.assertEqual("changed", statuses["long"])

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
        self.assertEqual(updated["program"]["name"], "My plan")
        self.assertEqual(updated["program"]["short_name"], "MYP")
        with self.assertRaises(WebError) as context:
            self.store.edit("plan.yaml", {"revision": loaded["revision"], "program": {}})
        self.assertEqual(context.exception.status, 409)

    def test_moves_to_empty_day_and_swaps_occupied_days(self) -> None:
        loaded = self.store.get("plan.yaml")
        moved = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "move": {
                    "from_week": 1,
                    "workout_id": "mixed",
                    "to_week": 1,
                    "to_day": 2,
                },
            },
        )
        days = {item["id"]: item["day"] for item in moved["weeks"][0]["workouts"]}
        self.assertEqual(days, {"mixed": 2, "easy": 4})
        swapped = self.store.edit(
            "plan.yaml",
            {
                "revision": moved["revision"],
                "move": {
                    "from_week": 1,
                    "workout_id": "mixed",
                    "to_week": 1,
                    "to_day": 4,
                },
            },
        )
        days = {item["id"]: item["day"] for item in swapped["weeks"][0]["workouts"]}
        self.assertEqual(days, {"mixed": 4, "easy": 2})

    def test_moving_between_weeks_recalculates_week_distances(self) -> None:
        loaded = self.store.get("plan.yaml")
        moved = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "move": {
                    "from_week": 1,
                    "workout_id": "mixed",
                    "to_week": 2,
                    "to_day": 1,
                },
            },
        )

        self.assertEqual(5000, moved["weeks"][0]["estimated_distance_meters"])
        self.assertAlmostEqual(
            12633.33, moved["weeks"][1]["estimated_distance_meters"], places=1
        )

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
        self.assertEqual(updated["weeks"][0]["workouts"][0]["name"], "Week 1 - Updated")
        invalid = source.replace("id: mixed", "id: changed")
        with self.assertRaises(WebError):
            self.store.edit(
                "plan.yaml",
                {
                    "revision": updated["revision"],
                    "workout": {"week": 1, "workout_id": "mixed", "yaml": invalid},
                },
            )

    def test_editor_round_trips_yaml_formatting_and_comments(self) -> None:
        self.path.write_text(
            """# Program document comment
program:
  id: characterization-plan
  name: Characterization Plan
  short_name: CHAR
  description: >-
    Keep this folded program description
    formatted as a block.
  start_week: 2026-W53
weeks:
  - week: 1
    focus: Mixed steps
    workouts:
      # Workout comment
      - id: mixed
        day: 1
        name: Week 1 - Mixed
        description: >-
          Keep this workout description
          formatted as a block.
        steps:
          - warmup: 5m
          - run: 10m
          - cooldown: 5m
""",
            encoding="utf-8",
        )
        loaded = self.store.get("plan.yaml")
        editor_yaml = loaded["weeks"][0]["workouts"][0]["yaml"]

        self.assertIn("description: >-\n  Keep this workout", editor_yaml)
        self.assertIn("steps:\n  - warmup: 5m", editor_yaml)
        updated = self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "workout": {
                    "week": 1,
                    "workout_id": "mixed",
                    "yaml": editor_yaml.replace(
                        "name: Week 1 - Mixed", "name: Week 1 - Updated"
                    ),
                },
            },
        )

        saved = self.path.read_text(encoding="utf-8")
        self.assertEqual("Week 1 - Updated", updated["weeks"][0]["workouts"][0]["name"])
        self.assertIn("# Program document comment", saved)
        self.assertIn("# Workout comment", saved)
        self.assertIn("description: >-\n    Keep this folded program", saved)
        self.assertIn("steps:\n          - warmup: 5m", saved)

    def test_exports_yaml_markdown_and_pdf(self) -> None:
        for format_name, content_type in (
            ("yaml", "application/yaml"),
            ("markdown", "text/markdown"),
            ("pdf", "application/pdf"),
        ):
            content, actual_type, filename = self.store.export("plan.yaml", format_name)
            self.assertTrue(content)
            self.assertTrue(actual_type.startswith(content_type))
            self.assertTrue(filename.startswith("plan."))

    def test_confines_program_files_to_root(self) -> None:
        with self.assertRaises(WebError):
            self.store.get("../plan.yaml")

    def test_user_scoped_store_isolates_programs_and_allows_empty_users(self) -> None:
        scoped = ProgramStore(self.root, user_scoped=True)

        alice = scoped.for_user("alice")
        bob = scoped.for_user("bob")

        self.assertEqual([], alice.list())
        self.assertEqual([], bob.list())
        alice.upload("alice-plan.yaml", self.path.read_text(encoding="utf-8"))
        self.assertEqual(["alice-plan.yaml"], [item["file"] for item in alice.list()])
        self.assertEqual([], bob.list())

    def test_upload_validates_yaml_and_does_not_overwrite(self) -> None:
        empty_root = self.root / "uploads"
        empty_root.mkdir()
        uploads = ProgramStore(empty_root)

        uploaded = uploads.upload("new-plan.yaml", self.path.read_text(encoding="utf-8"))
        self.assertEqual("Characterization Plan", uploaded["program"]["name"])

        with self.assertRaises(WebError) as conflict:
            uploads.upload("new-plan.yaml", self.path.read_text(encoding="utf-8"))
        self.assertEqual(409, conflict.exception.status)

        with self.assertRaises(WebError) as invalid:
            uploads.upload("broken.yaml", "program: [")
        self.assertEqual(422, invalid.exception.status)
        self.assertFalse((empty_root / "broken.yaml").exists())

        with self.assertRaises(WebError) as duplicate_id:
            uploads.upload("same-id.yaml", self.path.read_text(encoding="utf-8"))
        self.assertEqual(409, duplicate_id.exception.status)


class WebSyncServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.directory = TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.path = self.root / "plan.yaml"
        self.path.write_text(
            yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        self.repository = MemoryStateRepository()
        self.store = ProgramStore(self.root, repository=self.repository)
        self.client_factory = Mock(return_value=object())
        self.service = WebSyncService(
            self.store,
            repository=self.repository,
            client_factory=self.client_factory,
            today=lambda: date(2026, 12, 30),
        )

    def test_preview_uses_default_weeks_without_contacting_garmin(self) -> None:
        preview = self.service.preview("plan.yaml")

        self.assertEqual([1, 2], preview["plan"]["weeks"])
        self.assertEqual(
            ["missed", "create", "schedule", "create", "schedule"],
            [action["kind"] for action in preview["plan"]["actions"]],
        )
        self.assertEqual(64, len(preview["confirmationToken"]))
        self.client_factory.assert_not_called()

    def test_confirmed_sync_returns_structured_results(self) -> None:
        preview = self.service.preview("plan.yaml")
        result = SyncResult("characterization-plan", 1)
        result.add("schedule", "Mixed", workout_id=42, date="2026-12-28")

        with patch("runplan.web.synchronize_program_weeks", return_value=[result]):
            response = self.service.execute(
                "plan.yaml",
                {"confirmationToken": preview["confirmationToken"]},
            )

        self.client_factory.assert_called_once_with()
        self.assertEqual([1, 2], response["weeks"])
        self.assertEqual("schedule", response["results"][0]["actions"][0]["kind"])

    def test_changed_plan_rejects_stale_confirmation(self) -> None:
        preview = self.service.preview("plan.yaml")
        loaded = self.store.get("plan.yaml")
        self.store.edit(
            "plan.yaml",
            {
                "revision": loaded["revision"],
                "program": {"name": "Changed plan"},
            },
        )

        with self.assertRaises(WebError) as context:
            self.service.execute(
                "plan.yaml",
                {"confirmationToken": preview["confirmationToken"]},
            )

        self.assertEqual(409, context.exception.status)
        self.client_factory.assert_not_called()

    def test_garmin_error_is_actionable(self) -> None:
        preview = self.service.preview("plan.yaml")
        self.client_factory.side_effect = RuntimeError("login unavailable")

        with self.assertRaises(WebError) as context:
            self.service.execute(
                "plan.yaml",
                {"confirmationToken": preview["confirmationToken"]},
            )

        self.assertEqual(502, context.exception.status)
        self.assertIn("login unavailable", str(context.exception))

    def test_user_profiles_have_isolated_state_and_confirmation_tokens(self) -> None:
        alice = RunplanUser(
            "alice", "Alice", self.root / "alice.toml", self.root / "alice-tokens",
            self.root / "alice-state",
        )
        bob = RunplanUser(
            "bob", "Bob", self.root / "bob.toml", self.root / "bob-tokens",
            self.root / "bob-state",
        )
        service = WebSyncService(
            self.store,
            users=UserRegistry([alice, bob]),
            client_factory=self.client_factory,
            today=lambda: date(2026, 12, 30),
        )
        alice_state = service.repository_for("alice").load("characterization-plan")
        alice_state["workouts"]["week-01/mixed"] = {
            "status": "scheduled", "date": "2026-12-28", "schedule_id": 42
        }
        service.repository_for("alice").save("characterization-plan", alice_state)

        alice_preview = service.preview("plan.yaml", "alice")
        bob_preview = service.preview("plan.yaml", "bob")

        self.assertNotEqual(
            alice_preview["confirmationToken"], bob_preview["confirmationToken"]
        )
        self.assertEqual("alice", alice_preview["userId"])
        self.assertEqual("bob", bob_preview["userId"])
        self.assertNotEqual(
            [action["kind"] for action in alice_preview["plan"]["actions"]],
            [action["kind"] for action in bob_preview["plan"]["actions"]],
        )

    def test_recovery_requires_fresh_preview_before_atomic_rebuild(self) -> None:
        discovery = {
            "ownerId": "local-default",
            "programId": "characterization-plan",
            "recovered": [{"key": "week-01/mixed"}],
            "issues": [],
            "legacyCandidates": [],
            "records": {
                "week-01/mixed": {
                    "week": 1,
                    "workout_id": 42,
                    "date": "2026-12-28",
                    "status": "scheduled",
                }
            },
        }
        with patch("runplan.web.discover_sync_state", return_value=discovery):
            preview = self.service.recovery_preview("plan.yaml")
            response = self.service.recovery_execute(
                "plan.yaml",
                {"confirmationToken": preview["confirmationToken"]},
            )

        self.assertEqual(1, response["recoveredCount"])
        stored = self.repository.load("characterization-plan")
        self.assertEqual(42, stored["workouts"]["week-01/mixed"]["workout_id"])
        self.assertNotIn("records", response["discovery"])


if __name__ == "__main__":
    unittest.main()
