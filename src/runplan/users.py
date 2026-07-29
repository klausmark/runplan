"""Shared Runplan user configuration and active-program persistence."""

from __future__ import annotations

import logging
import os
import re
import threading
import tomllib
from collections.abc import Iterable
from dataclasses import dataclass, replace
from http import HTTPStatus
from pathlib import Path
from typing import Any

from .parsing.values import parse_pace
from .user_config import write_user_config
from .user_credentials import CredentialStore

logger = logging.getLogger(__name__)


class WebError(Exception):
    """An expected adapter error with an HTTP-compatible status."""

    def __init__(self, status: HTTPStatus, message: str):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class RunplanUser:
    """Non-secret server configuration for one local Runplan user."""

    id: str
    name: str
    credentials_file: Path
    token_store: Path
    state_directory: Path
    default_pace: str = "6:00 min/km"
    active_program: str | None = None

    def public(self) -> dict[str, str | None]:
        return {
            "id": self.id,
            "name": self.name,
            "activeProgram": self.active_program,
        }


class UserRegistry:
    """Coordinate user lookup and updates without exposing secret paths.

    Structural rationale: this remains the public, thread-safe transaction boundary for
    registry changes; credential I/O and registry serialization are delegated.
    """

    def __init__(self, users: Iterable[RunplanUser], *, config_path: Path | None = None) -> None:
        user_list = list(users)
        self._users = {user.id: user for user in user_list}
        if len(self._users) != len(user_list):
            raise ValueError("Runplan user IDs must be unique")
        self.config_path = config_path.expanduser().resolve() if config_path else None
        self._lock = threading.Lock()
        self._credentials = CredentialStore()

    @property
    def default_id(self) -> str:
        if not self._users:
            raise WebError(HTTPStatus.BAD_REQUEST, "No Runplan users are configured")
        return next(iter(self._users))

    def list(self) -> list[dict[str, str | None]]:
        return [user.public() for user in self._users.values()]

    def users(self) -> tuple[RunplanUser, ...]:
        return tuple(self._users.values())

    def get(self, user_id: str | None) -> RunplanUser:
        if not isinstance(user_id, str) or user_id not in self._users:
            raise WebError(HTTPStatus.BAD_REQUEST, "Unknown Runplan user")
        return self._users[user_id]

    def set_active_program(self, user_id: str, filename: str) -> RunplanUser:
        """Atomically persist a validated program filename for one user."""
        user = self.get(user_id)
        if (
            not isinstance(filename, str)
            or Path(filename).name != filename
            or not filename.endswith((".yaml", ".yml"))
        ):
            raise WebError(HTTPStatus.BAD_REQUEST, "Invalid program filename")
        if self.config_path is None:
            raise WebError(HTTPStatus.CONFLICT, "This user registry is read-only")
        with self._lock:
            updated_user = replace(user, active_program=filename)
            updated = {**self._users, user.id: updated_user}
            self._write(updated.values())
            self._users = updated
        logger.info("Active program changed user=%s file=%s", user.id, filename)
        return updated_user

    def create(self, username: Any, full_name: Any) -> dict[str, str | None]:
        """Persist and return a new server-configured Runplan user."""
        if not isinstance(username, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", username):
            raise WebError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                "Username must use lowercase letters, numbers, and hyphens",
            )
        if not isinstance(full_name, str) or not full_name.strip():
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Full name is required")
        if len(full_name.strip()) > 100:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Full name is too long")
        if self.config_path is None:
            raise WebError(HTTPStatus.CONFLICT, "This user registry is read-only")
        with self._lock:
            if username in self._users:
                raise WebError(HTTPStatus.CONFLICT, "Username already exists")
            base = self.config_path.parent / "users" / username
            user = RunplanUser(
                id=username,
                name=full_name.strip(),
                credentials_file=base / "credentials.toml",
                token_store=base / "tokens",
                state_directory=base / "state",
                default_pace=os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"),
            )
            updated = {**self._users, username: user}
            self._write(updated.values())
            self._users = updated
        logger.info("Runplan user created user=%s", username)
        return user.public()

    def settings(self, user_id: str | None) -> dict[str, Any]:
        user = self.get(user_id)
        credentials = self._credentials.read(user.credentials_file)
        return {
            "id": user.id,
            "fullName": user.name,
            "defaultPace": user.default_pace,
            "garminEmail": credentials.get("email", ""),
            "hasGarminPassword": bool(credentials.get("password")),
        }

    def update_settings(self, user_id: str | None, request: dict[str, Any]) -> dict[str, Any]:
        user = self.get(user_id)
        full_name = request.get("fullName")
        default_pace = request.get("defaultPace")
        email = request.get("garminEmail")
        password = request.get("garminPassword", "")
        if not isinstance(full_name, str) or not full_name.strip():
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Full name is required")
        if not isinstance(default_pace, str):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Default pace is required")
        try:
            parse_pace(default_pace, "defaultPace")
        except ValueError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        if not isinstance(email, str) or not email.strip():
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin email is required")
        if not isinstance(password, str):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin password is invalid")
        existing = self._credentials.read(user.credentials_file)
        effective_password = password or existing.get("password")
        if not isinstance(effective_password, str) or not effective_password:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin password is required")
        with self._lock:
            updated_user = replace(user, name=full_name.strip(), default_pace=default_pace.strip())
            updated = {**self._users, user.id: updated_user}
            self._credentials.write(user.credentials_file, email.strip(), effective_password)
            self._write(updated.values())
            self._users = updated
        logger.info(
            "User settings saved user=%s password_changed=%s",
            user.id,
            bool(password),
        )
        return {"user": updated_user.public(), "settings": self.settings(user.id)}

    def _write(self, users: Iterable[RunplanUser]) -> None:
        assert self.config_path is not None
        write_user_config(self.config_path, users)


def _configured_user_path(
    configured: Path,
    entry: dict[str, Any],
    index: int,
    field: str,
    fallback: str,
) -> Path:
    """Resolve and validate one user path relative to its registry file."""
    value = entry.get(field, fallback)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{configured}: users[{index}].{field} is invalid")
    result = Path(value).expanduser()
    return result if result.is_absolute() else configured.parent / result


def load_user_registry(path: Path | None = None) -> UserRegistry:
    """Load users from the configured TOML file, which may not exist yet."""
    configured = path or Path(os.getenv("RUNPLAN_USERS_FILE", "~/.config/runplan/users.toml"))
    configured = configured.expanduser().resolve()
    if not configured.exists():
        return UserRegistry([], config_path=configured)
    try:
        raw = tomllib.loads(configured.read_text(encoding="utf-8-sig"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"Could not load Runplan users from {configured}: {exc}") from exc
    entries = raw.get("users")
    if not isinstance(entries, list) or not entries:
        raise ValueError(f"{configured}: 'users' must be a non-empty array of tables")
    users = [_user_from_entry(configured, entry, index) for index, entry in enumerate(entries, 1)]
    return UserRegistry(users, config_path=configured)


def _user_from_entry(configured: Path, entry: Any, index: int) -> RunplanUser:
    if not isinstance(entry, dict):
        raise ValueError(f"{configured}: users[{index}] must be a table")
    user_id, name = _user_identity(configured, entry, index)
    default_pace = _user_pace(configured, entry, index)
    active_program = _active_program(configured, entry, index)
    return RunplanUser(
        id=user_id,
        name=name,
        credentials_file=_configured_user_path(
            configured, entry, index, "credentials_file", f"credentials-{user_id}.toml"
        ),
        token_store=_configured_user_path(
            configured, entry, index, "token_store", f"tokens/{user_id}"
        ),
        state_directory=_configured_user_path(
            configured, entry, index, "state_dir", f"state/{user_id}"
        ),
        default_pace=default_pace,
        active_program=active_program,
    )


def _user_identity(configured: Path, entry: dict[str, Any], index: int) -> tuple[str, str]:
    user_id, name = entry.get("id"), entry.get("name")
    if not isinstance(user_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", user_id):
        raise ValueError(f"{configured}: users[{index}].id is invalid")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{configured}: users[{index}].name is required")
    return user_id, name.strip()


def _user_pace(configured: Path, entry: dict[str, Any], index: int) -> str:
    value = entry.get("default_pace", os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"))
    if not isinstance(value, str):
        raise ValueError(f"{configured}: users[{index}].default_pace is invalid")
    try:
        parse_pace(value, f"users[{index}].default_pace")
    except ValueError as exc:
        raise ValueError(f"{configured}: {exc}") from exc
    return value


def _active_program(configured: Path, entry: dict[str, Any], index: int) -> str | None:
    value = entry.get("active_program")
    if value is not None and (
        not isinstance(value, str)
        or Path(value).name != value
        or not value.endswith((".yaml", ".yml"))
    ):
        raise ValueError(f"{configured}: users[{index}].active_program is invalid")
    return value


__all__ = [
    "RunplanUser",
    "UserRegistry",
    "WebError",
    "load_user_registry",
]
