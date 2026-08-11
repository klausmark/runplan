"""Execute the transactional synchronization workflow for one program week."""

from __future__ import annotations

import logging
from datetime import date
from typing import Any

from ..integrations.garmin.client import get_all_workouts, scheduled_items_for_dates
from .ports import GarminClient, StateRepository
from .results import SyncResult
from .sync_matching import resolve_workout
from .sync_scheduling import ensure_schedule, remove_superseded_schedule
from .sync_support import (
    TERMINAL_STATUSES,
    ignore_garmin_not_found,
    is_prunable,
    workout_content_hash,
    workout_payload,
)

logger = logging.getLogger("runplan.application.sync")


class WeekSynchronizer:
    """Synchronize and checkpoint exactly one selected program week.

    Structural rationale: the object keeps the mutable transaction context together while
    focused methods implement matching, scheduling, persistence, and cleanup steps.
    """

    def __init__(
        self,
        client: GarminClient,
        repository: StateRepository,
        program: dict[str, Any],
        compiled: list[tuple[dict[str, Any], Any]],
        *,
        prune: bool,
        today: date | None,
    ) -> None:
        if not compiled:
            raise ValueError("sync requires at least one workout")
        self.client = client
        self.repository = repository
        self.program_id = program["program_id"]
        self.week = program["week"]
        self.compiled = compiled
        self.prune = prune
        self.reference_date = today or date.today()
        self.result = SyncResult(self.program_id, self.week)
        self.state = repository.load(self.program_id)
        self.records: dict[str, Any] = self.state["workouts"]
        relevant_dates = {definition["schedule_date"] for definition, _ in compiled} | {
            record["date"]
            for record in self.records.values()
            if isinstance(record, dict) and isinstance(record.get("date"), str)
        }
        self.remote_workouts = get_all_workouts(client)
        self.scheduled = scheduled_items_for_dates(client, relevant_dates)
        self.replaced_records: list[tuple[str, dict[str, Any]]] = []

    def run(self) -> SyncResult:
        """Complete desired workouts before removing replaced or obsolete records."""
        for definition, workout in self.compiled:
            self._synchronize_workout(definition, workout)
        self._cleanup_replaced_and_obsolete()
        return self.result

    def _synchronize_workout(self, definition: dict[str, Any], workout: Any) -> None:
        """Synchronize and checkpoint one desired workout occurrence.

        Structural rationale: matching and scheduling are delegated; this method keeps
        their required transaction order and final checkpoint explicit.
        """
        key = f"week-{self.week:02d}/{definition['id']}"
        previous = self.records.get(key)
        if previous is None and definition["schedule_date"] < self.reference_date.isoformat():
            self._record_missed(key, definition)
            return
        if previous and previous.get("status") in TERMINAL_STATUSES:
            self._report_terminal(previous, definition)
            return

        desired_hash = workout_content_hash(workout)
        payload = workout_payload(workout)
        resolution = resolve_workout(
            self.client,
            self.remote_workouts,
            self.result,
            self.program_id,
            key,
            definition,
            workout,
            previous,
            payload,
            desired_hash,
        )
        if resolution.replaced:
            self.replaced_records.append((key, resolution.replaced))
        schedule_id = ensure_schedule(
            self.client,
            self.scheduled,
            self.result,
            self.program_id,
            definition,
            previous,
            resolution.workout_id,
            reused=resolution.replaced is None,
        )
        remove_superseded_schedule(
            self.client,
            self.result,
            definition,
            previous,
            resolution.workout_id,
            schedule_id,
            workout_replaced=resolution.replaced is not None,
        )
        self._checkpoint(
            key,
            definition,
            payload,
            desired_hash,
            resolution.workout_id,
            schedule_id,
        )

    def _record_missed(self, key: str, definition: dict[str, Any]) -> None:
        self.records[key] = {
            "week": self.week,
            "date": definition["schedule_date"],
            "name": definition["name"],
            "status": "missed",
        }
        self.repository.save(self.program_id, self.state)
        self.result.add("missed", definition["name"], date=definition["schedule_date"])

    def _report_terminal(self, previous: dict[str, Any], definition: dict[str, Any]) -> None:
        self.result.add(
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

    def _checkpoint(
        self,
        key: str,
        definition: dict[str, Any],
        payload: dict[str, Any],
        desired_hash: str,
        workout_id: Any,
        schedule_id: Any,
    ) -> None:
        self.records[key] = {
            "week": self.week,
            "workout_id": workout_id,
            "schedule_id": schedule_id,
            "date": definition["schedule_date"],
            "name": definition["name"],
            "description": payload.get("description"),
            "content_hash": desired_hash,
            "status": "scheduled",
        }
        self.state["active_week"] = self.week
        self.repository.save(self.program_id, self.state)

    def _cleanup_replaced_and_obsolete(self) -> None:
        current_keys = {
            f"week-{self.week:02d}/{definition['id']}" for definition, _ in self.compiled
        }
        obsolete = (
            [
                (key, self.records[key])
                for key in sorted(set(self.records) - current_keys)
                if is_prunable(self.records[key], date.today())
            ]
            if self.prune
            else []
        )
        for key, record in obsolete + self.replaced_records:
            self._remove_previous_record(key, record)

    def _remove_previous_record(self, key: str, record: dict[str, Any]) -> None:
        workout_id = record.get("workout_id")
        remote = next(
            (item for item in self.remote_workouts if item.get("workoutId") == workout_id), None
        )
        schedule_id = record.get("schedule_id")
        name = record.get("name", key)
        if schedule_id:
            ignore_garmin_not_found("unschedule_workout", {"schedule_id": schedule_id})(
                lambda sid=schedule_id: self.client.unschedule_workout(sid)
            )
            self.result.add("unschedule", name, workout_id=workout_id, schedule_id=schedule_id)
        if workout_id and remote is not None:
            ignore_garmin_not_found("delete_workout", {"workout_id": workout_id})(
                lambda wid=workout_id: self.client.delete_workout(wid)
            )
            self.result.add("delete", name, workout_id=workout_id)
        elif workout_id:
            logger.warning(
                "Tracked Garmin workout already missing during replacement cleanup program_id=%s key=%s workout_id=%s",
                self.program_id,
                key,
                workout_id,
            )
        if self.records.get(key) is record:
            del self.records[key]
        self.repository.save(self.program_id, self.state)


def synchronize_program_week(
    client: GarminClient,
    repository: StateRepository,
    program: dict[str, Any],
    compiled: list[tuple[dict[str, Any], Any]],
    *,
    prune: bool = False,
    today: date | None = None,
) -> SyncResult:
    """Synchronize one week and return structured actions."""
    return WeekSynchronizer(client, repository, program, compiled, prune=prune, today=today).run()
