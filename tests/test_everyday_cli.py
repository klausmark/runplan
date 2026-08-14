"""CLI surface for ``runplan everyday`` (Step 10 ``application/everyday``).

The tests use ``cli_parser.build_parser`` to parse arguments and
``run_everyday_propose`` / ``run_everyday_accept`` to execute the
subcommands. ``capsys`` captures stdout and stderr; ``tmp_path``
provides a working directory for the proposal JSON files.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from runplan.cli import build_parser, run_everyday_accept, run_everyday_propose
from tests.helpers import program_data


@pytest.fixture
def yaml_file(tmp_path: Path) -> Path:
    path = tmp_path / "plan.yaml"
    import yaml

    yaml.safe_dump(program_data(), path.open("w"), sort_keys=False, allow_unicode=True)
    return path


# ---------------------------------------------------------------------------
# Parser wiring
# ---------------------------------------------------------------------------


def test_parser_accepts_everyday_propose(yaml_file: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["everyday", "propose", str(yaml_file)])
    assert args.command == "everyday"
    assert args.everyday_command == "propose"
    assert args.yaml_file == yaml_file
    assert args.goal == "maintain"
    assert args.horizon_days == 14


def test_parser_accepts_everyday_accept(yaml_file: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(["everyday", "accept", str(yaml_file), "--proposal", "proposal.json"])
    assert args.command == "everyday"
    assert args.everyday_command == "accept"


def test_parser_rejects_unknown_goal(yaml_file: Path) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args(["everyday", "propose", str(yaml_file), "--goal", "unknown"])


# ---------------------------------------------------------------------------
# run_everyday_propose
# ---------------------------------------------------------------------------


def test_run_everyday_propose_outputs_overview_text(
    yaml_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "everyday",
            "propose",
            str(yaml_file),
            "--start",
            "2027-01-11",
            "--training-days",
            "1,3,5,7",
        ]
    )
    rc = run_everyday_propose(args)

    assert rc == 0
    captured = capsys.readouterr()
    assert "Everyday plan" in captured.out
    assert "Workouts:" in captured.out
    assert captured.err == ""


def test_run_everyday_propose_json_writes_proposal_file(
    yaml_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    proposal_path = yaml_file.parent / f"{yaml_file.name}.proposal.json"
    args = parser.parse_args(
        [
            "everyday",
            "propose",
            str(yaml_file),
            "--start",
            "2027-01-11",
            "--format",
            "json",
            "--training-days",
            "1,3,5,7",
        ]
    )
    rc = run_everyday_propose(args)

    assert rc == 0
    captured = capsys.readouterr()
    assert proposal_path.exists()
    payload = json.loads(proposal_path.read_text())
    assert payload["goal"] == "maintain"
    assert payload["start_date"] == "2027-01-11"
    assert "Proposal written to" in captured.err


def test_run_everyday_propose_unknown_program_returns_5(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    missing = tmp_path / "missing.yaml"
    args = parser.parse_args(["everyday", "propose", str(missing), "--start", "2027-01-11"])
    rc = run_everyday_propose(args)
    assert rc == 5
    captured = capsys.readouterr()
    assert "propose failed" in captured.err


def test_run_everyday_propose_invalid_date_returns_2(
    yaml_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "everyday",
            "propose",
            str(yaml_file),
            "--start",
            "not-a-date",
            "--training-days",
            "1,3,5,7",
        ]
    )
    rc = run_everyday_propose(args)
    assert rc == 2


# ---------------------------------------------------------------------------
# run_everyday_accept
# ---------------------------------------------------------------------------


def test_run_everyday_accept_appends_weeks_to_program(
    yaml_file: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    # Step 1: propose with JSON output
    propose_args = parser.parse_args(
        [
            "everyday",
            "propose",
            str(yaml_file),
            "--start",
            "2027-01-11",
            "--format",
            "json",
            "--training-days",
            "1,3,5,7",
        ]
    )
    assert run_everyday_propose(propose_args) == 0
    proposal_path = yaml_file.parent / f"{yaml_file.name}.proposal.json"
    assert proposal_path.exists()

    # Step 2: accept
    accept_args = parser.parse_args(
        [
            "everyday",
            "accept",
            str(yaml_file),
            "--proposal",
            str(proposal_path),
        ]
    )
    rc = run_everyday_accept(accept_args)
    assert rc == 0

    captured = capsys.readouterr()
    assert "Accepted" in captured.out

    # Step 3: verify the program YAML now has 4 weeks
    import yaml

    with yaml_file.open() as f:
        data = yaml.safe_load(f)
    assert len(data["weeks"]) == 4


def test_run_everyday_accept_missing_proposal_returns_5(
    yaml_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "everyday",
            "accept",
            str(yaml_file),
            "--proposal",
            str(tmp_path / "missing.json"),
        ]
    )
    rc = run_everyday_accept(args)
    assert rc == 5


def test_run_everyday_accept_invalid_proposal_returns_2(
    yaml_file: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    parser = build_parser()
    bad = tmp_path / "bad.json"
    bad.write_text("not a json document", encoding="utf-8")
    args = parser.parse_args(
        [
            "everyday",
            "accept",
            str(yaml_file),
            "--proposal",
            str(bad),
        ]
    )
    rc = run_everyday_accept(args)
    assert rc == 2
