"""Synchronization tracking embedded in a user's YAML program."""

from __future__ import annotations

import os
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

from .json_repository import JsonStateRepository, new_state


def _yaml() -> YAML:
    value = YAML()
    value.preserve_quotes = True
    value.width = 4096
    value.indent(mapping=2, sequence=4, offset=2)
    return value


def _record_from_tracking(week: int, workout: dict[str, Any]) -> dict[str, Any] | None:
    tracking = workout.get("tracking")
    if not isinstance(tracking, dict):
        return None
    garmin = tracking.get("garmin") if isinstance(tracking.get("garmin"), dict) else {}
    actual = tracking.get("actual") if isinstance(tracking.get("actual"), dict) else {}
    record = {
        "week": tracking.get("synced_week", week),
        "date": tracking.get("scheduled_date"),
        "name": workout.get("name"),
        "status": tracking.get("status", "planned"),
        "workout_id": garmin.get("workout_id"),
        "schedule_id": garmin.get("schedule_id"),
        "activity_id": garmin.get("activity_id"),
        "content_hash": tracking.get("synced_content_hash"),
        "completed_at": actual.get("completed_at"),
        "actual_distance_meters": actual.get("distance_meters"),
        "actual_duration_seconds": actual.get("duration_seconds"),
    }
    return {key: value for key, value in record.items() if value is not None}


def tracking_from_record(record: dict[str, Any]) -> dict[str, Any]:
    tracking: dict[str, Any] = {"status": record.get("status", "planned")}
    if isinstance(record.get("week"), int):
        tracking["synced_week"] = record["week"]
    if record.get("date") is not None:
        tracking["scheduled_date"] = record["date"]
    if record.get("content_hash") is not None:
        tracking["synced_content_hash"] = record["content_hash"]
    garmin = {
        key: record[source]
        for key, source in (
            ("workout_id", "workout_id"),
            ("schedule_id", "schedule_id"),
            ("activity_id", "activity_id"),
        )
        if record.get(source) is not None
    }
    if garmin:
        tracking["garmin"] = garmin
    actual = {
        key: record[source]
        for key, source in (
            ("completed_at", "completed_at"),
            ("distance_meters", "actual_distance_meters"),
            ("duration_seconds", "actual_duration_seconds"),
        )
        if record.get(source) is not None
    }
    if actual:
        tracking["actual"] = actual
    return tracking


class YamlStateRepository:
    """Expose embedded workout tracking through the synchronization state port."""

    def __init__(
        self,
        program_path: Path,
        *,
        legacy_directory: Path | None = None,
    ) -> None:
        self.program_path = program_path.expanduser().resolve()
        self.state_directory = legacy_directory.expanduser().resolve() if legacy_directory else None
        self.legacy = JsonStateRepository(legacy_directory) if legacy_directory else None

    def _document(self) -> dict[str, Any]:
        document = _yaml().load(self.program_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("program YAML must be an object")
        return document

    def load(self, program_id: str) -> dict[str, Any]:
        document = self._document()
        if document.get("program", {}).get("id") != program_id:
            raise ValueError("state does not match the YAML program")
        state = new_state(program_id)
        for week in document.get("weeks", []):
            if not isinstance(week, dict) or not isinstance(week.get("week"), int):
                continue
            for workout in week.get("workouts", []):
                if not isinstance(workout, dict) or not isinstance(workout.get("id"), str):
                    continue
                record = _record_from_tracking(week["week"], workout)
                if record is not None:
                    state["workouts"][f"week-{week['week']:02d}/{workout['id']}"] = record
        program_tracking = document.get("program", {}).get("tracking", {})
        orphaned = program_tracking.get("orphaned_workouts", {}) if isinstance(program_tracking, dict) else {}
        if isinstance(orphaned, dict):
            for key, record in orphaned.items():
                if isinstance(key, str) and isinstance(record, dict):
                    state["workouts"].setdefault(key, dict(record))
        if self.legacy is not None:
            legacy = self.legacy.load(program_id)
            for key, record in legacy.get("workouts", {}).items():
                state["workouts"].setdefault(key, record)
        return state

    def save(self, program_id: str, state: dict[str, Any]) -> None:
        document = self._document()
        if document.get("program", {}).get("id") != program_id:
            raise ValueError("state does not match the YAML program")
        records = state.get("workouts")
        if not isinstance(records, dict):
            raise ValueError("state workouts must be an object")
        written: set[str] = set()
        for week in document.get("weeks", []):
            if not isinstance(week, dict) or not isinstance(week.get("week"), int):
                continue
            for workout in week.get("workouts", []):
                if not isinstance(workout, dict) or not isinstance(workout.get("id"), str):
                    continue
                key = f"week-{week['week']:02d}/{workout['id']}"
                record = records.get(key)
                if isinstance(record, dict):
                    workout["tracking"] = tracking_from_record(record)
                    written.add(key)
                else:
                    workout.pop("tracking", None)
        orphaned = {
            key: record
            for key, record in records.items()
            if key not in written and isinstance(record, dict)
        }
        program = document.setdefault("program", {})
        program_tracking = program.setdefault("tracking", {})
        if orphaned:
            program_tracking["orphaned_workouts"] = orphaned
        else:
            program_tracking.pop("orphaned_workouts", None)
            if not program_tracking:
                program.pop("tracking", None)
        stream = StringIO()
        _yaml().dump(document, stream)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self.program_path.name}.", dir=self.program_path.parent
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                output.write(stream.getvalue())
            temporary.replace(self.program_path)
        finally:
            temporary.unlink(missing_ok=True)
        if self.legacy is not None:
            self.legacy.delete(program_id)

    def delete(self, program_id: str) -> None:
        state = self.load(program_id)
        state["workouts"] = {}
        self.save(program_id, state)


__all__ = ["YamlStateRepository", "tracking_from_record"]
