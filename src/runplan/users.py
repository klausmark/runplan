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

from .domain.pace import (
    format_pace_seconds,
    intensity_pace_seconds,
    parse_total_seconds,
)
from .user_config import write_user_config
from .user_credentials import CredentialStore

logger = logging.getLogger(__name__)

DEFAULT_FIVE_K_BEST = "30:00"
DEFAULT_PACE_ZONE_SECONDS_PER_KM = 5
MAX_PACE_ZONE_SECONDS_PER_KM = 60

ENV_FIVE_K_BEST = "RUNPLAN_5K_BEST"
ENV_PACE_ZONE = "RUNPLAN_PACE_ZONE"
ENV_LEGACY_DEFAULT_PACE = "RUNPLAN_DEFAULT_PACE"


def _parse_legacy_default_pace_to_five_k(value: str) -> str:
    """Convert a legacy ``M:SS min/km`` string into a 5K race total."""
    text = value.strip()
    match = re.fullmatch(
        r"\s*(\d+):([0-5]\d)\s*(?:-\s*(\d+):([0-5]\d)\s*)?min/km\s*",
        text,
        re.IGNORECASE,
    )
    if match is None:
        raise ValueError(f"invalid legacy pace {value!r}")
    first = int(match.group(1)) * 60 + int(match.group(2))
    second = int(match.group(3)) * 60 + int(match.group(4)) if match.group(3) is not None else first
    midpoint = (first + second) / 2
    total = round(midpoint * 5)
    minutes, seconds = divmod(total, 60)
    return f"{minutes}:{seconds:02d}"


def _coerce_pace_zone(value: Any) -> int:
    """Validate and normalize the user's Garmin pace zone tolerance."""
    if isinstance(value, bool):
        raise ValueError(f"invalid pace zone {value!r}; use 0-60")
    if isinstance(value, float):
        if not value.is_integer():
            raise ValueError(f"invalid pace zone {value!r}; use 0-60")
        value = int(value)
    elif isinstance(value, str):
        try:
            value = int(value.strip())
        except ValueError as exc:
            raise ValueError(f"invalid pace zone {value!r}; use 0-60") from exc
    elif not isinstance(value, int):
        raise ValueError(f"invalid pace zone {value!r}; use 0-60")
    if not 0 <= value <= MAX_PACE_ZONE_SECONDS_PER_KM:
        raise ValueError(f"pace zone {value} out of range; use 0-{MAX_PACE_ZONE_SECONDS_PER_KM}")
    return value


def five_k_pace_seconds(five_k_best: str) -> float:
    """Return the average 5K pace (seconds per kilometer) for ``five_k_best``."""
    total = parse_total_seconds(five_k_best)
    return total / 5.0


def fallback_pace_seconds_per_km(five_k_best: str) -> float:
    """Return the recovery pace used as the generic estimate fallback."""
    return intensity_pace_seconds(parse_total_seconds(five_k_best), "recovery")


class WebError(Exception):
    """An expected adapter error with an HTTP-compatible status."""

    def __init__(
        self,
        status: HTTPStatus,
        message: str,
        *,
        headers: dict[str, str] | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.headers = headers or {}


@dataclass(frozen=True)
class RunplanUser:
    """Non-secret server configuration for one local Runplan user."""

    id: str
    name: str
    credentials_file: Path
    token_store: Path
    state_directory: Path
    five_k_best: str = "30:00"
    pace_zone_seconds_per_km: int = 5
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

    def clear_active_program(self, user_id: str) -> RunplanUser:
        """Atomically drop the active program pointer for one user."""
        user = self.get(user_id)
        if user.active_program is None:
            return user
        if self.config_path is None:
            raise WebError(HTTPStatus.CONFLICT, "This user registry is read-only")
        with self._lock:
            updated_user = replace(user, active_program=None)
            updated = {**self._users, user.id: updated_user}
            self._write(updated.values())
            self._users = updated
        logger.info("Active program cleared user=%s", user.id)
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
                five_k_best=os.getenv(ENV_FIVE_K_BEST, DEFAULT_FIVE_K_BEST),
                pace_zone_seconds_per_km=_coerce_pace_zone(
                    os.getenv(ENV_PACE_ZONE, str(DEFAULT_PACE_ZONE_SECONDS_PER_KM))
                ),
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
            "fiveKBest": user.five_k_best,
            "paceZoneSecondsPerKm": user.pace_zone_seconds_per_km,
            "garminEmail": credentials.get("email", ""),
            "hasGarminPassword": bool(credentials.get("password")),
        }

    def update_settings(self, user_id: str | None, request: dict[str, Any]) -> dict[str, Any]:
        user = self.get(user_id)
        full_name = request.get("fullName")
        five_k_best = request.get("fiveKBest")
        pace_zone = request.get("paceZoneSecondsPerKm")
        email = request.get("garminEmail")
        password = request.get("garminPassword", "")
        if not isinstance(full_name, str) or not full_name.strip():
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Full name is required")
        if not isinstance(five_k_best, str):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "5K best is required")
        try:
            normalized_five_k_best = parse_total_seconds(five_k_best.strip())
        except ValueError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        try:
            normalized_pace_zone = _coerce_pace_zone(pace_zone)
        except ValueError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        if not isinstance(email, str):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin email is invalid")
        if not isinstance(password, str):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin password is invalid")
        existing = self._credentials.read(user.credentials_file)
        submitted_email = email.strip()
        submitted_password = password
        effective_email = submitted_email or existing.get("email", "")
        effective_password = submitted_password or existing.get("password", "")
        if submitted_email and not effective_password:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin password is required")
        if submitted_password and not effective_email:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin email is required")
        credentials_changed = submitted_email != existing.get("email", "") or bool(
            submitted_password and submitted_password != existing.get("password", "")
        )
        stored_five_k = format_pace_seconds(normalized_five_k_best)
        with self._lock:
            updated_user = replace(
                user,
                name=full_name.strip(),
                five_k_best=stored_five_k,
                pace_zone_seconds_per_km=normalized_pace_zone,
            )
            updated = {**self._users, user.id: updated_user}
            if credentials_changed:
                self._credentials.write(user.credentials_file, effective_email, effective_password)
            self._write(updated.values())
            self._users = updated
        logger.info(
            "User settings saved user=%s password_changed=%s",
            user.id,
            bool(submitted_password),
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
    five_k_best = _user_five_k_best(configured, entry, index)
    pace_zone = _user_pace_zone(configured, entry, index)
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
        five_k_best=five_k_best,
        pace_zone_seconds_per_km=pace_zone,
        active_program=active_program,
    )


def _user_identity(configured: Path, entry: dict[str, Any], index: int) -> tuple[str, str]:
    user_id, name = entry.get("id"), entry.get("name")
    if not isinstance(user_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", user_id):
        raise ValueError(f"{configured}: users[{index}].id is invalid")
    if not isinstance(name, str) or not name.strip():
        raise ValueError(f"{configured}: users[{index}].name is required")
    return user_id, name.strip()


def _user_five_k_best(configured: Path, entry: dict[str, Any], index: int) -> str:
    """Read or migrate a user's ``five_k_best`` entry."""
    if "five_k_best" in entry:
        value = entry["five_k_best"]
        if not isinstance(value, str):
            raise ValueError(f"{configured}: users[{index}].five_k_best is invalid")
        try:
            total = parse_total_seconds(value)
        except ValueError as exc:
            raise ValueError(f"{configured}: {exc}") from exc
        return format_pace_seconds(total)
    if "default_pace" in entry:
        legacy = entry["default_pace"]
        if not isinstance(legacy, str):
            raise ValueError(f"{configured}: users[{index}].default_pace is invalid")
        try:
            return _parse_legacy_default_pace_to_five_k(legacy)
        except ValueError as exc:
            raise ValueError(f"{configured}: {exc}") from exc
    legacy_env = os.getenv(ENV_LEGACY_DEFAULT_PACE)
    if legacy_env:
        try:
            return _parse_legacy_default_pace_to_five_k(legacy_env)
        except ValueError as exc:
            raise ValueError(f"{ENV_LEGACY_DEFAULT_PACE}: {exc}") from exc
    return os.getenv(ENV_FIVE_K_BEST, DEFAULT_FIVE_K_BEST)


def _user_pace_zone(configured: Path, entry: dict[str, Any], index: int) -> int:
    """Read a user's Garmin pace zone tolerance from the entry."""
    if "pace_zone_seconds_per_km" not in entry:
        return _coerce_pace_zone(os.getenv(ENV_PACE_ZONE, str(DEFAULT_PACE_ZONE_SECONDS_PER_KM)))
    value = entry["pace_zone_seconds_per_km"]
    try:
        return _coerce_pace_zone(value)
    except ValueError as exc:
        raise ValueError(f"{configured}: users[{index}].pace_zone_seconds_per_km: {exc}") from exc


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
