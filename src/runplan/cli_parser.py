"""Construct the Runplan command-line argument parser."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Any

from .logging_config import LOG_LEVELS


def add_week_selectors(parser: argparse.ArgumentParser, *, allow_weeks_ahead: bool = False) -> None:
    """Add the shared calendar-week selector options."""
    selectors = parser.add_mutually_exclusive_group()
    selectors.add_argument(
        "--select-weeks",
        help="Plan weeks (1,3,5-7) or current, next, or all",
    )
    if allow_weeks_ahead:
        selectors.add_argument(
            "--weeks-ahead",
            type=int,
            help="Current plan week plus this many subsequent weeks (default: 1)",
        )


def build_parser(program_directory: Path) -> argparse.ArgumentParser:
    """Build the CLI parser without reading process-global arguments."""
    parser = argparse.ArgumentParser(
        prog="runplan",
        description="Validate, export, and sync YAML running programs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    _add_sync_command(commands)
    _add_user_command(commands)
    _add_export_command(commands)
    commands.add_parser(
        "hash-password",
        help="Generate a password verifier for RUNPLAN_WEB_PASSWORD_HASH",
    )
    _add_serve_command(commands, program_directory)
    _add_reconcile_command(commands)
    return parser


def _add_sync_command(commands: Any) -> None:
    sync_parser = commands.add_parser("sync", help="Sync program weeks with Garmin Connect")
    sync_target = sync_parser.add_mutually_exclusive_group(required=True)
    sync_target.add_argument("user_id", nargs="?", help="Configured Runplan user ID")
    sync_target.add_argument(
        "--all", dest="all_users", action="store_true", help="Sync every configured user"
    )
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument("--output", choices=("overview", "json"), default="overview")
    sync_parser.add_argument("--delete-all", action="store_true")
    sync_parser.add_argument("--prune", action="store_true")
    sync_parser.add_argument("--yes", action="store_true")
    add_week_selectors(sync_parser, allow_weeks_ahead=True)


def _add_user_command(commands: Any) -> None:
    user_parser = commands.add_parser("user", help="Manage configured Runplan users")
    user_commands = user_parser.add_subparsers(dest="user_command", required=True)
    set_plan_parser = user_commands.add_parser("set-plan", help="Set a user's active program")
    set_plan_parser.add_argument("user_id")
    set_plan_parser.add_argument("filename")


def _add_export_command(commands: Any) -> None:
    export_parser = commands.add_parser("export", help="Render selected program weeks")
    export_parser.add_argument("yaml_file", type=Path, help="Path to the program YAML file")
    export_parser.add_argument(
        "--format", choices=("pdf", "text", "html", "markdown"), default="pdf"
    )
    export_parser.add_argument(
        "--output",
        type=Path,
        help="Output file (required for PDF, HTML, and Markdown; unavailable for text)",
    )
    export_parser.add_argument("--force", action="store_true")
    add_week_selectors(export_parser)


def _add_serve_command(commands: Any, program_directory: Path) -> None:
    serve_parser = commands.add_parser("serve", help="Run the password-protected web frontend")
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Listen address (use 0.0.0.0 for remote access)"
    )
    serve_parser.add_argument("--port", type=int, default=8000, help="Listen port")
    serve_parser.add_argument(
        "--log-level",
        choices=LOG_LEVELS,
        type=str.upper,
        default=os.getenv("RUNPLAN_LOG_LEVEL", "INFO").upper(),
        help="Server log level written to stdout (default: RUNPLAN_LOG_LEVEL or INFO)",
    )
    serve_parser.add_argument(
        "--program-dir",
        type=Path,
        default=program_directory,
        help="Directory containing editable YAML programs (default: RUNPLAN_PROGRAM_DIR or the user data directory)",
    )


def _add_reconcile_command(commands: Any) -> None:
    reconcile_parser = commands.add_parser(
        "reconcile", help="Refresh completed and missed workouts from Garmin"
    )
    reconcile_parser.add_argument("yaml_file", type=Path, help="Path to the program YAML file")
