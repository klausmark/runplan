"""Command-line adapter for Runplan."""

from __future__ import annotations

import argparse
import json
import os
import sys
from argparse import Namespace
from datetime import date
from pathlib import Path
from typing import Sequence
from typing import Any

from .domain.selectors import WeekSelection
from .domain.errors import WorkoutDefinitionError
from .domain.estimates import estimate_steps
from .domain.workout_titles import garmin_workout_title
from .application.export import build_program_export
from .application.presentation_weeks import build_presentation_weeks, presentation_start
from .exporters.pdf import export_pdf
from .exporters.html import export_html
from .exporters.markdown import export_markdown
from .cli_sync import run_sync
from .integrations.garmin.mapper import build_workout
from .parsing.yaml_loader import load_definition, load_definition_model
from .parsing.values import parse_pace
from .application.preview import build_preview
from .application.sync import (
    discover_sync_state,
    plan_program_weeks,
    reconcile_program,
    rebuild_sync_state,
    synchronize_program_weeks,
)
from .integrations.garmin.client import login_to_garmin
from .presentation.json_output import format_json
from .presentation.overview import format_overview
from .presentation.program_text import format_program_text
from .state.json_repository import JsonStateRepository


def default_program_directory() -> Path:
    """Return the server-owned program directory outside the source checkout."""
    configured = os.getenv("RUNPLAN_PROGRAM_DIR")
    if configured:
        return Path(configured).expanduser()
    data_home = os.getenv("XDG_DATA_HOME")
    base = Path(data_home).expanduser() if data_home else Path.home() / ".local" / "share"
    return base / "runplan" / "programs"


def week_selection(arguments: Namespace, *, default_all: bool = False) -> WeekSelection:
    """Translate parsed CLI selector options to a domain value object."""
    expression = getattr(arguments, "select_weeks", None)
    if expression is not None:
        return WeekSelection.parse(expression)
    weeks_ahead = getattr(arguments, "weeks_ahead", None)
    if weeks_ahead is not None:
        return WeekSelection.ahead(weeks_ahead)
    return WeekSelection.all() if default_all else WeekSelection.ahead(1)


def add_week_selectors(
    parser: argparse.ArgumentParser, *, allow_weeks_ahead: bool = False
) -> None:
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


def prepare_sync_selections(
    arguments: Namespace,
    *,
    fallback_pace_value: str | None = None,
) -> list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]]:
    """Load, select, and compile weeks without terminal or Garmin I/O."""
    model = load_definition_model(arguments.yaml_file)
    fallback_pace = parse_pace(
        fallback_pace_value or os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"),
        "RUNPLAN_DEFAULT_PACE",
    )
    fallback_pace_seconds_per_km = sum(fallback_pace) / len(fallback_pace)
    presentation_weeks = build_presentation_weeks(model)
    selection = (
        WeekSelection.all()
        if getattr(arguments, "delete_all", False)
        and getattr(arguments, "select_weeks", None) is None
        and getattr(arguments, "weeks_ahead", None) is None
        else week_selection(arguments)
    )
    selected_weeks = selection.resolve(
        tuple(week.number for week in presentation_weeks),
        start_date=presentation_start(model),
        today=getattr(arguments, "today", None),
    )
    selected_items = [
        (week.number, item)
        for week in presentation_weeks
        if week.number in selected_weeks
        for item in week.workouts
    ]
    selections = []
    source_weeks = sorted({item.source_week for _, item in selected_items})
    for source_week in source_weeks:
        definition = load_definition(arguments.yaml_file, source_week)
        presented = {
            item.workout.id: (presentation_week, item)
            for presentation_week, item in selected_items
            if item.source_week == source_week
        }
        definition["workouts"] = [
            workout for workout in definition["workouts"] if workout["id"] in presented
        ]
        compiled = []
        for workout in definition["workouts"]:
            presentation_week, item = presented[workout["id"]]
            workout["presentation_week"] = presentation_week
            workout["presentation_name"] = item.name
            workout["base_description"] = workout.get("description")
            estimate = estimate_steps(item.workout.steps, fallback_pace_seconds_per_km)
            workout["estimated_duration_seconds"] = estimate.duration_seconds
            workout["estimated_distance_meters"] = estimate.distance_meters
            workout["estimated_distance_is_approximate"] = (
                estimate.distance_is_approximate
            )
            workout["name"] = garmin_workout_title(
                model.short_name,
                presentation_week,
                item.workout,
                fallback_pace_seconds_per_km,
                workout_name=item.name,
            )
            compiled.append((workout, build_workout(workout)))
        selections.append((definition, compiled))
    return selections


def run_preview(
    arguments: Namespace,
    selections: list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]],
) -> int:
    """Render a prepared multi-week dry-run using the selected formatter."""
    sync_plan = plan_program_weeks(
        JsonStateRepository(),
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
    owner_id: str = "local-default",
) -> int:
    """Execute additive Garmin synchronization for prepared weeks."""
    try:
        client = login_to_garmin()
        results = synchronize_program_weeks(
            client, JsonStateRepository(), selections, prune=prune, today=today,
            owner_id=owner_id,
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
    parser = argparse.ArgumentParser(
        prog="runplan",
        description="Validate, export, and sync YAML running programs.",
    )
    commands = parser.add_subparsers(dest="command", required=True)
    sync_parser = commands.add_parser(
        "sync", help="Sync program weeks with Garmin Connect"
    )
    sync_parser.add_argument("yaml_file", type=Path, help="Path to the program YAML file")
    sync_parser.add_argument("--dry-run", action="store_true")
    sync_parser.add_argument(
        "--output", choices=("overview", "json"), default="overview"
    )
    sync_parser.add_argument("--delete-all", action="store_true")
    sync_parser.add_argument("--prune", action="store_true")
    sync_parser.add_argument("--yes", action="store_true")
    sync_parser.add_argument(
        "--owner-id",
        default=os.getenv("RUNPLAN_OWNER_ID", "local-default"),
        help="Stable non-secret Runplan owner ID embedded in Garmin metadata",
    )
    add_week_selectors(sync_parser, allow_weeks_ahead=True)

    export_parser = commands.add_parser(
        "export", help="Render selected program weeks"
    )
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

    serve_parser = commands.add_parser(
        "serve", help="Run the local web frontend (no authentication)"
    )
    serve_parser.add_argument(
        "--host", default="127.0.0.1", help="Listen address (use 0.0.0.0 for remote access)"
    )
    serve_parser.add_argument("--port", type=int, default=8000, help="Listen port")
    serve_parser.add_argument(
        "--program-dir",
        type=Path,
        default=default_program_directory(),
        help="Directory containing editable YAML programs (default: RUNPLAN_PROGRAM_DIR or the user data directory)",
    )
    reconcile_parser = commands.add_parser(
        "reconcile", help="Refresh completed and missed workouts from Garmin"
    )
    reconcile_parser.add_argument(
        "yaml_file", type=Path, help="Path to the program YAML file"
    )
    rebuild_parser = commands.add_parser(
        "rebuild-state", help="Rebuild local sync state from Garmin metadata"
    )
    rebuild_parser.add_argument("yaml_file", type=Path, help="Path to the program YAML file")
    rebuild_parser.add_argument(
        "--owner-id", default=os.getenv("RUNPLAN_OWNER_ID", "local-default")
    )
    rebuild_parser.add_argument(
        "--yes", action="store_true", help="Apply the reviewed recovery result"
    )
    return parser


def parse_arguments(argv: Sequence[str] | None = None) -> Namespace:
    return build_parser().parse_args(argv)


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
        return run_sync(arguments)
    if arguments.command == "export":
        return run_export(arguments)
    if arguments.command == "serve":
        from .web import serve

        return serve(arguments.host, arguments.port, arguments.program_dir)
    if arguments.command == "reconcile":
        return run_reconcile(arguments)
    if arguments.command == "rebuild-state":
        return run_rebuild_state(arguments)
    return 2


def run_reconcile(arguments: Namespace) -> int:
    """Refresh lifecycle state without creating or pruning workouts."""
    try:
        program = load_definition_model(arguments.yaml_file)
        client = login_to_garmin()
        result = reconcile_program(client, JsonStateRepository(), program.id)
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


def run_rebuild_state(arguments: Namespace) -> int:
    """Preview or apply recovery of local sync state from Garmin."""
    try:
        selections = prepare_sync_selections(
            Namespace(
                yaml_file=arguments.yaml_file,
                select_weeks="all",
                weeks_ahead=None,
                delete_all=False,
                today=None,
            )
        )
        client = login_to_garmin()
        discovery = discover_sync_state(
            client, selections, owner_id=arguments.owner_id
        )
        public = {key: value for key, value in discovery.items() if key != "records"}
        print(json.dumps(public, ensure_ascii=False, indent=2))
        if arguments.yes:
            rebuild_sync_state(JsonStateRepository(), discovery)
            print(f"Rebuilt local state for {discovery['programId']}.")
        else:
            print("Preview only. Run again with --yes to rebuild local state.")
        return 0
    except (WorkoutDefinitionError, ValueError) as exc:
        print(f"Recovery failed: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"Recovery failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 99


__all__ = [
    "build_parser",
    "add_week_selectors",
    "main",
    "parse_arguments",
    "prepare_sync_selections",
    "run_export",
    "run_multi_week_sync",
    "run_preview",
    "run_reconcile",
    "run_rebuild_state",
    "run_sync",
    "week_selection",
]


if __name__ == "__main__":
    raise SystemExit(main())
