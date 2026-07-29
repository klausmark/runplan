from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path

import pytest
import yaml

from runplan.application.export import build_program_export
from runplan.cli import main
from runplan.domain.selectors import WeekSelection
from runplan.exporters.html import export_html, format_program_html
from runplan.exporters.markdown import export_markdown, format_program_markdown
from runplan.parsing.yaml_loader import load_program_model
from tests.helpers import program_data


@pytest.fixture
def program_export():
    return build_program_export(load_program_model(program_data()), WeekSelection.all())


def test_html_is_standalone_and_escapes_user_content() -> None:
    raw = program_data()
    raw["program"]["name"] = "Plan <unsafe> & complete"
    raw["program"]["description"] = "Use <script> & recover"
    export = build_program_export(load_program_model(raw), WeekSelection.all())

    document = format_program_html(export)

    assert document.startswith("<!doctype html>")
    assert '<meta charset="utf-8">' in document
    assert "Plan &lt;unsafe&gt; &amp; complete" in document
    assert "Use &lt;script&gt; &amp; recover" in document
    assert "<script>" not in document


def test_markdown_is_deterministic_commonmark_and_escapes_content() -> None:
    raw = program_data()
    raw["program"]["name"] = "Plan *fast* <safe>"
    export = build_program_export(load_program_model(raw), WeekSelection.all())

    first = format_program_markdown(export)
    second = format_program_markdown(export)

    assert first == second
    assert first.startswith("# Plan \\*fast\\* \\<safe\\>\n")
    assert first.count("\n---\n") == 2
    assert "```text\nWarmup: 1 km" in first


@pytest.mark.parametrize(
    ("filename", "exporter"),
    [("plan.html", export_html), ("plan.md", export_markdown)],
)
def test_file_exports_refuse_overwrite_without_force(
    tmp_path: Path, program_export, filename, exporter
) -> None:
    output = tmp_path / filename
    exporter(program_export, output, False)

    with pytest.raises(FileExistsError):
        exporter(program_export, output, False)

    exporter(program_export, output, True)
    assert output.stat().st_size > 0


@pytest.mark.parametrize(
    ("export_format", "suffix", "week_one", "week_two"),
    [
        ("html", ".html", 'id="week-1"', 'id="week-2"'),
        ("markdown", ".md", "## Week 1 ", "## Week 2 "),
    ],
)
def test_cli_writes_only_selected_week(
    tmp_path: Path, export_format, suffix, week_one, week_two
) -> None:
    source = tmp_path / "plan.yaml"
    output = tmp_path / f"plan{suffix}"
    source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
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
    assert result == 0
    assert week_one not in document
    assert week_two in document
    assert "Exported 1 weeks" in stdout.getvalue()


@pytest.mark.parametrize("export_format", ["html", "markdown"])
def test_cli_requires_output_for_file_exports(tmp_path: Path, export_format) -> None:
    source = tmp_path / "plan.yaml"
    source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
    stderr = StringIO()

    with redirect_stderr(stderr):
        result = main(["export", str(source), "--format", export_format])

    assert result == 2
    assert "requires --output" in stderr.getvalue()
