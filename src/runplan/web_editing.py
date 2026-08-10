"""Validate and atomically apply edits to program YAML documents."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
from http import HTTPStatus
from pathlib import Path
from typing import TYPE_CHECKING, Any

from ruamel.yaml.error import YAMLError as RoundTripYAMLError

from .application.ports import StateRepository
from .domain.errors import WorkoutDefinitionError
from .parsing.yaml_loader import load_program_model
from .state.yaml_repository import record_from_workout_tracking
from .users import WebError
from .web_yaml import dump_editable_yaml, load_editable_yaml

if TYPE_CHECKING:
    from .web_programs import ProgramStore

logger = logging.getLogger("runplan.web")


def _revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ProgramEditor:
    """Apply validated metadata, movement, and workout edits to one document.

    Structural rationale: its methods are the validation and mutation rules for one
    atomic YAML edit transaction.
    """

    def __init__(self, store: ProgramStore) -> None:
        self.store = store

    def path(self, name: str) -> Path:
        return self.store.path(name)

    def _read(self, path: Path) -> tuple[dict[str, Any], str]:
        return self.store._read(path)

    def get(
        self,
        name: str,
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
        pace_zone_seconds_per_km: int | None = None,
    ) -> dict[str, Any]:
        return self.store.get(
            name,
            repository=repository,
            fallback_pace_value=fallback_pace_value,
            pace_zone_seconds_per_km=pace_zone_seconds_per_km,
        )

    def edit(
        self,
        name: str,
        request: dict[str, Any],
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
        pace_zone_seconds_per_km: int | None = None,
    ) -> dict[str, Any]:
        path = self.path(name)
        raw, text = self._read(path)
        if request.get("revision") != _revision(text):
            raise WebError(HTTPStatus.CONFLICT, "The program changed; reload before saving")
        state_repository = repository or self.store.repository
        completed = self._completed_workouts(raw, state_repository)
        metadata, move, workout_edit, workout_add, workout_delete = self._apply_request(
            raw, request, completed
        )
        self._validate(raw)
        rendered = dump_editable_yaml(raw)
        self._atomic_write(path, rendered)
        changes = self._change_names(metadata, move, workout_edit, workout_add, workout_delete)
        logger.info(
            "YAML program saved file=%s changes=%s bytes=%d",
            path,
            ",".join(changes) or "none",
            len(rendered.encode("utf-8")),
        )
        return self.get(
            name,
            repository=repository,
            fallback_pace_value=fallback_pace_value,
            pace_zone_seconds_per_km=pace_zone_seconds_per_km,
        )

    def _apply_request(
        self,
        raw: dict[str, Any],
        request: dict[str, Any],
        completed: set[tuple[int, str]],
    ) -> tuple[Any, Any, Any, Any, Any]:
        metadata = request.get("program")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise WebError(HTTPStatus.BAD_REQUEST, "program must be an object")
            for field in ("name", "short_name", "description", "start_week"):
                if field in metadata:
                    raw["program"][field] = metadata[field]

        move = request.get("move")
        if move is not None:
            self._move(raw, move, completed)

        workout_edit = request.get("workout")
        if workout_edit is not None:
            self._replace_workout(raw, workout_edit)

        workout_add = request.get("add_workout")
        if workout_add is not None:
            self._add_workout(raw, workout_add)

        workout_delete = request.get("delete_workout")
        if workout_delete is not None:
            self._delete_workout(raw, workout_delete)
        return metadata, move, workout_edit, workout_add, workout_delete

    @staticmethod
    def _completed_workouts(
        raw: dict[str, Any], repository: StateRepository
    ) -> set[tuple[int, str]]:
        program_id = raw.get("program", {}).get("id")
        records = repository.load(program_id).get("workouts", {})
        completed: set[tuple[int, str]] = set()
        for week in raw.get("weeks", []):
            if not isinstance(week, dict) or not isinstance(week.get("week"), int):
                continue
            for workout in week.get("workouts", []):
                if not isinstance(workout, dict) or not isinstance(workout.get("id"), str):
                    continue
                tracking = workout.get("tracking")
                key = f"week-{week['week']:02d}/{workout['id']}"
                record = records.get(key) if isinstance(records, dict) else None
                if (isinstance(tracking, dict) and tracking.get("status") == "completed") or (
                    isinstance(record, dict) and record.get("status") == "completed"
                ):
                    completed.add((week["week"], workout["id"]))
        return completed

    @staticmethod
    def _validate(raw: dict[str, Any]) -> None:
        try:
            load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    @staticmethod
    def _change_names(
        metadata: Any,
        move: Any,
        workout_edit: Any,
        workout_add: Any,
        workout_delete: Any,
    ) -> list[str]:
        changes: list[str] = []
        if isinstance(metadata, dict):
            changes.extend(
                f"program.{field}"
                for field in metadata
                if field in {"name", "short_name", "description", "start_week"}
            )
        if isinstance(move, dict):
            changes.append(
                "move:"
                f"{move.get('workout_id')}:{move.get('from_week')}->"
                f"{move.get('to_week')}/day-{move.get('to_day')}"
            )
        if isinstance(workout_edit, dict):
            changes.append(f"workout:{workout_edit.get('week')}/{workout_edit.get('workout_id')}")
        if isinstance(workout_add, dict):
            changes.append(f"add-workout:{workout_add.get('week')}")
        if isinstance(workout_delete, dict):
            changes.append(
                f"delete-workout:{workout_delete.get('week')}/{workout_delete.get('workout_id')}"
            )
        return changes

    @staticmethod
    def _find_week(raw: dict[str, Any], number: int) -> dict[str, Any]:
        for week in raw.get("weeks", []):
            if week.get("week") == number:
                return week
        raise WebError(HTTPStatus.BAD_REQUEST, f"Unknown week {number}")

    def _move(self, raw: dict[str, Any], move: Any, completed: set[tuple[int, str]]) -> None:
        if not isinstance(move, dict):
            raise WebError(HTTPStatus.BAD_REQUEST, "move must be an object")
        try:
            source_number = int(move["from_week"])
            target_number = int(move["to_week"])
            target_day = int(move["to_day"])
            workout_id = str(move["workout_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid move") from exc
        if not 1 <= target_day <= 7:
            raise WebError(HTTPStatus.BAD_REQUEST, "Target day must be from 1 to 7")
        source = self._find_week(raw, source_number)
        target = self._find_week(raw, target_number)
        workout = next((item for item in source["workouts"] if item.get("id") == workout_id), None)
        if workout is None:
            raise WebError(HTTPStatus.BAD_REQUEST, "Workout not found in source week")
        if (source_number, workout_id) in completed:
            raise WebError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "Completed workouts can only be moved by editing YAML directly",
            )
        occupied = next(
            (item for item in target["workouts"] if item.get("day") == target_day), None
        )
        if (
            occupied is not None
            and occupied is not workout
            and (target_number, occupied.get("id")) in completed
        ):
            raise WebError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "A completed workout can only be moved by editing YAML directly",
            )
        old_day = workout["day"]
        if occupied is not None and occupied is not workout:
            occupied["day"] = old_day
            if source is not target:
                target["workouts"].remove(occupied)
                source["workouts"].append(occupied)
        source["workouts"].remove(workout)
        workout["day"] = target_day
        target["workouts"].append(workout)
        source["workouts"].sort(key=lambda item: item["day"])
        if target is not source:
            target["workouts"].sort(key=lambda item: item["day"])

    def _replace_workout(self, raw: dict[str, Any], edit: Any) -> None:
        if not isinstance(edit, dict):
            raise WebError(HTTPStatus.BAD_REQUEST, "workout must be an object")
        try:
            week = self._find_week(raw, int(edit["week"]))
            workout_id = str(edit["workout_id"])
            replacement = load_editable_yaml(edit["yaml"])
        except (KeyError, TypeError, ValueError, RoundTripYAMLError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid workout YAML: {exc}") from exc
        if not isinstance(replacement, dict):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Workout YAML must be an object")
        for index, workout in enumerate(week["workouts"]):
            if workout.get("id") == workout_id:
                if replacement.get("id") != workout_id:
                    raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Workout ID cannot be changed")
                week["workouts"][index] = replacement
                week["workouts"].sort(key=lambda item: item.get("day", 0))
                return
        raise WebError(HTTPStatus.BAD_REQUEST, "Workout not found")

    def _add_workout(self, raw: dict[str, Any], addition: Any) -> None:
        if not isinstance(addition, dict):
            raise WebError(HTTPStatus.BAD_REQUEST, "add_workout must be an object")
        try:
            week = self._find_week(raw, int(addition["week"]))
            workout = load_editable_yaml(addition["yaml"])
        except (KeyError, TypeError, ValueError, RoundTripYAMLError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid workout YAML: {exc}") from exc
        if not isinstance(workout, dict):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Workout YAML must be an object")
        week["workouts"].append(workout)
        week["workouts"].sort(key=lambda item: item.get("day", 0))

    def _delete_workout(self, raw: dict[str, Any], deletion: Any) -> None:
        if not isinstance(deletion, dict):
            raise WebError(HTTPStatus.BAD_REQUEST, "delete_workout must be an object")
        try:
            week_number = int(deletion["week"])
            workout_id = str(deletion["workout_id"])
        except (KeyError, TypeError, ValueError) as exc:
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid workout deletion") from exc
        week = self._find_week(raw, week_number)
        workout = next((item for item in week["workouts"] if item.get("id") == workout_id), None)
        if workout is None:
            raise WebError(HTTPStatus.BAD_REQUEST, "Workout not found")
        if len(week["workouts"]) == 1:
            raise WebError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "A week must contain at least one workout",
            )
        record = record_from_workout_tracking(week_number, workout)
        if record is not None and (record.get("workout_id") or record.get("schedule_id")):
            record["pending_deletion"] = True
            tracking = raw.setdefault("program", {}).setdefault("tracking", {})
            orphaned = tracking.setdefault("orphaned_workouts", {})
            orphaned[f"week-{week_number:02d}/{workout_id}"] = record
        week["workouts"].remove(workout)

    @staticmethod
    def _atomic_write(path: Path, text: str) -> None:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                stream.write(text)
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
