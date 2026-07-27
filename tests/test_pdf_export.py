import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from pypdf import PdfReader

from runplan import (
    WeekSelection,
    build_program_export,
    export_pdf,
    load_definition_model,
)
from runplan.parsing.yaml_loader import load_program_model
from runplan.exporters.html import format_program_html
from runplan.exporters.markdown import format_program_markdown
from runplan.presentation.program_text import format_program_text
from tests.helpers import program_data


PROJECT_DIR = Path(__file__).resolve().parents[1]
PROGRAM_FIXTURES = PROJECT_DIR / "tests" / "fixtures" / "programs"


class PdfExportTests(unittest.TestCase):
    def test_pdf_and_text_have_matching_sections_and_one_week_per_page(self) -> None:
        program = build_program_export(
            load_program_model(program_data()), WeekSelection.all()
        )
        text = format_program_text(program)
        html = format_program_html(program)
        markdown = format_program_markdown(program)

        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "parity.pdf"
            export_pdf(program, output, force=False)
            pages = [page.extract_text() or "" for page in PdfReader(output).pages]

        self.assertEqual(3, len(pages))
        self.assertIn("Characterization Plan", pages[0])
        self.assertIn("Week 1", pages[1])
        self.assertNotIn("Week 2", pages[1])
        self.assertIn("Week 2", pages[2])
        self.assertNotIn("Week 1", pages[2])
        for value in (
            "Start week: 2026-W53",
            "Total workouts: 3",
            "Estimated total duration:",
            "Estimated total distance:",
            "Mixed",
            "Repeat 2 times:",
            "400 m @ 4:30-4:45 min/km",
        ):
            for document in (text, html, markdown, "\n".join(pages)):
                self.assertIn(value, document)

    def test_exports_complete_fictional_program(self) -> None:
        program = build_program_export(
            load_definition_model(PROGRAM_FIXTURES / "morgan-example-5k.yaml"),
            WeekSelection.all(),
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "Morgan Example running program.pdf"
            export_pdf(program, output, force=False)

            reader = PdfReader(output)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)

            self.assertEqual(3, len(reader.pages))
            self.assertIn("Morgan Example - Beginner", text)
            self.assertIn("Program weeks: 2", text)
            self.assertIn("Selected weeks: 2", text)
            self.assertIn("Total workouts: 4", text)
            self.assertIn("Estimated total duration:", text)
            self.assertIn("Estimated total distance:", text)
            self.assertGreaterEqual(text.count("WORKOUTS"), 2)
            self.assertGreaterEqual(text.count("DURATION"), 2)
            self.assertGreaterEqual(text.count("DISTANCE"), 2)
            self.assertIn("Run", text)
            self.assertIn("Recovery", text)
            self.assertIn("MONDAY", text)
            self.assertIn("TUESDAY", text)
            self.assertIn("THURSDAY", text)
            self.assertIn("SATURDAY", text)
            self.assertIn("Easy intervals A", text)
            self.assertIn("Longer intervals", text)
            for week in range(1, 3):
                self.assertIn(f"Week {week}", text)

    def test_refuses_to_overwrite_without_force(self) -> None:
        program = build_program_export(
            load_definition_model(PROGRAM_FIXTURES / "riley-example-5k.yaml"),
            WeekSelection.all(),
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "program.pdf"
            export_pdf(program, output, force=False)

            with self.assertRaises(FileExistsError):
                export_pdf(program, output, force=False)

            export_pdf(program, output, force=True)
            self.assertGreater(output.stat().st_size, 0)

    def test_export_is_deterministic(self) -> None:
        program = build_program_export(
            load_program_model(program_data()), WeekSelection.all()
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            first = Path(temporary_dir) / "first.pdf"
            second = Path(temporary_dir) / "second.pdf"
            export_pdf(program, first, force=False)
            export_pdf(program, second, force=False)

            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_exports_pace_target_in_minutes_per_kilometer(self) -> None:
        program = build_program_export(
            load_definition_model(
                PROJECT_DIR / "docs" / "examples" / "distance-workout.yaml"
            ),
            WeekSelection.all(),
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            output = Path(temporary_dir) / "pace-target.pdf"
            export_pdf(program, output, force=False)

            reader = PdfReader(output)
            text = "\n".join(page.extract_text() or "" for page in reader.pages)
            self.assertIn("400 m @ 4:30-4:45 min/km", text)

    @unittest.skipUnless(shutil.which("pdftoppm"), "pdftoppm is not installed")
    def test_representative_pages_render_with_runplan_palette(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow is not installed")

        program = build_program_export(
            load_program_model(program_data()), WeekSelection.all()
        )

        with tempfile.TemporaryDirectory() as temporary_dir:
            directory = Path(temporary_dir)
            output = directory / "visual-regression.pdf"
            rendered = directory / "page"
            export_pdf(program, output, force=False)
            subprocess.run(
                [
                    "pdftoppm",
                    "-f",
                    "1",
                    "-l",
                    "2",
                    "-r",
                    "72",
                    "-png",
                    str(output),
                    str(rendered),
                ],
                check=True,
                capture_output=True,
            )
            pages = [
                Image.open(directory / f"page-{page}.png").convert("RGB")
                for page in (1, 2)
            ]

            self.assertEqual([(596, 842), (596, 842)], [page.size for page in pages])
            for page in pages:
                pixels = list(page.get_flattened_data())
                warm_paper = sum(
                    240 <= red <= 250 and 240 <= green <= 249 and 232 <= blue <= 244
                    for red, green, blue in pixels
                )
                runplan_green = sum(
                    15 <= red <= 50 and 80 <= green <= 125 and 55 <= blue <= 100
                    for red, green, blue in pixels
                )
                self.assertGreater(warm_paper, len(pixels) // 2)
                self.assertGreater(runplan_green, 100)


if __name__ == "__main__":
    unittest.main()
