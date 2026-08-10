import shutil
import subprocess
from pathlib import Path
from unittest.mock import Mock

import pytest
from pypdf import PdfReader

from runplan import (
    WeekSelection,
    build_program_export,
    export_pdf,
    load_definition_model,
)
from runplan.exporters.html import format_program_html
from runplan.exporters.markdown import format_program_markdown
from runplan.exporters.pdf import _draw_runplan_mark
from runplan.parsing.yaml_loader import load_program_model
from runplan.presentation.program_text import format_program_text
from tests.helpers import program_data

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROGRAM_FIXTURES = PROJECT_DIR / "tests" / "fixtures" / "programs"


class TestPdfExport:
    def test_runplan_mark_uses_vector_geometry_instead_of_font_text(self) -> None:
        canvas = Mock()
        glyph = canvas.beginPath.return_value

        _draw_runplan_mark(canvas, 10, 20, 64)

        canvas.rotate.assert_called_once_with(4)
        canvas.roundRect.assert_called_once_with(7, 7, 50, 50, 15, fill=1, stroke=0)
        canvas.drawPath.assert_called_once_with(glyph, fill=1, stroke=0, fillMode=0)
        canvas.drawCentredString.assert_not_called()

    def test_pdf_and_text_have_matching_sections_and_one_week_per_page(
        self, tmp_path: Path
    ) -> None:
        program = build_program_export(load_program_model(program_data()), WeekSelection.all())
        text = format_program_text(program)
        html = format_program_html(program)
        markdown = format_program_markdown(program)

        output = tmp_path / "parity.pdf"
        export_pdf(program, output, force=False)
        pages = [page.extract_text() or "" for page in PdfReader(output).pages]

        assert len(pages) == 3
        assert "Characterization Plan" in pages[0]
        assert "Week 1" in pages[1]
        assert "Week 2" not in pages[1]
        assert "Week 2" in pages[2]
        assert "Week 1" not in pages[2]
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
                assert value in document

    def test_exports_complete_fictional_program(self, tmp_path: Path) -> None:
        program = build_program_export(
            load_definition_model(PROGRAM_FIXTURES / "morgan-example-5k.yaml"),
            WeekSelection.all(),
        )

        output = tmp_path / "Morgan Example running program.pdf"
        export_pdf(program, output, force=False)

        reader = PdfReader(output)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)

        assert len(reader.pages) == 3
        for expected in (
            "Morgan Example - Beginner",
            "Program weeks: 2",
            "Selected weeks: 2",
            "Total workouts: 4",
            "Estimated total duration:",
            "Estimated total distance:",
            "Run",
            "Recovery",
            "MONDAY",
            "TUESDAY",
            "THURSDAY",
            "SATURDAY",
            "Easy intervals A",
            "Longer intervals",
            "Week 1",
            "Week 2",
        ):
            assert expected in text
        assert text.count("WORKOUTS") >= 2
        assert text.count("DURATION") >= 2
        assert text.count("DISTANCE") >= 2

    def test_refuses_to_overwrite_without_force(self, tmp_path: Path) -> None:
        program = build_program_export(
            load_definition_model(PROGRAM_FIXTURES / "riley-example-5k.yaml"),
            WeekSelection.all(),
        )

        output = tmp_path / "program.pdf"
        export_pdf(program, output, force=False)

        with pytest.raises(FileExistsError):
            export_pdf(program, output, force=False)

        export_pdf(program, output, force=True)
        assert output.stat().st_size > 0

    def test_export_is_deterministic(self, tmp_path: Path) -> None:
        program = build_program_export(load_program_model(program_data()), WeekSelection.all())

        first = tmp_path / "first.pdf"
        second = tmp_path / "second.pdf"
        export_pdf(program, first, force=False)
        export_pdf(program, second, force=False)

        assert first.read_bytes() == second.read_bytes()

    def test_exports_pace_target_in_minutes_per_kilometer(self, tmp_path: Path) -> None:
        program = build_program_export(
            load_definition_model(PROJECT_DIR / "docs" / "examples" / "distance-workout.yaml"),
            WeekSelection.all(),
        )

        output = tmp_path / "pace-target.pdf"
        export_pdf(program, output, force=False)

        reader = PdfReader(output)
        text = "\n".join(page.extract_text() or "" for page in reader.pages)
        assert "400 m @ 4:30-4:45 min/km" in text

    @pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="pdftoppm is not installed")
    def test_representative_pages_render_with_runplan_palette(self, tmp_path: Path) -> None:
        Image = pytest.importorskip("PIL.Image")

        program = build_program_export(load_program_model(program_data()), WeekSelection.all())

        output = tmp_path / "visual-regression.pdf"
        rendered = tmp_path / "page"
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
        pages = [Image.open(tmp_path / f"page-{page}.png").convert("RGB") for page in (1, 2)]

        assert [page.size for page in pages] == [(596, 842), (596, 842)]
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
            assert warm_paper > len(pixels) // 2
            assert runplan_green > 100


def _load_nike_export(slug: str):
    import yaml

    raw = yaml.safe_load(
        (PROJECT_DIR / "src" / "runplan" / "templates" / "programs" / f"{slug}.yaml").read_text(
            encoding="utf-8"
        )
    )
    program = load_program_model(raw)
    return build_program_export(program, WeekSelection.all())


def _pdf_text(path: Path) -> str:
    return "\n".join(page.extract_text() or "" for page in PdfReader(path).pages)


class TestPdfCoachingFormatting:
    def test_pdf_coaching_renders_pace_chart_intro_and_examples(self, tmp_path: Path) -> None:
        export = _load_nike_export("nike-5k")
        output = tmp_path / "nike-5k.pdf"
        export_pdf(export, output, force=False)

        text = _pdf_text(output)

        assert "Throughout the plan" in text
        assert "Worked examples" in text
        assert "If your last 5K was 27:00" in text

    def test_pdf_coaching_renders_bold_in_glossary_terms(self, tmp_path: Path) -> None:
        export = _load_nike_export("nike-5k")
        output = tmp_path / "nike-5k.pdf"
        export_pdf(export, output, force=False)

        text = _pdf_text(output)

        assert "Progression Run" in text
        assert "Intervals" in text
        assert "**Progression Run**" not in text
        assert "**" not in text

    def test_pdf_coaching_renders_bullets_with_bullet_character(self, tmp_path: Path) -> None:
        export = _load_nike_export("nike-5k")
        output = tmp_path / "nike-5k.pdf"
        export_pdf(export, output, force=False)

        text = _pdf_text(output)

        assert "\u2022" in text

    def test_pdf_coaching_renders_italic_in_pace_chart_examples(self, tmp_path: Path) -> None:
        export = _load_nike_export("nike-5k")
        output = tmp_path / "nike-5k.pdf"
        export_pdf(export, output, force=False)

        text = _pdf_text(output)

        assert "If your last 5K was 27:00" in text
        assert "Best Mile Pace: 8:00 minutes" in text
        assert "*If your last 5K was 27:00*" not in text
