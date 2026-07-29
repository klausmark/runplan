"""Atomic local JSON persistence for CLI synchronization state."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

CURRENT_STATE_VERSION = 2


def new_state(program_id: str) -> dict[str, Any]:
    """Create an empty document using the current state schema."""
    return {
        "schema_version": CURRENT_STATE_VERSION,
        "program_id": program_id,
        "workouts": {},
    }


def migrate_state(state: Any) -> dict[str, Any]:
    """Migrate a loaded state document to the current schema in memory."""
    if not isinstance(state, dict):
        raise ValueError("state root must be an object")
    version = state.get("schema_version", 0)
    if not isinstance(version, int) or isinstance(version, bool) or version < 0:
        raise ValueError("schema_version must be a non-negative integer")
    if version > CURRENT_STATE_VERSION:
        raise ValueError(
            f"schema version {version} is newer than supported version {CURRENT_STATE_VERSION}"
        )
    migrated = dict(state)
    if version == 0:
        migrated["schema_version"] = 1
        version = 1
    if version == 1:
        workouts = migrated.get("workouts")
        if isinstance(workouts, dict):
            migrated["workouts"] = {
                key: (
                    {**record, "status": _legacy_status(record)}
                    if isinstance(record, dict) and "status" not in record
                    else record
                )
                for key, record in workouts.items()
            }
        migrated["schema_version"] = 2
    return migrated


def _legacy_status(record: dict[str, Any]) -> str:
    """Infer the safest active status for a pre-lifecycle record."""
    return "scheduled" if record.get("schedule_id") else "planned"


def state_path(program_id: str) -> Path:
    """Return the configured state path for a program."""
    state_directory = Path(os.getenv("GARMIN_STATE_DIR", "~/.local/state/runplan")).expanduser()
    return state_directory / f"{program_id}.json"


def load_state(program_id: str) -> dict[str, Any]:
    """Load state or return a new empty state document."""
    path = state_path(program_id)
    if not path.exists():
        return new_state(program_id)
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"Could not read state file: {path}\n{exc}") from exc
    try:
        state = migrate_state(state)
    except ValueError as exc:
        raise SystemExit(f"State file has an invalid format: {path}\n{exc}") from exc
    if state.get("program_id") != program_id or not isinstance(state.get("workouts"), dict):
        raise SystemExit(f"State file has an invalid format: {path}")
    return state


def save_state(program_id: str, state: dict[str, Any]) -> None:
    """Atomically persist one program state document."""
    document = migrate_state(state)
    if document.get("program_id") != program_id or not isinstance(document.get("workouts"), dict):
        raise ValueError("state does not match the program or schema")
    path = state_path(program_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


class JsonStateRepository:
    """Filesystem-backed state repository used by the CLI."""

    def __init__(self, state_directory: Path | None = None) -> None:
        self.state_directory = state_directory.expanduser().resolve() if state_directory else None

    def _path(self, program_id: str) -> Path:
        if self.state_directory is None:
            return state_path(program_id)
        return self.state_directory / f"{program_id}.json"

    def load(self, program_id: str) -> dict[str, Any]:
        path = self._path(program_id)
        if self.state_directory is None:
            return load_state(program_id)
        if not path.exists():
            return new_state(program_id)
        try:
            state = migrate_state(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            raise SystemExit(f"Could not read state file: {path}\n{exc}") from exc
        if state.get("program_id") != program_id or not isinstance(state.get("workouts"), dict):
            raise SystemExit(f"State file has an invalid format: {path}")
        return state

    def save(self, program_id: str, state: dict[str, Any]) -> None:
        if self.state_directory is None:
            save_state(program_id, state)
            return
        document = migrate_state(state)
        if document.get("program_id") != program_id or not isinstance(
            document.get("workouts"), dict
        ):
            raise ValueError("state does not match the program or schema")
        path = self._path(program_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        temporary.replace(path)

    def delete(self, program_id: str) -> None:
        path = self._path(program_id)
        if path.exists():
            path.unlink()


__all__ = [
    "CURRENT_STATE_VERSION",
    "JsonStateRepository",
    "load_state",
    "migrate_state",
    "new_state",
    "save_state",
    "state_path",
]
