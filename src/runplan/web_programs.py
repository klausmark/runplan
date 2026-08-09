"""YAML program document storage, editing, projection, and export."""

from __future__ import annotations

import hashlib
import logging
import re
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import unquote

from ruamel.yaml.error import YAMLError as RoundTripYAMLError

from .application.ports import StateRepository
from .domain.errors import WorkoutDefinitionError
from .parsing.yaml_loader import load_program_model
from .state.json_repository import JsonStateRepository
from .users import WebError
from .web_exports import export_program
from .web_yaml import load_editable_yaml

logger = logging.getLogger("runplan.web")


def _revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class ProgramStore:
    """Confined filesystem storage for YAML program documents.

    Structural rationale: this is the document-storage boundary; projection, editing,
    and export implementations are delegated while their compatibility methods remain.
    """

    def __init__(
        self,
        root: Path,
        *,
        repository: StateRepository | None = None,
        user_scoped: bool = False,
    ) -> None:
        self.root = root.expanduser().resolve()
        if not self.root.is_dir():
            raise ValueError(f"Program directory does not exist: {self.root}")
        self.repository = repository or JsonStateRepository()
        self.user_scoped = user_scoped

    def path(self, name: str) -> Path:
        decoded = unquote(name)
        if Path(decoded).name != decoded or not decoded.endswith((".yaml", ".yml")):
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid program filename")
        path = (self.root / decoded).resolve()
        if path.parent != self.root:
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid program filename")
        return path

    def for_user(self, user_id: str) -> ProgramStore:
        """Return storage confined to one user's program directory."""
        if not self.user_scoped:
            return self
        if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", user_id):
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid Runplan user")
        root = (self.root / user_id).resolve()
        if root.parent != self.root:
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid Runplan user")
        root.mkdir(parents=True, exist_ok=True)
        return ProgramStore(root, repository=self.repository)

    def upload(
        self,
        name: Any,
        content: Any,
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
    ) -> dict[str, Any]:
        """Validate and atomically store a new YAML program.

        Structural rationale: validation, uniqueness, and atomic persistence are the
        integrity boundary of one upload transaction.
        """
        if not isinstance(name, str):
            raise WebError(HTTPStatus.BAD_REQUEST, "Program filename is required")
        path = self.path(name)
        if path.exists():
            raise WebError(HTTPStatus.CONFLICT, "A program with that filename already exists")
        if not isinstance(content, str) or not content.strip():
            raise WebError(HTTPStatus.BAD_REQUEST, "Program YAML is required")
        if len(content.encode("utf-8")) > 1_000_000:
            raise WebError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "Program YAML must be 1 MB or less")
        try:
            raw = load_editable_yaml(content)
        except RoundTripYAMLError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Program YAML must be an object")
        try:
            model = load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        if any(item["id"] == model.id for item in self.list()):
            raise WebError(
                HTTPStatus.CONFLICT,
                f"A program with ID {model.id!r} already exists for this user",
            )
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise WebError(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not save program") from exc
        logger.info(
            "YAML program uploaded file=%s program_id=%s bytes=%d",
            path,
            model.id,
            len(content.encode("utf-8")),
        )
        return self.get(
            name,
            repository=repository,
            fallback_pace_value=fallback_pace_value,
        )

    def list(self) -> list[dict[str, str]]:
        result = []
        for path in sorted((*self.root.glob("*.yaml"), *self.root.glob("*.yml"))):
            try:
                raw, text = self._read(path)
                model = load_program_model(raw)
            except (OSError, RoundTripYAMLError, WorkoutDefinitionError) as exc:
                logger.warning(
                    "Ignoring unreadable YAML program file=%s exception=%s message=%s",
                    path,
                    type(exc).__name__,
                    exc,
                )
                continue
            result.append(
                {"file": path.name, "id": model.id, "name": model.name, "revision": _revision(text)}
            )
        return result

    def _read(self, path: Path) -> tuple[dict[str, Any], str]:
        try:
            text = path.read_text(encoding="utf-8")
        except FileNotFoundError as exc:
            raise WebError(HTTPStatus.NOT_FOUND, "Program not found") from exc
        try:
            raw = load_editable_yaml(text)
        except RoundTripYAMLError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Program YAML must be an object")
        return raw, text

    def revision(self, name: str) -> str:
        """Return the current document revision without building its view model."""
        _, text = self._read(self.path(name))
        return _revision(text)

    def get(
        self,
        name: str,
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
    ) -> dict[str, Any]:
        """Build the web read model for one stored program."""
        from .web_projection import ProgramProjector

        return ProgramProjector(self).get(
            name,
            repository=repository,
            fallback_pace_value=fallback_pace_value,
        )

    def edit(
        self,
        name: str,
        request: dict[str, Any],
        *,
        repository: StateRepository | None = None,
        fallback_pace_value: str | None = None,
    ) -> dict[str, Any]:
        """Validate and apply one program edit transaction."""
        from .web_editing import ProgramEditor

        return ProgramEditor(self).edit(
            name,
            request,
            repository=repository,
            fallback_pace_value=fallback_pace_value,
        )

    def delete(self, name: str) -> None:
        """Remove a stored YAML program file from disk."""
        path = self.path(name)
        try:
            path.unlink()
        except FileNotFoundError as exc:
            raise WebError(HTTPStatus.NOT_FOUND, "Program not found") from exc
        logger.info("YAML program deleted file=%s", path)

    def export(
        self, name: str, format_name: str, *, fallback_pace_value: str | None = None
    ) -> tuple[bytes, str, str]:
        path = self.path(name)
        raw, _ = self._read(path)
        return export_program(path, raw, format_name, fallback_pace_value=fallback_pace_value)
