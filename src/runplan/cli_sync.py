"""Synchronization command adapter."""

from __future__ import annotations

import argparse
import json
import sys

from garminconnect.exceptions import (
    GarminConnectAuthenticationError,
    GarminConnectConnectionError,
    GarminConnectTooManyRequestsError,
)

from .application.sync import delete_all_managed, sync_program_week
from .domain.errors import WorkoutDefinitionError
from .domain.selectors import WeekSelectionError
from .integrations.garmin.client import login_to_garmin
from .presentation.text import format_step_overview, format_totals, format_weekday
from .state.json_repository import load_state
from .state.yaml_repository import YamlStateRepository


def run_sync(args: argparse.Namespace) -> int:
    if getattr(args, "repository", None) is None and getattr(args, "yaml_file", None):
        args.repository = YamlStateRepository(args.yaml_file)
    try:
        from .cli import prepare_sync_selections

        compiled_selections = prepare_sync_selections(
            args, fallback_pace_value=getattr(args, "fallback_pace_value", None)
        )
        catalog_values = vars(args).copy()
        catalog_values.update(select_weeks="all", weeks_ahead=None, delete_all=False)
        active_plan_selections = prepare_sync_selections(
            argparse.Namespace(**catalog_values),
            fallback_pace_value=getattr(args, "fallback_pace_value", None),
        )
        definition, compiled = compiled_selections[0]
    except WeekSelectionError as exc:
        print(f"Cannot select sync weeks: {exc}", file=sys.stderr)
        return 2
    except (WorkoutDefinitionError, ValueError) as exc:
        print(f"Invalid workout definition: {exc}", file=sys.stderr)
        return 2

    if "workouts" in definition:
        if getattr(args, "prune", False) and not args.dry_run:
            from .cli import run_preview

            run_preview(args, compiled_selections)
            confirmed = args.yes or input(
                "Apply these prune changes? [y/N] "
            ).strip().lower() in ("y", "yes")
            if not confirmed:
                print("Sync cancelled; Garmin was not changed.")
                return 0
        if getattr(args, "prune", False) and args.dry_run and not args.delete_all:
            from .cli import run_preview

            return run_preview(args, compiled_selections)
        if getattr(args, "prune", False):
            from .cli import run_multi_week_sync

            return run_multi_week_sync(
                compiled_selections,
                active_plan_selections=active_plan_selections,
                prune=True,
                today=getattr(args, "today", None),
                owner_id=getattr(args, "owner_id", "local-default"),
                repository=getattr(args, "repository", None),
                credentials_file=getattr(args, "credentials_file", None),
                token_store=getattr(args, "token_store", None),
            )
        if args.dry_run and not args.delete_all:
            from .cli import run_preview

            return run_preview(args, compiled_selections)
        if not args.delete_all:
            from .cli import run_multi_week_sync

            return run_multi_week_sync(
                compiled_selections,
                active_plan_selections=active_plan_selections,
                today=getattr(args, "today", None),
                owner_id=getattr(args, "owner_id", "local-default"),
                repository=getattr(args, "repository", None),
                credentials_file=getattr(args, "credentials_file", None),
                token_store=getattr(args, "token_store", None),
            )
        if args.delete_all:
            repository = getattr(args, "repository", None)
            state = (
                repository.load(definition["program_id"])
                if repository is not None
                else load_state(definition["program_id"])
            )
            tracked = [
                record
                for record in state["workouts"].values()
                if record.get("status") not in ("completed", "missed", "retired")
            ]
            if args.dry_run:
                if args.output == "json":
                    print(
                        json.dumps(
                            {
                                "programId": definition["program_id"],
                                "action": "delete-all",
                                "trackedWorkouts": tracked,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                else:
                    print(f"Program: {definition['program_id']}")
                    print("Action: Delete all managed workouts")
                    if tracked:
                        print(f"\nRegistered for deletion: {len(tracked)}")
                        for record in tracked:
                            print(
                                f"  - {record.get('name', 'Unknown workout')} "
                                f"({record.get('date', 'unknown date')})"
                            )
                    else:
                        print("\nNo workouts are registered in local state.")
                        print(
                            "A real run also checks exact matches from the "
                            "selected week in Garmin."
                        )
                    print("\nDry run: No data was deleted.")
                return 0

            if not args.yes:
                print(
                    "Safety stop: --delete-all also requires --yes.\n"
                    "Review it first with --delete-all --dry-run.",
                    file=sys.stderr,
                )
                return 2
            try:
                client = login_to_garmin(
                    credentials_file=getattr(args, "credentials_file", None),
                    token_store=getattr(args, "token_store", None),
                )
                deleted = delete_all_managed(
                    client, definition, compiled,
                    repository=getattr(args, "repository", None),
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
        if args.dry_run and args.output == "json":
            output = {
                "programId": definition["program_id"],
                "week": definition["week"],
                "workouts": [
                    {
                        "id": item["id"],
                        "date": item["schedule_date"],
                        "payload": item_workout.to_dict(),
                    }
                    for item, item_workout in compiled
                ],
            }
            print(json.dumps(output, ensure_ascii=False, indent=2))
            return 0

        dates = [item["schedule_date"] for item, _ in compiled]
        print(f"Program: {definition['program_id']}")
        print(f"Week: {definition['week']} ({min(dates)} to {max(dates)})")
        print(f"Workouts: {len(compiled)}")
        for item, item_workout in compiled:
            print(
                f"\n{format_weekday(item['schedule_date'])} · "
                f"{item_workout.workoutName} "
                f"· {format_totals(item['steps'])}"
            )
            print(format_step_overview(item["steps"]))

        if args.dry_run:
            state = load_state(definition["program_id"])
            current_keys = {
                f"week-{definition['week']:02d}/{item['id']}"
                for item, _ in compiled
            }
            obsolete = [
                record
                for key, record in state["workouts"].items()
                if key not in current_keys
            ]
            print("\nSync changes:")
            print(f"  Create or reuse: {len(compiled)} workouts")
            if obsolete:
                print(f"  Remove: {len(obsolete)} previous workouts and schedules")
                for record in obsolete:
                    print(f"    - {record.get('name', 'Unknown workout')} ({record.get('date', 'unknown date')})")
            else:
                print("  Remove: no registered workouts")
            print("\nDry run: No data was uploaded or deleted.")
            return 0

        try:
            client = login_to_garmin()
            sync_program_week(client, definition, compiled)
            print("Sync Garmin Connect with the watch to transfer the workouts.")
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


__all__ = ["run_sync"]
