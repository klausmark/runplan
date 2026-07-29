"""Command-line adapter for Runplan."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from argparse import Namespace
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Any

from .application.export import build_program_export
from .application.ports import StateRepository
from .application.preview import build_preview
from .application.sync import (
    plan_program_weeks,
    reconcile_program,
    synchronize_program_weeks,
)
from .cli_parser import add_week_selectors
from .cli_selection import prepare_sync_selections, week_selection
from .cli_sync import run_sync
from .domain.errors import WorkoutDefinitionError
from .exporters.html import export_html
from .exporters.markdown import export_markdown
from .exporters.pdf import export_pdf
from .integrations.garmin.client import login_to_garmin
from .logging_config import LOG_LEVELS
from .parsing.values import parse_pace
from .parsing.yaml_loader import load_definition_model
from .presentation.json_output import format_json
from .presentation.overview import format_overview
from .presentation.program_text import format_program_text
from .state.json_repository import JsonStateRepository
from .state.yaml_repository import YamlStateRepository


def default_program_directory() -> Path:
    """Return the server-owned program directory outside the source checkout."""
    configured = os.getenv("RUNPLAN_PROGRAM_DIR")
    if configured:
        return Path(configured).expanduser()
    data_home = os.getenv("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "runplan" / "programs"


def run_preview(
    arguments: Namespace,
    selections: list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]],
) -> int:
    """Render a prepared multi-week dry-run using the selected formatter."""
    sync_plan = plan_program_weeks(
        getattr(arguments, "repository", None) or JsonStateRepository(),
        selections,
        prune=getattr(arguments, "prune", False),
        today=getattr(arguments, "today", None),
    )
    preview = build_preview(selections, sync_plan)
    formatter = format_json if arguments.output == "json" else format_overview
    print(formatter(preview))
    return 0


def run_multi_week_sync(
    selections: list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]],
    *,
    prune: bool = False,
    today: date | None = None,
    repository: StateRepository | None = None,
    credentials_file: Path | None = None,
    token_store: Path | None = None,
) -> int:
    """Execute additive Garmin synchronization for prepared weeks."""
    try:
        client = login_to_garmin(credentials_file=credentials_file, token_store=token_store)
        results = synchronize_program_weeks(
            client,
            repository or JsonStateRepository(),
            selections,
            prune=prune,
            today=today,
        )
        for result in results:
            for action in result.actions:
                if action.kind in ("completed", "missed"):
                    print(f"{action.kind.title()}: {action.name} ({action.date})")
        print("The selected weeks were synced with Garmin Connect.")
        return 0
    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 99


def build_parser() -> argparse.ArgumentParser:
    """Build the CLI parser without reading process-global arguments."""
    from .cli_parser import build_parser as build_cli_parser

    return build_cli_parser(default_program_directory())


def parse_arguments(argv: Sequence[str] | None = None) -> Namespace:
    parser = build_parser()
    arguments = parser.parse_args(argv)
    if arguments.command == "serve" and arguments.log_level not in LOG_LEVELS:
        parser.error("RUNPLAN_LOG_LEVEL must be one of: " + ", ".join(LOG_LEVELS))
    return arguments


def run_export(arguments: Namespace) -> int:
    """Render selected program weeks using the requested export format."""
    try:
        if arguments.format == "text" and arguments.output is not None:
            raise ValueError("text export writes to stdout; do not use --output")
        if arguments.format != "text" and arguments.output is None:
            raise ValueError(f"{arguments.format.upper()} export requires --output")
        program = load_definition_model(arguments.yaml_file)
        fallback_pace = parse_pace(
            os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"),
            "RUNPLAN_DEFAULT_PACE",
        )
        export = build_program_export(
            program,
            week_selection(arguments, default_all=True),
            fallback_pace_seconds_per_km=sum(fallback_pace) / len(fallback_pace),
        )
        if arguments.format == "text":
            print(format_program_text(export))
            return 0
        assert arguments.output is not None
        exporters = {
            "pdf": export_pdf,
            "html": export_html,
            "markdown": export_markdown,
        }
        exporters[arguments.format](export, arguments.output, arguments.force)
    except (WorkoutDefinitionError, ValueError) as exc:
        print(f"Invalid program definition: {exc}", file=sys.stderr)
        return 2
    except (FileExistsError, FileNotFoundError, OSError) as exc:
        print(f"Export failed: {exc}", file=sys.stderr)
        return 5

    output_path = arguments.output.expanduser().resolve()
    print(f"Exported {len(export.weeks)} weeks to {output_path}")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    arguments = parse_arguments(argv)
    if arguments.command == "sync":
        return run_user_sync(arguments)
    if arguments.command == "user":
        return run_user_command(arguments)
    if arguments.command == "export":
        return run_export(arguments)
    if arguments.command == "hash-password":
        return run_hash_password()
    if arguments.command == "serve":
        from .web import serve

        return serve(
            arguments.host,
            arguments.port,
            arguments.program_dir,
            log_level=arguments.log_level,
        )
    if arguments.command == "reconcile":
        return run_reconcile(arguments)
    return 2


def run_hash_password() -> int:
    """Prompt for and print a web password verifier without echoing the password."""
    from .web_auth import format_password_hash

    password = getpass.getpass("Web password: ")
    confirmation = getpass.getpass("Confirm web password: ")
    if not password:
        print("Web password must not be empty.", file=sys.stderr)
        return 2
    if password != confirmation:
        print("Passwords do not match.", file=sys.stderr)
        return 2
    print(format_password_hash(password))
    return 0


def _program_path(user_id: str, filename: str) -> Path:
    """Resolve one user's active program inside the configured program root."""
    return default_program_directory().expanduser().resolve() / user_id / filename


def run_user_command(arguments: Namespace) -> int:
    """Execute user configuration commands."""
    from .users import WebError, load_user_registry

    if arguments.user_command != "set-plan":
        return 2
    try:
        registry = load_user_registry()
        user = registry.get(arguments.user_id)
        path = _program_path(user.id, arguments.filename)
        if not path.is_file():
            raise ValueError(f"Program not found for {user.id}: {path}")
        load_definition_model(path)
        registry.set_active_program(user.id, arguments.filename)
    except (ValueError, WorkoutDefinitionError, WebError) as exc:
        print(f"Cannot set active program: {exc}", file=sys.stderr)
        return 2
    print(f"Active program for {user.id}: {arguments.filename}")
    return 0


def _sync_one_user(arguments: Namespace, user: Any) -> int:
    """Resolve a user profile and delegate to the existing sync adapter."""
    if user.active_program is None:
        print(
            f"User {user.id} has no active program. "
            f"Set one with: runplan user set-plan {user.id} FILE",
            file=sys.stderr,
        )
        return 2
    path = _program_path(user.id, user.active_program)
    if not path.is_file():
        print(f"Active program for {user.id} was not found: {path}", file=sys.stderr)
        return 2
    values = vars(arguments).copy()
    values.update(
        yaml_file=path,
        repository=YamlStateRepository(path, legacy_directory=user.state_directory),
        credentials_file=user.credentials_file,
        token_store=user.token_store,
        fallback_pace_value=user.default_pace,
    )
    try:
        return run_sync(Namespace(**values))
    except SystemExit as exc:
        print(f"Sync failed for {user.id}: {exc}", file=sys.stderr)
        return 2


def run_user_sync(arguments: Namespace) -> int:
    """Synchronize one configured user or a best-effort batch of all users."""
    from .users import WebError, load_user_registry

    try:
        registry = load_user_registry()
    except ValueError as exc:
        print(f"Cannot load Runplan users: {exc}", file=sys.stderr)
        return 2
    if not arguments.all_users:
        try:
            user = registry.get(arguments.user_id)
        except WebError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return _sync_one_user(arguments, user)

    synced = skipped = failed = 0
    for user in registry.users():
        print(f"\nUser: {user.id} ({user.name})")
        if user.active_program is None:
            print("Skipped: no active program.")
            skipped += 1
            continue
        result = _sync_one_user(arguments, user)
        if result == 0:
            synced += 1
        else:
            failed += 1
            print(f"Failed: {user.id} (exit code {result}).", file=sys.stderr)
    print(f"\nSync summary: {synced} synced, {skipped} skipped, {failed} failed.")
    return 1 if failed else 0


def run_reconcile(arguments: Namespace) -> int:
    """Refresh lifecycle state without creating or pruning workouts."""
    try:
        program = load_definition_model(arguments.yaml_file)
        client = login_to_garmin()
        result = reconcile_program(client, YamlStateRepository(arguments.yaml_file), program.id)
    except (WorkoutDefinitionError, ValueError) as exc:
        print(f"Invalid program definition: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Reconcile failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 99
    if not result.actions:
        print("No historical workout status changed.")
        return 0
    for action in result.actions:
        print(f"{action.kind.title()}: {action.name} ({action.date})")
    return 0


__all__ = [
    "build_parser",
    "add_week_selectors",
    "main",
    "parse_arguments",
    "prepare_sync_selections",
    "run_export",
    "run_hash_password",
    "run_multi_week_sync",
    "run_preview",
    "run_reconcile",
    "run_sync",
    "run_user_command",
    "run_user_sync",
    "week_selection",
]


if __name__ == "__main__":
    raise SystemExit(main())
