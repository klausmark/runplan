import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

from runplan.application.export import build_program_export
from runplan.cli import main
from runplan.domain.selectors import WeekSelection
from runplan.parsing.yaml_loader import load_program_model
from runplan.presentation.program_text import SECTION_DIVIDER, format_program_text
from tests.helpers import program_data


class ProgramExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = load_program_model(program_data())

    def test_common_model_selects_requested_weeks(self) -> None:
        export = build_program_export(self.program, WeekSelection.explicit("2"))

        self.assertEqual("Characterization Plan", export.name)
        self.assertEqual(2, export.total_weeks)
        self.assertEqual([2], [week.number for week in export.weeks])
        self.assertEqual("Long", export.weeks[0].workouts[0].name)
        self.assertEqual("Week 2 - Long", export.weeks[0].workouts[0].source_name)
        self.assertEqual(1, export.selected_week_count)
        self.assertEqual(1, export.summary.workout_count)
        self.assertEqual(60 * 60, export.summary.estimated_duration_seconds)
        self.assertEqual(10_000, export.summary.estimated_distance_meters)
        self.assertEqual(export.summary, export.weeks[0].summary)

    def test_summaries_estimate_missing_quantities_and_exclude_timed_pauses(self) -> None:
        export = build_program_export(self.program, WeekSelection.explicit("1"))

        self.assertEqual(2, export.summary.workout_count)
        self.assertEqual(47 * 60 + 42, export.summary.estimated_duration_seconds)
        self.assertAlmostEqual(7_633.333, export.summary.estimated_distance_meters, places=3)
        self.assertEqual(export.summary, export.weeks[0].summary)

    def test_text_renderer_includes_details_without_sync_language(self) -> None:
        export = build_program_export(self.program, WeekSelection.explicit("1"))

        text = format_program_text(export)

        self.assertIn("Characterization Plan", text)
        self.assertIn("Start week: 2026-W53", text)
        self.assertIn("Program weeks: 2", text)
        self.assertIn("Selected weeks: 1", text)
        self.assertIn("Total workouts: 2", text)
        self.assertIn("Estimated total duration: 47 min 42 sec", text)
        self.assertIn("Estimated total distance: 7.6 km", text)
        self.assertIn("Week 1 (2026-12-28 to 2027-01-03)", text)
        self.assertIn("Workouts this week: 2", text)
        self.assertIn("Estimated duration this week: 47 min 42 sec", text)
        self.assertIn("Estimated distance this week: 7.6 km", text)
        self.assertLess(text.index("Workouts this week: 2"), text.index("Monday · Mixed"))
        self.assertEqual(1, text.count(SECTION_DIVIDER))
        self.assertIn("Monday · Mixed · 8 min + 1.8 km", text)
        self.assertIn("Repeat 2 times:", text)
        self.assertIn("Run: 400 m @ 4:30-4:45 min/km", text)
        self.assertNotIn("Sync changes", text)
        self.assertNotIn("Dry run", text)

    def test_text_export_matches_snapshot(self) -> None:
        export = build_program_export(self.program, WeekSelection.explicit("1"))
        snapshot = Path(__file__).parent / "snapshots" / "program_export_week_1.txt"

        self.assertEqual(snapshot.read_text(encoding="utf-8").rstrip(), format_program_text(export))

    def test_environment_configures_fallback_pace_for_cli_export(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            stdout = StringIO()
            with (
                patch.dict("os.environ", {"RUNPLAN_DEFAULT_PACE": "5:00 min/km"}),
                redirect_stdout(stdout),
            ):
                result = main(
                    [
                        "export",
                        str(source),
                        "--format",
                        "text",
                        "--select-weeks",
                        "2",
                    ]
                )

        self.assertEqual(0, result)
        self.assertIn("Estimated total duration: 50 min", stdout.getvalue())

    def test_cli_rejects_invalid_environment_fallback_pace(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            stderr = StringIO()
            with (
                patch.dict("os.environ", {"RUNPLAN_DEFAULT_PACE": "fast"}),
                redirect_stderr(stderr),
            ):
                result = main(["export", str(source), "--format", "text"])

        self.assertEqual(2, result)
        self.assertIn("RUNPLAN_DEFAULT_PACE", stderr.getvalue())

    def test_text_cli_writes_selected_weeks_to_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            stdout = StringIO()
            with redirect_stdout(stdout):
                result = main(
                    [
                        "export",
                        str(source),
                        "--format",
                        "text",
                        "--select-weeks",
                        "2",
                    ]
                )

        self.assertEqual(0, result)
        self.assertIn("Week 2 (", stdout.getvalue())
        self.assertNotIn("Week 1 (", stdout.getvalue())

    def test_text_cli_rejects_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = main(
                    [
                        "export",
                        str(source),
                        "--format",
                        "text",
                        "--output",
                        str(Path(directory, "plan.txt")),
                    ]
                )

        self.assertEqual(2, result)
        self.assertIn("text export writes to stdout", stderr.getvalue())

    def test_pdf_cli_requires_output_path(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            stderr = StringIO()
            with redirect_stderr(stderr):
                result = main(["export", str(source), "--format", "pdf"])

        self.assertEqual(2, result)
        self.assertIn("PDF export requires --output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
