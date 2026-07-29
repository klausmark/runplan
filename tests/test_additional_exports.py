import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import yaml

from runplan.application.export import build_program_export
from runplan.cli import main
from runplan.domain.selectors import WeekSelection
from runplan.exporters.html import export_html, format_program_html
from runplan.exporters.markdown import export_markdown, format_program_markdown
from runplan.parsing.yaml_loader import load_program_model
from tests.helpers import program_data


class AdditionalExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self.program = build_program_export(load_program_model(program_data()), WeekSelection.all())

    def test_html_is_standalone_and_escapes_user_content(self) -> None:
        raw = program_data()
        raw["program"]["name"] = "Plan <unsafe> & complete"
        raw["program"]["description"] = "Use <script> & recover"
        export = build_program_export(load_program_model(raw), WeekSelection.all())

        document = format_program_html(export)

        self.assertTrue(document.startswith("<!doctype html>"))
        self.assertIn('<meta charset="utf-8">', document)
        self.assertIn("Plan &lt;unsafe&gt; &amp; complete", document)
        self.assertIn("Use &lt;script&gt; &amp; recover", document)
        self.assertNotIn("<script>", document)

    def test_markdown_is_deterministic_commonmark_and_escapes_content(self) -> None:
        raw = program_data()
        raw["program"]["name"] = "Plan *fast* <safe>"
        export = build_program_export(load_program_model(raw), WeekSelection.all())

        first = format_program_markdown(export)
        second = format_program_markdown(export)

        self.assertEqual(first, second)
        self.assertTrue(first.startswith("# Plan \\*fast\\* \\<safe\\>\n"))
        self.assertEqual(2, first.count("\n---\n"))
        self.assertIn("```text\nWarmup: 1 km", first)

    def test_file_exports_refuse_overwrite_without_force(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for name, exporter in (("plan.html", export_html), ("plan.md", export_markdown)):
                with self.subTest(name=name):
                    output = Path(directory, name)
                    exporter(self.program, output, False)
                    with self.assertRaises(FileExistsError):
                        exporter(self.program, output, False)
                    exporter(self.program, output, True)
                    self.assertGreater(output.stat().st_size, 0)

    def test_cli_writes_only_selected_week_for_html_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            for export_format, suffix, week_one, week_two in (
                ("html", ".html", 'id="week-1"', 'id="week-2"'),
                ("markdown", ".md", "## Week 1 ", "## Week 2 "),
            ):
                with self.subTest(export_format=export_format):
                    output = Path(directory, f"plan{suffix}")
                    stdout = StringIO()
                    with redirect_stdout(stdout):
                        result = main(
                            [
                                "export",
                                str(source),
                                "--format",
                                export_format,
                                "--output",
                                str(output),
                                "--select-weeks",
                                "2",
                            ]
                        )
                    document = output.read_text(encoding="utf-8")
                    self.assertEqual(0, result)
                    self.assertNotIn(week_one, document)
                    self.assertIn(week_two, document)
                    self.assertIn("Exported 1 weeks", stdout.getvalue())

    def test_cli_requires_output_for_html_and_markdown(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory, "plan.yaml")
            source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
            for export_format in ("html", "markdown"):
                with self.subTest(export_format=export_format):
                    stderr = StringIO()
                    with redirect_stderr(stderr):
                        result = main(["export", str(source), "--format", export_format])
                    self.assertEqual(2, result)
                    self.assertIn("requires --output", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
