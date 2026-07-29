from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
import yaml

from runplan.application.export import build_program_export
from runplan.cli import main
from runplan.domain.selectors import WeekSelection
from runplan.parsing.yaml_loader import load_program_model
from runplan.presentation.program_text import SECTION_DIVIDER, format_program_text
from tests.helpers import program_data


@pytest.fixture
def program():
    return load_program_model(program_data())


def test_common_model_selects_requested_weeks(program) -> None:
    export = build_program_export(program, WeekSelection.explicit("2"))

    assert export.name == "Characterization Plan"
    assert export.total_weeks == 2
    assert [week.number for week in export.weeks] == [2]
    assert export.weeks[0].workouts[0].name == "Long"
    assert export.weeks[0].workouts[0].source_name == "Week 2 - Long"
    assert export.selected_week_count == 1
    assert export.summary.workout_count == 1
    assert export.summary.estimated_duration_seconds == 60 * 60
    assert export.summary.estimated_distance_meters == 10_000
    assert export.summary == export.weeks[0].summary


def test_summaries_estimate_missing_quantities_and_exclude_timed_pauses(program) -> None:
    export = build_program_export(program, WeekSelection.explicit("1"))

    assert export.summary.workout_count == 2
    assert export.summary.estimated_duration_seconds == 47 * 60 + 42
    assert export.summary.estimated_distance_meters == pytest.approx(7_633.333, abs=0.001)
    assert export.summary == export.weeks[0].summary


def test_text_renderer_includes_details_without_sync_language(program) -> None:
    export = build_program_export(program, WeekSelection.explicit("1"))

    text = format_program_text(export)

    assert "Characterization Plan" in text
    assert "Start week: 2026-W53" in text
    assert "Program weeks: 2" in text
    assert "Selected weeks: 1" in text
    assert "Total workouts: 2" in text
    assert "Estimated total duration: 47 min 42 sec" in text
    assert "Estimated total distance: 7.6 km" in text
    assert "Week 1 (2026-12-28 to 2027-01-03)" in text
    assert "Workouts this week: 2" in text
    assert "Estimated duration this week: 47 min 42 sec" in text
    assert "Estimated distance this week: 7.6 km" in text
    assert text.index("Workouts this week: 2") < text.index("Monday · Mixed")
    assert text.count(SECTION_DIVIDER) == 1
    assert "Monday · Mixed · 8 min + 1.8 km" in text
    assert "Repeat 2 times:" in text
    assert "Run: 400 m @ 4:30-4:45 min/km" in text
    assert "Sync changes" not in text
    assert "Dry run" not in text


def test_text_export_matches_snapshot(program) -> None:
    export = build_program_export(program, WeekSelection.explicit("1"))
    snapshot = Path(__file__).parent / "snapshots" / "program_export_week_1.txt"

    assert snapshot.read_text(encoding="utf-8").rstrip() == format_program_text(export)


def test_environment_configures_fallback_pace_for_cli_export(tmp_path: Path, monkeypatch) -> None:
    source = write_program(tmp_path)
    stdout = StringIO()
    monkeypatch.setenv("RUNPLAN_DEFAULT_PACE", "5:00 min/km")

    with redirect_stdout(stdout):
        result = main(["export", str(source), "--format", "text", "--select-weeks", "2"])

    assert result == 0
    assert "Estimated total duration: 50 min" in stdout.getvalue()


def test_cli_rejects_invalid_environment_fallback_pace(tmp_path: Path, monkeypatch) -> None:
    source = write_program(tmp_path)
    stderr = StringIO()
    monkeypatch.setenv("RUNPLAN_DEFAULT_PACE", "fast")

    with redirect_stderr(stderr):
        result = main(["export", str(source), "--format", "text"])

    assert result == 2
    assert "RUNPLAN_DEFAULT_PACE" in stderr.getvalue()


def test_text_cli_writes_selected_weeks_to_stdout(tmp_path: Path) -> None:
    source = write_program(tmp_path)
    stdout = StringIO()

    with redirect_stdout(stdout):
        result = main(["export", str(source), "--format", "text", "--select-weeks", "2"])

    assert result == 0
    assert "Week 2 (" in stdout.getvalue()
    assert "Week 1 (" not in stdout.getvalue()


def test_text_cli_rejects_output_path(tmp_path: Path) -> None:
    source = write_program(tmp_path)
    stderr = StringIO()

    with redirect_stderr(stderr):
        result = main(
            [
                "export",
                str(source),
                "--format",
                "text",
                "--output",
                str(tmp_path / "plan.txt"),
            ]
        )

    assert result == 2
    assert "text export writes to stdout" in stderr.getvalue()


def test_pdf_cli_requires_output_path(tmp_path: Path) -> None:
    source = write_program(tmp_path)
    stderr = StringIO()

    with redirect_stderr(stderr):
        result = main(["export", str(source), "--format", "pdf"])

    assert result == 2
    assert "PDF export requires --output" in stderr.getvalue()


def write_program(directory: Path) -> Path:
    source = directory / "plan.yaml"
    source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
    return source
