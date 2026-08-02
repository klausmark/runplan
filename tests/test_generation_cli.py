"""CLI tests for the first 10K generator."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path

import pytest

from runplan.cli import run_generate
from runplan.cli_parser import build_parser


@pytest.fixture()
def cli_parser(tmp_path: Path):
    return build_parser(tmp_path)


def test_generate_first_10k_writes_to_stdout(capsys, cli_parser) -> None:
    arguments = cli_parser.parse_args(
        [
            "generate",
            "first-10k",
            "--start-week",
            "2026-W32",
            "--duration-weeks",
            "12",
            "--training-days",
            "1,2,3,4,5,6,7",
            "--sessions-per-week",
            "4",
            "--current-weekly-km",
            "25",
            "--current-longest-km",
            "6",
        ]
    )
    result = run_generate(arguments)
    assert result == 0
    captured = capsys.readouterr()
    assert "program:" in captured.out
    assert "weeks:" in captured.out
    assert "first-10k-2026-w32" in captured.out


def test_generate_first_10k_writes_to_file(tmp_path: Path, cli_parser) -> None:
    output = tmp_path / "program.yaml"
    arguments = cli_parser.parse_args(
        [
            "generate",
            "first-10k",
            "--start-week",
            "2026-W32",
            "--duration-weeks",
            "10",
            "--training-days",
            "2,4,6",
            "--sessions-per-week",
            "3",
            "--output",
            str(output),
        ]
    )
    result = run_generate(arguments)
    assert result == 0
    assert output.exists()
    assert "program:" in output.read_text(encoding="utf-8")


def test_generate_first_10k_rejects_invalid_duration(tmp_path: Path, cli_parser) -> None:
    arguments = cli_parser.parse_args(
        [
            "generate",
            "first-10k",
            "--duration-weeks",
            "5",
        ]
    )
    assert run_generate(arguments) == 2


def test_generate_first_10k_rejects_invalid_pace(tmp_path: Path, cli_parser) -> None:
    arguments = cli_parser.parse_args(
        [
            "generate",
            "first-10k",
            "--known-easy-pace",
            "bogus",
        ]
    )
    assert run_generate(arguments) == 2


def test_generate_first_10k_with_race_date(capsys, cli_parser) -> None:
    arguments = cli_parser.parse_args(
        [
            "generate",
            "first-10k",
            "--start-week",
            "2026-W32",
            "--duration-weeks",
            "12",
            "--race-date",
            "2026-10-25",
            "--training-days",
            "1,3,5,7",
            "--sessions-per-week",
            "3",
        ]
    )
    result = run_generate(arguments)
    assert result == 0
    captured = capsys.readouterr()
    assert "program:" in captured.out
    assert "race" in captured.out or "10km" in captured.out


def test_generate_first_10k_with_known_pace(capsys, cli_parser) -> None:
    arguments = cli_parser.parse_args(
        [
            "generate",
            "first-10k",
            "--start-week",
            "2026-W32",
            "--duration-weeks",
            "12",
            "--training-days",
            "1,3,5,7",
            "--sessions-per-week",
            "3",
            "--known-easy-pace",
            "5:45-6:00 min/km",
        ]
    )
    result = run_generate(arguments)
    assert result == 0
    captured = capsys.readouterr()
    assert "min/km" in captured.out


def test_run_generate_with_unknown_subcommand() -> None:
    arguments = Namespace(generate_command="bogus")
    result = run_generate(arguments)
    assert result == 2
