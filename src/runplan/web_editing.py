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
    ) -> dict[str, Any]:
        return self.store.get(name, repository=repository, fallback_pace_value=fallback_pace_value)

    def edit(
        self,
        name: str,
        request: dict[str, Any],
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
    ) -> dict[str, Any]:
        path = self.path(name)
        raw, text = self._read(path)
        if request.get("revision") != _revision(text):
            raise WebError(HTTPStatus.CONFLICT, "The program changed; reload before saving")
        metadata, move, workout_edit = self._apply_request(raw, request)
        self._validate(raw)
        rendered = dump_editable_yaml(raw)
        self._atomic_write(path, rendered)
        changes = self._change_names(metadata, move, workout_edit)
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
        )

    def _apply_request(self, raw: dict[str, Any], request: dict[str, Any]) -> tuple[Any, Any, Any]:
        metadata = request.get("program")
        if metadata is not None:
            if not isinstance(metadata, dict):
                raise WebError(HTTPStatus.BAD_REQUEST, "program must be an object")
            for field in ("name", "short_name", "description", "start_week"):
                if field in metadata:
                    raw["program"][field] = metadata[field]

        move = request.get("move")
        if move is not None:
            self._move(raw, move)

        workout_edit = request.get("workout")
        if workout_edit is not None:
            self._replace_workout(raw, workout_edit)
        return metadata, move, workout_edit

    @staticmethod
    def _validate(raw: dict[str, Any]) -> None:
        try:
            load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    @staticmethod
    def _change_names(metadata: Any, move: Any, workout_edit: Any) -> list[str]:
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
        return changes

    @staticmethod
    def _find_week(raw: dict[str, Any], number: int) -> dict[str, Any]:
        for week in raw.get("weeks", []):
            if week.get("week") == number:
                return week
        raise WebError(HTTPStatus.BAD_REQUEST, f"Unknown week {number}")

    def _move(self, raw: dict[str, Any], move: Any) -> None:
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
        occupied = next(
            (item for item in target["workouts"] if item.get("day") == target_day), None
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
