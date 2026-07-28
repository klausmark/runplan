"""Garmin synchronization use cases and CLI compatibility rendering."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from typing import Any

from .ports import GarminClient, StateRepository
from .results import ReconcileResult, SyncAction, SyncPlan, SyncResult
from ..integrations.garmin.client import get_all_workouts, scheduled_items_for_dates
from ..state.json_repository import JsonStateRepository


_CONTENT_FIELDS = (
    "workoutName",
    "description",
    "estimatedDurationInSecs",
    "workoutSegments",
)

_TERMINAL_STATUSES = {"completed", "missed", "retired"}
_CLEANUP_STATUSES = {"completed", "missed"}


def _schedule_for_record(
    scheduled: list[dict[str, Any]], record: dict[str, Any]
) -> dict[str, Any] | None:
    """Find the Garmin calendar occurrence belonging to a tracked workout."""
    schedule_id = record.get("schedule_id")
    if schedule_id:
        match = next(
            (
                item
                for item in scheduled
                if item.get("workoutScheduleId", item.get("id")) == schedule_id
            ),
            None,
        )
        if match is not None:
            return match
    return next(
        (
            item
            for item in scheduled
            if item.get("workoutId") == record.get("workout_id")
            and item.get("date") == record.get("date")
        ),
        None,
    )


def reconcile_program(
    client: GarminClient,
    repository: StateRepository,
    program_id: str,
    *,
    today: date | None = None,
) -> ReconcileResult:
    """Update tracked historical workouts from Garmin calendar associations."""
    reference_date = today or date.today()
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    historical_dates = {
        record["date"]
        for record in records.values()
        if isinstance(record, dict)
        and isinstance(record.get("date"), str)
        and record["date"] < reference_date.isoformat()
        and record.get("status") not in _TERMINAL_STATUSES
    }
    scheduled = (
        scheduled_items_for_dates(client, historical_dates)
        if historical_dates
        else []
    )
    result = ReconcileResult(program_id)
    changed = False
    for record in records.values():
        if (
            not isinstance(record, dict)
            or record.get("date") not in historical_dates
        ):
            continue
        occurrence = _schedule_for_record(scheduled, record)
        activity_id = occurrence.get("associatedActivityId") if occurrence else None
        if activity_id is not None:
            record["status"] = "completed"
            record["activity_id"] = activity_id
            completed_at = occurrence.get("associatedActivityDateTime")
            if completed_at:
                record["completed_at"] = completed_at
            record["actual_distance_meters"] = occurrence["actualDistanceMeters"]
            record["actual_duration_seconds"] = occurrence["actualDurationSeconds"]
            record.pop("content_hash", None)
            record.pop("description", None)
            result.add(
                "completed",
                record.get("name", "Unknown workout"),
                workout_id=record.get("workout_id"),
                schedule_id=record.get("schedule_id"),
                date=record.get("date"),
                activity_id=activity_id,
                completed_at=completed_at,
                actual_distance_meters=record["actual_distance_meters"],
                actual_duration_seconds=record["actual_duration_seconds"],
            )
        else:
            record["status"] = "missed"
            result.add(
                "missed",
                record.get("name", "Unknown workout"),
                workout_id=record.get("workout_id"),
                schedule_id=record.get("schedule_id"),
                date=record.get("date"),
            )
        changed = True
    if changed:
        repository.save(program_id, state)
    return result


def reconcile_selected_program(
    client: GarminClient,
    repository: StateRepository,
    selections: list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]],
    *,
    today: date | None = None,
) -> ReconcileResult:
    """Reconcile Garmin calendar evidence for every selected plan occurrence."""
    _validate_selections(selections)
    reference_date = today or date.today()
    program_id = selections[0][0]["program_id"]
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    selected = [
        (program["week"], definition)
        for program, compiled in selections
        for definition, _ in compiled
    ]
    dates = {definition["schedule_date"] for _, definition in selected}
    scheduled = scheduled_items_for_dates(client, dates) if dates else []
    result = ReconcileResult(program_id)
    changed = False
    for week, definition in selected:
        key = f"week-{week:02d}/{definition['id']}"
        record = records.get(key)
        occurrence = _schedule_for_record(scheduled, record) if isinstance(record, dict) else None
        activity_id = occurrence.get("associatedActivityId") if occurrence else None
        if activity_id is not None:
            if isinstance(record, dict) and record.get("status") == "completed":
                continue
            completed_at = occurrence.get("associatedActivityDateTime")
            completed = {
                "week": week,
                "date": definition["schedule_date"],
                "name": definition["name"],
                "status": "completed",
                "activity_id": activity_id,
            }
            workout_id = occurrence.get("workoutId")
            schedule_id = occurrence.get("workoutScheduleId", occurrence.get("id"))
            if workout_id is not None:
                completed["workout_id"] = workout_id
            if schedule_id is not None:
                completed["schedule_id"] = schedule_id
            if completed_at:
                completed["completed_at"] = completed_at
            completed["actual_distance_meters"] = occurrence["actualDistanceMeters"]
            completed["actual_duration_seconds"] = occurrence["actualDurationSeconds"]
            records[key] = completed
            result.add(
                "completed",
                definition["name"],
                workout_id=workout_id,
                schedule_id=schedule_id,
                date=definition["schedule_date"],
                activity_id=activity_id,
                completed_at=completed_at,
                actual_distance_meters=completed["actual_distance_meters"],
                actual_duration_seconds=completed["actual_duration_seconds"],
            )
            changed = True
        elif (
            definition["schedule_date"] < reference_date.isoformat()
            and isinstance(record, dict)
            and record.get("status") not in _TERMINAL_STATUSES
        ):
            record["status"] = "missed"
            result.add(
                "missed",
                record.get("name", definition["name"]),
                workout_id=record.get("workout_id"),
                schedule_id=record.get("schedule_id"),
                date=definition["schedule_date"],
            )
            changed = True
    if changed:
        repository.save(program_id, state)
    return result


def _is_prunable(record: Any, reference_date: date) -> bool:
    """Return whether prune may remove this future active record."""
    return (
        isinstance(record, dict)
        and record.get("status") not in _TERMINAL_STATUSES
        and isinstance(record.get("date"), str)
        and record["date"] >= reference_date.isoformat()
    )


def _validate_selections(
    selections: list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]],
) -> None:
    """Reject ambiguous batches before state or Garmin can be mutated."""
    if not selections:
        raise ValueError("sync requires at least one selected week")
    program_ids = {program.get("program_id") for program, _ in selections}
    if len(program_ids) != 1:
        raise ValueError("sync selections must belong to one program")
    weeks = [program.get("week") for program, _ in selections]
    if len(weeks) != len(set(weeks)):
        raise ValueError("sync selections contain overlapping weeks")
    empty = [program.get("week") for program, compiled in selections if not compiled]
    if empty:
        raise ValueError(f"selected weeks contain no workouts: {empty}")


def _workout_payload(workout: Any) -> dict[str, Any]:
    payload = workout.to_dict()
    return {field: payload.get(field) for field in _CONTENT_FIELDS}


def _content_hash(payload: dict[str, Any]) -> str:
    canonical = {field: payload.get(field) for field in _CONTENT_FIELDS}
    encoded = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def workout_content_hash(workout: Any) -> str:
    """Return the canonical sync hash for a compiled Garmin workout."""
    return _content_hash(_workout_payload(workout))


def plan_program_weeks(
    repository: StateRepository,
    selections: list[
        tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]
    ],
    *,
    prune: bool = False,
    today: date | None = None,
) -> SyncPlan:
    """Build an offline sync diff without mutating state or Garmin."""
    _validate_selections(selections)
    program_id = selections[0][0]["program_id"]
    weeks = tuple(program["week"] for program, _ in selections)
    plan = SyncPlan(program_id=program_id, weeks=weeks)
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    desired_keys: set[str] = set()
    reference_date = today or date.today()

    for program, compiled in selections:
        week = program["week"]
        for definition, workout in compiled:
            key = f"week-{week:02d}/{definition['id']}"
            desired_keys.add(key)
            record = records.get(key)
            desired_hash = workout_content_hash(workout)
            if record is None and definition["schedule_date"] < reference_date.isoformat():
                plan.add("missed", definition["name"], date=definition["schedule_date"])
            elif record is None:
                plan.add("create", definition["name"])
                plan.add("schedule", definition["name"], date=definition["schedule_date"])
            elif record.get("status") in _TERMINAL_STATUSES:
                plan.add(
                    record["status"],
                    record.get("name", definition["name"]),
                    workout_id=record.get("workout_id"),
                    schedule_id=record.get("schedule_id"),
                    date=record.get("date"),
                    activity_id=record.get("activity_id"),
                    completed_at=record.get("completed_at"),
                )
            elif record.get("content_hash") != desired_hash:
                plan.add("update", definition["name"], workout_id=record.get("workout_id"))
                plan.add("schedule", definition["name"], date=definition["schedule_date"])
            else:
                plan.add("reuse", definition["name"], workout_id=record.get("workout_id"))
                if not record.get("schedule_id") or record.get("date") != definition["schedule_date"]:
                    plan.add("schedule", definition["name"], date=definition["schedule_date"])
                    if (
                        record.get("schedule_id")
                        and record.get("date") != definition["schedule_date"]
                    ):
                        plan.add(
                            "unschedule",
                            definition["name"],
                            workout_id=record.get("workout_id"),
                            schedule_id=record["schedule_id"],
                            date=record.get("date"),
                        )

    for key, record in sorted(records.items()):
        if not isinstance(record, dict) or record.get("status") not in _CLEANUP_STATUSES:
            continue
        name = record.get("name", key)
        if record.get("schedule_id"):
            plan.add(
                "unschedule",
                name,
                workout_id=record.get("workout_id"),
                schedule_id=record["schedule_id"],
                date=record.get("date"),
            )
        if record.get("workout_id"):
            plan.add("delete", name, workout_id=record["workout_id"])

    if prune:
        for key in sorted(set(records) - desired_keys):
            record = records[key]
            if not _is_prunable(record, reference_date):
                continue
            name = record.get("name", key)
            if record.get("schedule_id"):
                plan.add(
                    "unschedule",
                    name,
                    workout_id=record.get("workout_id"),
                    schedule_id=record["schedule_id"],
                    date=record.get("date"),
                )
            if record.get("workout_id"):
                plan.add("delete", name, workout_id=record["workout_id"])
    return plan


def _remote_has_content(remote: dict[str, Any]) -> bool:
    return "workoutSegments" in remote and "estimatedDurationInSecs" in remote


def _is_owned(remote: dict[str, Any], record: dict[str, Any]) -> bool:
    """Treat a remote object as owned only when its ID is tracked locally."""
    workout_id = record.get("workout_id")
    return workout_id is not None and remote.get("workoutId") == workout_id


def cleanup_terminal_workouts(
    client: GarminClient,
    repository: StateRepository,
    program_id: str,
) -> list[SyncAction]:
    """Remove Garmin schedules/templates while retaining local terminal history."""
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    terminal = [
        (key, record)
        for key, record in sorted(records.items())
        if isinstance(record, dict)
        and record.get("status") in _CLEANUP_STATUSES
        and (record.get("schedule_id") or record.get("workout_id"))
    ]
    if not terminal:
        return []
    remote_workouts = get_all_workouts(client)
    dates = {
        record["date"]
        for _, record in terminal
        if isinstance(record.get("date"), str)
    }
    scheduled = scheduled_items_for_dates(client, dates) if dates else []
    remote_by_id = {
        item.get("workoutId"): item
        for item in remote_workouts
        if item.get("workoutId") is not None
    }

    # Verify every extant template before making the first destructive call.
    for _, record in terminal:
        remote = remote_by_id.get(record.get("workout_id"))
        if remote is not None and not _is_owned(remote, record):
            raise RuntimeError(
                f"Safety stop: workoutId={record.get('workout_id')} "
                "does not belong to the program"
            )

    actions: list[SyncAction] = []
    for key, record in terminal:
        name = record.get("name", key)
        workout_id = record.get("workout_id")
        occurrence = _schedule_for_record(scheduled, record)
        schedule_id = (
            occurrence.get("workoutScheduleId", occurrence.get("id"))
            if occurrence is not None
            else None
        )
        if schedule_id is not None:
            client.unschedule_workout(schedule_id)
            actions.append(
                SyncAction(
                    "unschedule",
                    name,
                    workout_id=workout_id,
                    schedule_id=schedule_id,
                    date=record.get("date"),
                )
            )
        if record.pop("schedule_id", None) is not None:
            repository.save(program_id, state)

        remote = remote_by_id.get(workout_id)
        if workout_id is not None and remote is not None:
            client.delete_workout(workout_id)
            actions.append(SyncAction("delete", name, workout_id=workout_id))
        changed = False
        for field in ("workout_id", "content_hash", "description"):
            if record.pop(field, None) is not None:
                changed = True
        if changed:
            repository.save(program_id, state)
    return actions


def synchronize_program_week(
    client: GarminClient,
    repository: StateRepository,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
    *,
    prune: bool = False,
    today: date | None = None,
) -> SyncResult:
    """Synchronize one week and return actions without performing terminal I/O."""
    if not compiled:
        raise ValueError("sync requires at least one workout")
    program_id = program["program_id"]
    week = program["week"]
    reference_date = today or date.today()
    result = SyncResult(program_id=program_id, week=week)
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    current_keys = {
        f"week-{week:02d}/{definition['id']}" for definition, _ in compiled
    }
    relevant_dates = {
        definition["schedule_date"] for definition, _ in compiled
    } | {
        record["date"]
        for record in records.values()
        if isinstance(record, dict) and isinstance(record.get("date"), str)
    }
    remote_workouts = get_all_workouts(client)
    scheduled = scheduled_items_for_dates(client, relevant_dates)
    replaced_records: list[tuple[str, dict[str, Any]]] = []

    # Complete and persist the new week before deleting any previous content.
    for definition, workout in compiled:
        key = f"week-{week:02d}/{definition['id']}"
        desired_hash = workout_content_hash(workout)
        payload = _workout_payload(workout)
        previous = records.get(key)
        if previous is None and definition["schedule_date"] < reference_date.isoformat():
            records[key] = {
                "week": week,
                "date": definition["schedule_date"],
                "name": definition["name"],
                "status": "missed",
            }
            repository.save(program_id, state)
            result.add("missed", definition["name"], date=definition["schedule_date"])
            continue
        if previous and previous.get("status") in _TERMINAL_STATUSES:
            result.add(
                previous["status"],
                previous.get("name", definition["name"]),
                workout_id=previous.get("workout_id"),
                schedule_id=previous.get("schedule_id"),
                date=previous.get("date"),
                activity_id=previous.get("activity_id"),
                completed_at=previous.get("completed_at"),
                actual_distance_meters=previous.get("actual_distance_meters"),
                actual_duration_seconds=previous.get("actual_duration_seconds"),
            )
            continue
        tracked_id = previous.get("workout_id") if isinstance(previous, dict) else None
        matching = next(
            (item for item in remote_workouts if item.get("workoutId") == tracked_id),
            None,
        ) if tracked_id is not None else None
        reusable = bool(
            matching is not None
            and matching.get("workoutName") == payload.get("workoutName")
            and matching.get("description") == payload.get("description")
            and previous
            and previous.get("content_hash") == desired_hash
        )
        if matching is not None and _remote_has_content(matching):
            reusable = reusable and _content_hash(matching) == desired_hash

        if not reusable:
            replaced = previous
            uploaded = client.upload_running_workout(workout)
            workout_id = uploaded.get("workoutId")
            if not workout_id:
                raise RuntimeError(
                    f"Upload of {definition['name']!r} did not return workoutId"
                )
            remote = {**payload, **uploaded}
            remote_workouts.append(remote)
            result.add("create", definition["name"], workout_id=workout_id)
            if replaced:
                replaced_records.append((key, replaced.copy()))
        else:
            workout_id = matching.get("workoutId")
            if not workout_id:
                raise RuntimeError(
                    f"Existing workout {definition['name']!r} has no workoutId"
                )
            result.add("reuse", definition["name"], workout_id=workout_id)

        schedule = next(
            (
                item
                for item in scheduled
                if item.get("workoutId") == workout_id
                and item.get("date") == definition["schedule_date"]
            ),
            None,
        )
        if schedule is None:
            schedule = client.schedule_workout(workout_id, definition["schedule_date"])
            result.add(
                "schedule",
                definition["name"],
                workout_id=workout_id,
                date=definition["schedule_date"],
            )
        else:
            result.add(
                "already_scheduled",
                definition["name"],
                workout_id=workout_id,
                date=definition["schedule_date"],
            )
        schedule_id = schedule.get("workoutScheduleId", schedule.get("id"))
        if not schedule_id:
            raise RuntimeError(
                f"Scheduling {definition['name']!r} did not return a schedule ID"
            )
        if (
            previous
            and previous.get("schedule_id")
            and previous["schedule_id"] != schedule_id
            and not any(replaced_key == key for replaced_key, _ in replaced_records)
        ):
            client.unschedule_workout(previous["schedule_id"])
            result.add(
                "unschedule",
                definition["name"],
                workout_id=previous.get("workout_id"),
                schedule_id=previous["schedule_id"],
                date=previous.get("date"),
            )
        records[key] = {
            "week": week,
            "workout_id": workout_id,
            "schedule_id": schedule_id,
            "date": definition["schedule_date"],
            "name": definition["name"],
            "description": payload.get("description"),
            "content_hash": desired_hash,
            "status": "scheduled",
        }
        state["active_week"] = week
        repository.save(program_id, state)

    obsolete_records = (
        [
            (key, records[key])
            for key in sorted(set(records) - current_keys)
            if _is_prunable(records[key], date.today())
        ]
        if prune
        else []
    )
    cleanup = obsolete_records + replaced_records
    for key, record in cleanup:
        workout_id = record.get("workout_id")
        remote = next(
            (item for item in remote_workouts if item.get("workoutId") == workout_id),
            None,
        )
        schedule_id = record.get("schedule_id")
        if schedule_id:
            client.unschedule_workout(schedule_id)
            result.add(
                "unschedule",
                record.get("name", key),
                workout_id=workout_id,
                schedule_id=schedule_id,
            )
        if workout_id and remote is not None:
            client.delete_workout(workout_id)
            result.add("delete", record.get("name", key), workout_id=workout_id)
        if records.get(key) is record:
            del records[key]
        repository.save(program_id, state)
    return result


def synchronize_program_weeks(
    client: GarminClient,
    repository: StateRepository,
    selections: list[
        tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]
    ],
    *,
    prune: bool = False,
    today: date | None = None,
) -> list[SyncResult]:
    """Synchronize selected weeks additively without pruning other weeks."""
    _validate_selections(selections)
    program_id = selections[0][0]["program_id"]
    reconciled = reconcile_program(client, repository, program_id, today=today)
    selected_reconciled = reconcile_selected_program(
        client,
        repository,
        selections,
        today=today,
    )
    cleanup_actions = cleanup_terminal_workouts(client, repository, program_id)
    results: list[SyncResult] = []
    for program, compiled in selections:
        results.append(
            synchronize_program_week(
                client,
                repository,
                program,
                compiled,
                prune=False,
                today=today,
            )
        )
    if results:
        reported = {
            (action.kind, action.name, action.date, action.activity_id)
            for result in results
            for action in result.actions
        }
        reconciliation_actions: list[SyncAction] = []
        for action in reconciled.actions + selected_reconciled.actions + cleanup_actions:
            identity = (action.kind, action.name, action.date, action.activity_id)
            if identity not in reported:
                reconciliation_actions.append(action)
                reported.add(identity)
        results[0].actions[0:0] = reconciliation_actions
    if prune:
        reference_date = today or date.today()
        desired_keys = {
            f"week-{program['week']:02d}/{definition['id']}"
            for program, compiled in selections
            for definition, _ in compiled
        }
        state = repository.load(program_id)
        records: dict[str, Any] = state["workouts"]
        remote_workouts = get_all_workouts(client)
        for key in sorted(set(records) - desired_keys):
            record = records[key]
            if not _is_prunable(record, reference_date):
                continue
            workout_id = record.get("workout_id")
            remote = next(
                (item for item in remote_workouts if item.get("workoutId") == workout_id),
                None,
            )
            if remote is not None and not _is_owned(remote, record):
                raise RuntimeError(
                    f"Safety stop: workoutId={workout_id} does not belong to the program"
                )
            name = record.get("name", key)
            schedule_id = record.get("schedule_id")
            if schedule_id:
                client.unschedule_workout(schedule_id)
                results[-1].add(
                    "unschedule", name, workout_id=workout_id, schedule_id=schedule_id
                )
            if workout_id and remote is not None:
                client.delete_workout(workout_id)
                results[-1].add("delete", name, workout_id=workout_id)
            del records[key]
            repository.save(program_id, state)
    return results


def delete_managed_workouts(
    client: GarminClient,
    repository: StateRepository,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
) -> tuple[int, list[SyncAction]]:
    """Delete all verified workouts owned by a program."""
    program_id = program["program_id"]
    actions = cleanup_terminal_workouts(client, repository, program_id)
    state = repository.load(program_id)
    records: dict[str, Any] = state["workouts"]
    remote_workouts = get_all_workouts(client)
    dates = {
        record["date"]
        for record in records.values()
        if isinstance(record, dict) and isinstance(record.get("date"), str)
    }
    scheduled = scheduled_items_for_dates(client, dates) if dates else []
    deleted = 0
    for key in sorted(list(records)):
        record = records[key]
        if record.get("status") in _TERMINAL_STATUSES:
            continue
        workout_id = record.get("workout_id")
        remote = next(
            (item for item in remote_workouts if item.get("workoutId") == workout_id),
            None,
        )
        schedule_id = record.get("schedule_id")
        if not schedule_id:
            schedule = next(
                (
                    item
                    for item in scheduled
                    if item.get("workoutId") == workout_id
                    and item.get("date") == record.get("date")
                ),
                None,
            )
            if schedule is not None:
                schedule_id = schedule.get("workoutScheduleId", schedule.get("id"))
        name = record.get("name", key)
        if schedule_id:
            client.unschedule_workout(schedule_id)
            actions.append(
                SyncAction("unschedule", name, workout_id, schedule_id=schedule_id)
            )
        if workout_id and remote is not None:
            client.delete_workout(workout_id)
            actions.append(SyncAction("delete", name, workout_id))
        del records[key]
        deleted += 1
        repository.save(program_id, state)
    if not records:
        repository.delete(program_id)
    return deleted, actions


def _print_actions(actions: list[SyncAction]) -> None:
    for action in actions:
        if action.kind == "create":
            print(f"Created: {action.name} (workoutId={action.workout_id}).")
        elif action.kind == "reuse":
            print(f"Reused: {action.name} (workoutId={action.workout_id}).")
        elif action.kind == "schedule":
            print(f"Scheduled for {action.date}.")
        elif action.kind == "already_scheduled":
            print(f"Already scheduled for {action.date}.")
        elif action.kind == "unschedule":
            print(f"Removed schedule: {action.name}.")
        elif action.kind == "delete":
            print(f"Deleted workout: {action.name}.")
        elif action.kind == "completed":
            print(f"Completed: {action.name} ({action.date}).")
        elif action.kind == "missed":
            print(f"Missed: {action.name} ({action.date}).")
        elif action.kind == "retired":
            print(f"Retired: {action.name}.")


def sync_program_week(
    client: GarminClient,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
) -> None:
    """CLI-compatible wrapper around the output-free synchronization use case."""
    result = synchronize_program_week(
        client, JsonStateRepository(), program, compiled, prune=False
    )
    _print_actions(result.actions)
    print(f"\nWeek {result.week} was synced with Garmin Connect.")


def delete_all_managed(
    client: GarminClient,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
    *,
    repository: StateRepository | None = None,
) -> int:
    """CLI-compatible wrapper for deleting program-owned Garmin workouts."""
    deleted, actions = delete_managed_workouts(
        client, repository or JsonStateRepository(), program, compiled
    )
    _print_actions(actions)
    return deleted


__all__ = [
    "cleanup_terminal_workouts",
    "delete_all_managed",
    "delete_managed_workouts",
    "plan_program_weeks",
    "reconcile_program",
    "reconcile_selected_program",
    "sync_program_week",
    "synchronize_program_week",
    "synchronize_program_weeks",
    "workout_content_hash",
]
