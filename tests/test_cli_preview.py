import copy
import json
from argparse import Namespace
from contextlib import redirect_stderr, redirect_stdout
from datetime import date
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from runplan import run_sync
from tests.helpers import program_data


@pytest.fixture
def program_path(tmp_path: Path) -> Path:
    path = tmp_path / "program.yaml"
    path.write_text(
        yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False),
        encoding="utf-8",
    )
    return path


def sync_arguments(program_path: Path, **overrides) -> Namespace:
    values = {
        "yaml_file": program_path,
        "select_weeks": "1",
        "dry_run": True,
        "output": "overview",
        "delete_all": False,
        "yes": False,
    }
    values.update(overrides)
    return Namespace(**values)


def test_json_dry_run_is_machine_readable_and_does_not_login(program_path) -> None:
    args = sync_arguments(program_path, output="json")
    stdout = StringIO()

    with patch("runplan.cli_sync.login_to_garmin") as login, redirect_stdout(stdout):
        result = run_sync(args)

    assert result == 0
    login.assert_not_called()
    output = json.loads(stdout.getvalue())
    assert output["programId"] == "characterization-plan"
    assert output["weeks"][0]["week"] == 1
    workouts = output["weeks"][0]["workouts"]
    assert [item["id"] for item in workouts] == ["mixed", "easy"]
    assert workouts[0]["date"] == "2026-12-28"


def test_overview_dry_run_is_additive_and_does_not_mutate_state(program_path) -> None:
    state = {
        "program_id": "characterization-plan",
        "workouts": {"week-09/old": {"name": "Old workout", "date": "2026-11-01"}},
    }
    stdout = StringIO()

    with (
        patch("runplan.cli_sync.load_state", return_value=copy.deepcopy(state)),
        redirect_stdout(stdout),
    ):
        result = run_sync(sync_arguments(program_path))

    assert result == 0
    text = stdout.getvalue()
    assert "CHAR - W1 - Mixed - ~2.6k" in text
    assert "Monday · Mixed" in text
    assert "2026-12-28 · Week 1 - Mixed" not in text
    assert "17 min 42 sec + 2.6 km" in text
    assert "Old workout (2026-11-01)" not in text


def test_invalid_week_returns_definition_error_exit_code(program_path) -> None:
    stderr = StringIO()

    with redirect_stderr(stderr):
        result = run_sync(sync_arguments(program_path, select_weeks="0"))

    assert result == 2
    assert "week numbers must be positive" in stderr.getvalue()


def test_default_sync_reports_when_today_is_outside_the_program(program_path) -> None:
    args = sync_arguments(program_path, today=date(2026, 7, 26))
    del args.select_weeks
    stderr = StringIO()

    with redirect_stderr(stderr):
        result = run_sync(args)

    assert result == 2
    assert "Cannot select sync weeks" in stderr.getvalue()
    assert "outside the program" in stderr.getvalue()


def test_multi_week_dry_run_defaults_to_overview_output(program_path) -> None:
    stdout = StringIO()

    with redirect_stdout(stdout):
        result = run_sync(sync_arguments(program_path, select_weeks="all"))

    assert result == 0
    assert not stdout.getvalue().lstrip().startswith("{")
    assert "Week 1" in stdout.getvalue()
    assert "Week 2" in stdout.getvalue()


def test_prune_can_be_cancelled_before_login(program_path) -> None:
    args = sync_arguments(program_path, dry_run=False, prune=True)
    stdout = StringIO()

    with (
        patch("runplan.cli_sync.login_to_garmin") as login,
        patch("builtins.input", return_value="n"),
        redirect_stdout(stdout),
    ):
        result = run_sync(args)

    assert result == 0
    login.assert_not_called()
    assert "Sync changes:" in stdout.getvalue()
    assert "Sync cancelled" in stdout.getvalue()
