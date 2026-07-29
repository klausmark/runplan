from argparse import Namespace
from contextlib import redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from runplan.cli import (
    main,
    parse_arguments,
    prepare_sync_selections,
    run_multi_week_sync,
    run_preview,
    week_selection,
)
from tests.helpers import compiled_week, program_data


@pytest.fixture
def program_path(tmp_path: Path) -> Path:
    source = tmp_path / "plan.yaml"
    source.write_text(yaml.safe_dump(program_data()), encoding="utf-8")
    return source


def test_parser_defaults_to_overview_and_current_plus_one_week() -> None:
    arguments = parse_arguments(["sync", "plan.yaml", "--dry-run"])

    assert arguments.output == "overview"
    assert week_selection(arguments).kind == "ahead"
    assert week_selection(arguments).weeks == (1,)


def test_parser_rejects_multiple_selector_flags() -> None:
    with pytest.raises(SystemExit):
        parse_arguments(["sync", "plan.yaml", "--select-weeks", "1", "--weeks-ahead", "1"])


def test_default_and_explicit_selectors() -> None:
    assert week_selection(Namespace()).kind == "ahead"
    assert week_selection(Namespace(select_weeks="2,4-5")).weeks == (2, 4, 5)
    with pytest.raises(ValueError, match="non-negative"):
        week_selection(Namespace(weeks_ahead=-1))


@pytest.mark.parametrize("value", ["current", "next", "all"])
def test_relative_and_all_flags_map_to_domain_kinds(value) -> None:
    assert week_selection(Namespace(select_weeks=value)).kind == value


def test_export_command_is_dispatched_from_native_cli(program_path, tmp_path) -> None:
    stdout = StringIO()
    with patch("runplan.cli.export_pdf") as export, redirect_stdout(stdout):
        result = main(["export", str(program_path), "--output", str(tmp_path / "plan.pdf")])

    assert result == 0
    export.assert_called_once()
    assert "Exported 2 weeks" in stdout.getvalue()


def test_pdf_export_receives_only_selected_weeks(program_path, tmp_path) -> None:
    with patch("runplan.cli.export_pdf") as export, redirect_stdout(StringIO()):
        result = main(
            [
                "export",
                str(program_path),
                "--format",
                "pdf",
                "--output",
                str(tmp_path / "plan.pdf"),
                "--select-weeks",
                "2",
            ]
        )

    assert result == 0
    assert [week.number for week in export.call_args.args[0].weeks] == [2]


def test_sync_preparation_selects_and_compiles_multiple_weeks(program_path) -> None:
    selections = prepare_sync_selections(Namespace(yaml_file=program_path, select_weeks="1-2"))

    assert [program["week"] for program, _ in selections] == [1, 2]
    assert [len(compiled) for _, compiled in selections] == [2, 1]


def test_default_sync_selects_current_plan_week_and_one_week_ahead(program_path) -> None:
    first = prepare_sync_selections(Namespace(yaml_file=program_path, today=date(2026, 12, 28)))
    second = prepare_sync_selections(Namespace(yaml_file=program_path, today=date(2027, 1, 4)))

    assert [program["week"] for program, _ in first] == [1, 2]
    assert [program["week"] for program, _ in second] == [2]


@pytest.mark.parametrize("expression", ["all", "1-2,2"])
def test_all_and_overlapping_expressions_prepare_each_week_once(program_path, expression) -> None:
    prepared = prepare_sync_selections(Namespace(yaml_file=program_path, select_weeks=expression))

    assert [program["week"] for program, _ in prepared] == [1, 2]


def test_preview_handler_only_formats_and_prints_prepared_data() -> None:
    selections = [compiled_week(1), compiled_week(2)]
    stdout = StringIO()

    with redirect_stdout(stdout):
        result = run_preview(Namespace(output="overview"), selections)

    assert result == 0
    assert "Week 1" in stdout.getvalue()
    assert "Week 2" in stdout.getvalue()


def test_multi_week_handler_delegates_to_additive_use_case() -> None:
    selections = [compiled_week(1), compiled_week(2)]
    client = object()

    with (
        patch("runplan.cli.login_to_garmin", return_value=client),
        patch("runplan.cli.synchronize_program_weeks") as synchronize,
        redirect_stdout(StringIO()),
    ):
        result = run_multi_week_sync(selections)

    assert result == 0
    assert synchronize.call_args.args[0] is client
    assert synchronize.call_args.args[2] == selections
