"""Synchronization command adapter."""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .application.sync import delete_all_managed
from .domain.errors import WorkoutDefinitionError
from .domain.selectors import WeekSelectionError
from .integrations.garmin.client import login_to_garmin
from .state.json_repository import load_state
from .state.yaml_repository import YamlStateRepository


def run_sync(args: argparse.Namespace) -> int:
    """Select and execute one focused synchronization workflow."""
    _ensure_repository(args)
    prepared = _prepare(args)
    if isinstance(prepared, int):
        return prepared
    definition, compiled, selections = prepared
    if getattr(args, "delete_all", False):
        return _run_delete_all(args, definition, compiled)
    if getattr(args, "prune", False):
        return _run_prune(args, selections)
    if args.dry_run:
        return _preview(args, selections)
    return _multi_week(args, selections)


def _ensure_repository(args: argparse.Namespace) -> None:
    if getattr(args, "repository", None) is None and getattr(args, "yaml_file", None):
        args.repository = YamlStateRepository(args.yaml_file)


def _prepare(args: argparse.Namespace) -> Any:
    try:
        from .cli import prepare_sync_selections

        selections = prepare_sync_selections(
            args, fallback_pace_value=getattr(args, "fallback_pace_value", None)
        )
        definition, compiled = selections[0]
        return definition, compiled, selections
    except WeekSelectionError as exc:
        print(f"Cannot select sync weeks: {exc}", file=sys.stderr)
        return 2
    except (WorkoutDefinitionError, ValueError) as exc:
        print(f"Invalid workout definition: {exc}", file=sys.stderr)
        return 2


def _preview(args: argparse.Namespace, selections: list[Any]) -> int:
    from .cli import run_preview

    return run_preview(args, selections)


def _run_prune(args: argparse.Namespace, selections: list[Any]) -> int:
    if args.dry_run:
        return _preview(args, selections)
    _preview(args, selections)
    confirmed = args.yes or input("Apply these prune changes? [y/N] ").strip().lower() in (
        "y",
        "yes",
    )
    if not confirmed:
        print("Sync cancelled; Garmin was not changed.")
        return 0
    return _multi_week(args, selections, prune=True)


def _multi_week(args: argparse.Namespace, selections: list[Any], *, prune: bool = False) -> int:
    from .cli import run_multi_week_sync

    return run_multi_week_sync(
        selections,
        prune=prune,
        today=getattr(args, "today", None),
        repository=getattr(args, "repository", None),
        credentials_file=getattr(args, "credentials_file", None),
        token_store=getattr(args, "token_store", None),
    )


def _run_delete_all(
    args: argparse.Namespace, definition: dict[str, Any], compiled: list[Any]
) -> int:
    tracked = _tracked_records(args, definition["program_id"])
    if args.dry_run:
        _print_delete_preview(args, definition["program_id"], tracked)
        return 0
    if not args.yes:
        print(
            "Safety stop: --delete-all also requires --yes.\nReview it first with --delete-all --dry-run.",
            file=sys.stderr,
        )
        return 2
    try:
        client = login_to_garmin(
            credentials_file=getattr(args, "credentials_file", None),
            token_store=getattr(args, "token_store", None),
        )
        deleted = delete_all_managed(
            client, definition, compiled, repository=getattr(args, "repository", None)
        )
        print(f"\nCleanup complete: {deleted} workouts processed.")
        return 0
    except GarminConnectAuthenticationError as exc:
        print(f"Garmin login failed: {exc}", file=sys.stderr)
        return 10
    except GarminConnectTooManyRequestsError as exc:
        print(f"Garmin is temporarily rejecting more requests: {exc}", file=sys.stderr)
        return 11
    except GarminConnectConnectionError as exc:
        print(f"Garmin Connect error: {exc}", file=sys.stderr)
        return 12
    except Exception as exc:
        print(f"Unexpected error: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 99


def _tracked_records(args: argparse.Namespace, program_id: str) -> list[dict[str, Any]]:
    repository = getattr(args, "repository", None)
    state = repository.load(program_id) if repository is not None else load_state(program_id)
    return [
        record
        for record in state["workouts"].values()
        if record.get("status") not in ("completed", "missed", "retired")
    ]


def _print_delete_preview(
    args: argparse.Namespace, program_id: str, tracked: list[dict[str, Any]]
) -> None:
    if args.output == "json":
        print(
            json.dumps(
                {"programId": program_id, "action": "delete-all", "trackedWorkouts": tracked},
                ensure_ascii=False,
                indent=2,
            )
        )
        return
    print(f"Program: {program_id}")
    print("Action: Delete all managed workouts")
    if tracked:
        print(f"\nRegistered for deletion: {len(tracked)}")
        for record in tracked:
            print(
                f"  - {record.get('name', 'Unknown workout')} ({record.get('date', 'unknown date')})"
            )
    else:
        print("\nNo workouts are registered in local state.")
        print("A real run also checks exact matches from the selected week in Garmin.")
    print("\nDry run: No data was deleted.")


__all__ = ["run_sync"]
