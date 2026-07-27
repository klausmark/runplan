from __future__ import annotations

import copy
import json
import re
import tempfile
import unittest
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

from runplan import (
    WorkoutDefinitionError,
    build_workout,
    compile_steps,
    load_definition,
    load_program,
    parse_duration,
    run_sync,
)
from tests.helpers import normalized_program, program_data


class ProgramParsingCharacterizationTests(unittest.TestCase):
    def test_start_week_uses_valid_iso_calendar_week(self) -> None:
        for value in ("2026-01-03", "2026-W00", "2026-W54", 202631):
            with self.subTest(value=value):
                raw = program_data()
                raw["program"]["start_week"] = value
                with self.assertRaisesRegex(WorkoutDefinitionError, "start_week"):
                    load_program(raw, selected_week=1)

    def test_legacy_start_date_is_not_accepted(self) -> None:
        raw = program_data()
        raw["program"]["start_date"] = raw["program"].pop("start_week")

        with self.assertRaisesRegex(WorkoutDefinitionError, "start_week"):
            load_program(raw, selected_week=1)

    def test_normalizes_program_and_dates_across_year_boundary(self) -> None:
        program = normalized_program(selected_week=2)

        self.assertEqual("characterization-plan", program["program_id"])
        self.assertEqual("2026-12-28", program["start_date"])
        self.assertEqual("2026-W53", program["start_week"])
        self.assertEqual(2, program["week"])
        self.assertEqual("2027-01-10", program["workouts"][0]["schedule_date"])
        self.assertEqual([1, 2], [week["number"] for week in program["weeks"]])

    def test_rejects_non_contiguous_weeks_with_location(self) -> None:
        raw = program_data()
        raw["weeks"][1]["week"] = 3

        with self.assertRaisesRegex(
            WorkoutDefinitionError,
            r"weeks: week numbers must be contiguous from 1; found \[1, 3\]",
        ):
            load_program(raw, selected_week=1)

    def test_rejects_duplicate_ids_days_and_unsorted_days(self) -> None:
        mutations = (
            ("duplicate id", lambda raw: raw["weeks"][0]["workouts"][1].update(id="mixed"), "ID 'mixed'"),
            ("duplicate day", lambda raw: raw["weeks"][0]["workouts"][1].update(day=1), "day 1 is already"),
            ("unsorted day", lambda raw: raw["weeks"][0]["workouts"][0].update(day=5), "must be sorted by day"),
        )
        for label, mutate, message in mutations:
            with self.subTest(label=label):
                raw = program_data()
                mutate(raw)
                with self.assertRaisesRegex(WorkoutDefinitionError, message):
                    load_program(raw, selected_week=1)

    def test_allows_workout_names_to_repeat_across_weeks(self) -> None:
        raw = program_data()
        raw["weeks"][1]["workouts"][0]["name"] = raw["weeks"][0]["workouts"][0]["name"]

        load_program(raw, selected_week=1)

    def test_short_name_is_required_and_compact(self) -> None:
        for value in (None, "A", "TOO-LONG-123", "not valid", "HCA_26"):
            with self.subTest(value=value):
                raw = program_data()
                raw["program"]["short_name"] = value
                with self.assertRaisesRegex(WorkoutDefinitionError, "short_name"):
                    load_program(raw, selected_week=1)

    def test_rejects_unknown_selected_week(self) -> None:
        with self.assertRaisesRegex(
            WorkoutDefinitionError, "Program does not contain week 9"
        ):
            load_program(program_data(), selected_week=9)

    def test_duration_formats_remain_backward_compatible(self) -> None:
        cases = {
            30: 30,
            "30s": 30,
            "2m": 120,
            "1m30s": 90,
            "1.5m": 90,
            "00:30": 30,
            "02:30": 150,
            "01:02:03": 3723,
        }
        for value, expected in cases.items():
            with self.subTest(value=value):
                self.assertEqual(expected, parse_duration(value, "trin[1]"))

    def test_nested_step_error_keeps_precise_location(self) -> None:
        steps = [
            {
                "repeat": {
                    "count": 2,
                    "steps": [{"run": {"distance": "400"}}],
                }
            }
        ]

        with self.assertRaisesRegex(
            WorkoutDefinitionError,
            r"steps\[1\]\.steps\[1\]\.distance: invalid distance",
        ):
            compile_steps(steps)

    def test_danish_yaml_field_names_are_rejected(self) -> None:
        raw = program_data()
        raw["uger"] = raw.pop("weeks")

        with self.assertRaisesRegex(WorkoutDefinitionError, "Field 'weeks'"):
            load_program(raw, selected_week=1)

    def test_every_bundled_program_loads_and_builds_every_week(self) -> None:
        project = Path(__file__).resolve().parents[1]
        fixtures = project / "tests" / "fixtures" / "programs"
        paths = sorted(fixtures.glob("*.yaml")) + sorted(
            (project / "docs" / "examples").glob("*.yaml")
        )
        self.assertGreaterEqual(len(paths), 4)
        for path in paths:
            with self.subTest(path=path.name):
                first = load_definition(path)
                self.assertTrue(first["program_short_name"])
                for week in first["weeks"]:
                    selected = load_definition(path, selected_week=week["number"])
                    for workout in selected["workouts"]:
                        self.assertNotRegex(workout["name"], r"^Week\s+\d+\s+-")
                        build_workout(workout)

    def test_fictional_marathon_calendar_preserves_key_dates(self) -> None:
        project = Path(__file__).resolve().parents[1]
        source = project / "tests" / "fixtures" / "programs" / "avery-example-marathon.yaml"
        first = load_definition(source, selected_week=1)
        last = load_definition(source, selected_week=3)

        self.assertEqual("2027-W10", first["start_week"])
        self.assertEqual("2027-03-08", first["workouts"][0]["schedule_date"])
        self.assertEqual(1, first["workouts"][0]["day"])
        self.assertEqual("2027-03-27", last["workouts"][-1]["schedule_date"])
        self.assertEqual(6, last["workouts"][-1]["day"])

    def test_maintained_yaml_and_documentation_use_english_schema_keys(self) -> None:
        project = Path(__file__).resolve().parents[1]
        fixtures = project / "tests" / "fixtures" / "programs"
        maintained = [
            *fixtures.glob("*.yaml"),
            *(project / "docs" / "examples").glob("*.yaml"),
            project / "README.md",
            project / "docs" / "program-prompt.md",
            fixtures / "avery-example-marathon.md",
        ]
        danish_key = re.compile(
            r"(?:^\s*|[{,]\s*)(?:navn|beskrivelse|startdato|uger|uge|fokus|dag|"
            r"trin|opvarmning|løb|gå|afslutning|gentag|antal|tid|tempo):",
            re.MULTILINE,
        )

        for path in maintained:
            with self.subTest(path=path.name):
                self.assertIsNone(danish_key.search(path.read_text(encoding="utf-8")))

    def test_maintained_user_facing_content_has_no_danish_characters(self) -> None:
        project = Path(__file__).resolve().parents[1]
        fixtures = project / "tests" / "fixtures" / "programs"
        maintained = [
            project / "README.md",
            project / "PLAN.md",
            fixtures / "morgan-example-5k.yaml",
            fixtures / "riley-example-5k.yaml",
            fixtures / "avery-example-marathon.yaml",
            fixtures / "avery-example-marathon.md",
            *sorted((project / "docs").rglob("*.md")),
            *sorted((project / "docs" / "examples").glob("*.yaml")),
        ]

        for path in maintained:
            with self.subTest(path=path.relative_to(project)):
                self.assertNotRegex(path.read_text(encoding="utf-8"), r"[æøåÆØÅ]")


class GarminPayloadCharacterizationTests(unittest.TestCase):
    def test_mixed_workout_payload_is_stable(self) -> None:
        workout = build_workout(normalized_program()["workouts"][0]).to_dict()
        steps = workout["workoutSegments"][0]["workoutSteps"]

        self.assertEqual("Week 1 - Mixed", workout["workoutName"])
        self.assertEqual(480, workout["estimatedDurationInSecs"])
        self.assertEqual("distance", steps[0]["endCondition"]["conditionTypeKey"])
        self.assertEqual(1000, steps[0]["endConditionValue"])
        repeat = steps[1]
        self.assertEqual(2, repeat["numberOfIterations"])
        interval, recovery = repeat["workoutSteps"]
        self.assertEqual("pace.zone", interval["targetType"]["workoutTargetTypeKey"])
        self.assertAlmostEqual(1000 / 285, interval["targetValueOne"])
        self.assertAlmostEqual(1000 / 270, interval["targetValueTwo"])
        self.assertEqual("time", recovery["endCondition"]["conditionTypeKey"])
        self.assertEqual(90, recovery["endConditionValue"])


class CliPreviewCharacterizationTests(unittest.TestCase):
    def _write_program(self, directory: str) -> Path:
        path = Path(directory) / "program.yaml"
        path.write_text(
            yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        return path

    def test_json_dry_run_is_machine_readable_and_does_not_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_program(directory)
            args = Namespace(
                yaml_file=path,
                select_weeks="1",
                dry_run=True,
                output="json",
                delete_all=False,
                yes=False,
            )
            stdout = StringIO()
            with patch("runplan.cli_sync.login_to_garmin") as login, redirect_stdout(stdout):
                result = run_sync(args)

        self.assertEqual(0, result)
        login.assert_not_called()
        output = json.loads(stdout.getvalue())
        self.assertEqual("characterization-plan", output["programId"])
        self.assertEqual(1, output["weeks"][0]["week"])
        workouts = output["weeks"][0]["workouts"]
        self.assertEqual(["mixed", "easy"], [item["id"] for item in workouts])
        self.assertEqual("2026-12-28", workouts[0]["date"])

    def test_overview_dry_run_is_additive_and_does_not_mutate_state(self) -> None:
        state = {
            "program_id": "characterization-plan",
            "workouts": {
                "week-09/old": {
                    "name": "Old workout",
                    "date": "2026-11-01",
                }
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_program(directory)
            args = Namespace(
                yaml_file=path,
                select_weeks="1",
                dry_run=True,
                output="overview",
                delete_all=False,
                yes=False,
            )
            stdout = StringIO()
            with patch(
                "runplan.cli_sync.load_state", return_value=copy.deepcopy(state)
            ), redirect_stdout(stdout):
                result = run_sync(args)

        self.assertEqual(0, result)
        text = stdout.getvalue()
        self.assertIn("CHAR - W1 - Mixed - ~2.6k", text)
        self.assertIn("Monday · Mixed", text)
        self.assertNotIn("2026-12-28 · Week 1 - Mixed", text)
        self.assertIn("17 min 42 sec + 2.6 km", text)
        self.assertNotIn("Old workout (2026-11-01)", text)

    def test_invalid_week_returns_definition_error_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_program(directory)
            args = Namespace(
                yaml_file=path,
                select_weeks="0",
                dry_run=True,
                output="overview",
                delete_all=False,
                yes=False,
            )
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = run_sync(args)

        self.assertEqual(2, result)
        self.assertIn("week numbers must be positive", stderr.getvalue())

    def test_default_sync_reports_when_today_is_outside_the_program(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_program(directory)
            args = Namespace(
                yaml_file=path,
                today=date(2026, 7, 26),
                dry_run=True,
                output="overview",
                delete_all=False,
                yes=False,
            )
            stderr = StringIO()

            with redirect_stderr(stderr):
                result = run_sync(args)

        self.assertEqual(2, result)
        self.assertIn("Cannot select sync weeks", stderr.getvalue())
        self.assertIn("outside the program", stderr.getvalue())

    def test_multi_week_dry_run_defaults_to_overview_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_program(directory)
            args = Namespace(
                yaml_file=path,
                select_weeks="all",
                dry_run=True,
                output="overview",
                delete_all=False,
                yes=False,
            )
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = run_sync(args)

        self.assertEqual(0, result)
        self.assertFalse(stdout.getvalue().lstrip().startswith("{"))
        self.assertIn("Week 1", stdout.getvalue())
        self.assertIn("Week 2", stdout.getvalue())

    def test_prune_without_yes_previews_and_can_be_cancelled_before_login(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = self._write_program(directory)
            args = Namespace(
                yaml_file=path,
                select_weeks="1",
                dry_run=False,
                output="overview",
                delete_all=False,
                prune=True,
                yes=False,
            )
            stdout = StringIO()
            with (
                patch("runplan.cli_sync.login_to_garmin") as login,
                patch("builtins.input", return_value="n"),
                redirect_stdout(stdout),
            ):
                result = run_sync(args)

        self.assertEqual(0, result)
        login.assert_not_called()
        self.assertIn("Sync changes:", stdout.getvalue())
        self.assertIn("Sync cancelled", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
