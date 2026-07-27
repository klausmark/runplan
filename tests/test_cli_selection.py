from argparse import Namespace
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from runplan.cli import (
    main,
    parse_arguments,
    prepare_sync_selections,
    run_preview,
    run_multi_week_sync,
    week_selection,
)
from tests.helpers import compiled_week, program_data
import yaml


class CliSelectionTests(unittest.TestCase):
    def test_serve_programs_default_to_external_user_data_directory(self) -> None:
        with patch.dict("os.environ", {"XDG_DATA_HOME": "/srv/runplan-data"}, clear=True):
            arguments = parse_arguments(["serve"])
        self.assertEqual(Path("/srv/runplan-data/runplan/programs"), arguments.program_dir)

        with patch.dict("os.environ", {"RUNPLAN_PROGRAM_DIR": "/srv/plans"}, clear=True):
            arguments = parse_arguments(["serve"])
        self.assertEqual(Path("/srv/plans"), arguments.program_dir)

    def test_parser_defaults_to_overview_and_current_plus_one_week(self) -> None:
        arguments = parse_arguments(["sync", "plan.yaml", "--dry-run"])

        self.assertEqual("overview", arguments.output)
        self.assertEqual("ahead", week_selection(arguments).kind)
        self.assertEqual((1,), week_selection(arguments).weeks)

    def test_parser_rejects_multiple_selector_flags(self) -> None:
        with self.assertRaises(SystemExit):
            parse_arguments(
                ["sync", "plan.yaml", "--select-weeks", "1", "--weeks-ahead", "1"]
            )

    def test_default_and_explicit_selectors(self) -> None:
        self.assertEqual("ahead", week_selection(Namespace()).kind)
        self.assertEqual(
            (2, 4, 5),
            week_selection(Namespace(select_weeks="2,4-5")).weeks,
        )
        with self.assertRaisesRegex(ValueError, "non-negative"):
            week_selection(Namespace(weeks_ahead=-1))

    def test_relative_and_all_flags_map_to_domain_kinds(self) -> None:
        cases = (
            (Namespace(select_weeks="current"), "current"),
            (Namespace(select_weeks="next"), "next"),
            (Namespace(select_weeks="all"), "all"),
        )
        for arguments, expected in cases:
            with self.subTest(expected=expected):
                self.assertEqual(expected, week_selection(arguments).kind)

    def test_export_command_is_dispatched_from_native_cli(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            output = Path(directory, "plan.pdf")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            stdout = StringIO()

            with patch("runplan.cli.export_pdf") as export, redirect_stdout(stdout):
                result = main(
                    ["export", str(source), "--output", str(output)]
                )

        self.assertEqual(0, result)
        export.assert_called_once()
        self.assertIn("Exported 2 weeks", stdout.getvalue())

    def test_pdf_export_receives_only_selected_weeks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            output = Path(directory, "plan.pdf")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")

            with patch("runplan.cli.export_pdf") as export, redirect_stdout(StringIO()):
                result = main(
                    [
                        "export",
                        str(source),
                        "--format",
                        "pdf",
                        "--output",
                        str(output),
                        "--select-weeks",
                        "2",
                    ]
                )

        self.assertEqual(0, result)
        exported_program = export.call_args.args[0]
        self.assertEqual([2], [week.number for week in exported_program.weeks])

    def test_sync_preparation_selects_and_compiles_multiple_weeks(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            arguments = Namespace(
                yaml_file=source,
                select_weeks="1-2",
            )

            selections = prepare_sync_selections(arguments)

        self.assertEqual([1, 2], [program["week"] for program, _ in selections])
        self.assertEqual([2, 1], [len(compiled) for _, compiled in selections])

    def test_default_sync_selects_current_plan_week_and_one_week_ahead(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")

            first = prepare_sync_selections(
                Namespace(yaml_file=source, today=date(2026, 12, 28))
            )
            second = prepare_sync_selections(
                Namespace(yaml_file=source, today=date(2027, 1, 4))
            )

        self.assertEqual([1, 2], [program["week"] for program, _ in first])
        self.assertEqual([2], [program["week"] for program, _ in second])

    def test_all_and_overlapping_expressions_prepare_each_week_once(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            selections = []
            for arguments in (
                Namespace(yaml_file=source, select_weeks="all"),
                Namespace(yaml_file=source, select_weeks="1-2,2"),
            ):
                selections.append(prepare_sync_selections(arguments))

        for prepared in selections:
            self.assertEqual([1, 2], [program["week"] for program, _ in prepared])

    def test_preview_handler_only_formats_and_prints_prepared_data(self) -> None:
        selections = [compiled_week(1), compiled_week(2)]
        stdout = StringIO()

        with redirect_stdout(stdout):
            result = run_preview(Namespace(output="overview"), selections)

        self.assertEqual(0, result)
        self.assertIn("Week 1", stdout.getvalue())
        self.assertIn("Week 2", stdout.getvalue())

    def test_multi_week_handler_delegates_to_additive_use_case(self) -> None:
        selections = [compiled_week(1), compiled_week(2)]
        client = object()

        with (
            patch("runplan.cli.login_to_garmin", return_value=client),
            patch("runplan.cli.synchronize_program_weeks") as synchronize,
            redirect_stdout(StringIO()),
        ):
            result = run_multi_week_sync(selections)

        self.assertEqual(0, result)
        self.assertIs(client, synchronize.call_args.args[0])
        self.assertEqual(selections, synchronize.call_args.args[2])


if __name__ == "__main__":
    unittest.main()
