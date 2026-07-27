"""Small dependency-free HTTP adapter for the Runplan web MVP."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import tomllib
from argparse import Namespace
from dataclasses import dataclass, replace
from datetime import date, timedelta
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import StringIO
from pathlib import Path
from typing import Any, Callable
from urllib.parse import parse_qs, unquote, urlsplit

from ruamel.yaml import YAML
from ruamel.yaml.error import YAMLError as RoundTripYAMLError

from .application.export import build_program_export
from .application.ports import GarminClient, StateRepository
from .application.sync import (
    discover_sync_state,
    plan_program_weeks,
    rebuild_sync_state,
    synchronize_program_weeks,
    workout_content_hash,
)
from .domain.errors import WorkoutDefinitionError
from .domain.estimates import estimate_steps
from .domain.selectors import WeekSelection
from .exporters.markdown import format_program_markdown
from .exporters.pdf import export_pdf
from .parsing.values import parse_pace
from .parsing.yaml_loader import load_program_model
from .state.json_repository import JsonStateRepository


ASSET_DIR = Path(__file__).with_name("web_assets")


class WebError(Exception):
    """An expected request error with an HTTP status."""

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

    def public(self) -> dict[str, str]:
        return {"id": self.id, "name": self.name}


class UserRegistry:
    """Resolve configured users without exposing credential locations."""

    def __init__(
        self, users: list[RunplanUser], *, config_path: Path | None = None
    ) -> None:
        self._users = {user.id: user for user in users}
        if len(self._users) != len(users):
            raise ValueError("Runplan user IDs must be unique")
        self.config_path = config_path.expanduser().resolve() if config_path else None
        self._lock = threading.Lock()

    @property
    def default_id(self) -> str:
        if not self._users:
            raise WebError(HTTPStatus.BAD_REQUEST, "No Runplan users are configured")
        return next(iter(self._users))

    def list(self) -> list[dict[str, str]]:
        return [user.public() for user in self._users.values()]

    def get(self, user_id: str | None) -> RunplanUser:
        if not isinstance(user_id, str) or user_id not in self._users:
            raise WebError(HTTPStatus.BAD_REQUEST, "Unknown Runplan user")
        return self._users[user_id]

    def create(self, username: Any, full_name: Any) -> dict[str, str]:
        """Persist and return a new server-configured Runplan user."""
        if not isinstance(username, str) or not re.fullmatch(
            r"[a-z0-9]+(?:-[a-z0-9]+)*", username
        ):
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
        return user.public()

    def settings(self, user_id: str | None) -> dict[str, Any]:
        user = self.get(user_id)
        credentials = self._read_credentials(user.credentials_file)
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
        existing = self._read_credentials(user.credentials_file)
        effective_password = password or existing.get("password")
        if not isinstance(effective_password, str) or not effective_password:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Garmin password is required")
        with self._lock:
            updated_user = replace(
                user, name=full_name.strip(), default_pace=default_pace.strip()
            )
            updated = {**self._users, user.id: updated_user}
            self._write_credentials(
                user.credentials_file, email.strip(), effective_password
            )
            self._write(updated.values())
            self._users = updated
        return {"user": updated_user.public(), "settings": self.settings(user.id)}

    @staticmethod
    def _read_credentials(path: Path) -> dict[str, str]:
        try:
            value = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError:
            return {}
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise WebError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"Could not read Garmin credentials: {exc}",
            ) from exc
        return {
            key: item for key in ("email", "password")
            if isinstance((item := value.get(key)), str)
        }

    @staticmethod
    def _write_credentials(path: Path, email: str, password: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            f"email = {json.dumps(email)}\npassword = {json.dumps(password)}\n",
            encoding="utf-8",
        )
        temporary.replace(path)

    def _write(self, users: Any) -> None:
        assert self.config_path is not None
        lines: list[str] = []
        for user in users:
            lines.extend([
                "[[users]]",
                f"id = {json.dumps(user.id)}",
                f"name = {json.dumps(user.name, ensure_ascii=False)}",
                f"credentials_file = {json.dumps(str(user.credentials_file))}",
                f"token_store = {json.dumps(str(user.token_store))}",
                f"state_dir = {json.dumps(str(user.state_directory))}",
                f"default_pace = {json.dumps(user.default_pace)}",
                "",
            ])
        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.config_path.with_suffix(".tmp")
        temporary.write_text("\n".join(lines), encoding="utf-8")
        temporary.replace(self.config_path)


def load_user_registry(path: Path | None = None) -> UserRegistry:
    """Load web users from the configured TOML file, which may not exist yet."""
    configured = path or Path(os.getenv(
        "RUNPLAN_USERS_FILE", "~/.config/runplan/users.toml"
    ))
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
    users: list[RunplanUser] = []
    for index, entry in enumerate(entries, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"{configured}: users[{index}] must be a table")
        user_id, name = entry.get("id"), entry.get("name")
        if not isinstance(user_id, str) or not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", user_id):
            raise ValueError(f"{configured}: users[{index}].id is invalid")
        if not isinstance(name, str) or not name.strip():
            raise ValueError(f"{configured}: users[{index}].name is required")
        default_pace = entry.get(
            "default_pace", os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km")
        )
        if not isinstance(default_pace, str):
            raise ValueError(f"{configured}: users[{index}].default_pace is invalid")
        try:
            parse_pace(default_pace, f"users[{index}].default_pace")
        except ValueError as exc:
            raise ValueError(f"{configured}: {exc}") from exc
        def configured_path(field: str, fallback: str) -> Path:
            value = entry.get(field, fallback)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"{configured}: users[{index}].{field} is invalid")
            result = Path(value).expanduser()
            return result if result.is_absolute() else configured.parent / result
        users.append(RunplanUser(
            id=user_id,
            name=name.strip(),
            credentials_file=configured_path("credentials_file", f"credentials-{user_id}.toml"),
            token_store=configured_path("token_store", f"tokens/{user_id}"),
            state_directory=configured_path("state_dir", f"state/{user_id}"),
            default_pace=default_pace,
        ))
    return UserRegistry(users, config_path=configured)


def _revision(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _editable_yaml() -> YAML:
    parser = YAML()
    parser.preserve_quotes = True
    parser.width = 4096
    parser.indent(mapping=2, sequence=4, offset=2)
    return parser


def _load_editable_yaml(text: str) -> Any:
    """Parse YAML while retaining presentation details needed by the editor."""
    return _editable_yaml().load(text)


def _dump_editable_yaml(value: Any) -> str:
    """Render round-trip YAML without introducing display-only line wrapping."""
    stream = StringIO()
    _editable_yaml().dump(value, stream)
    return stream.getvalue()


class ProgramStore:
    """Confined filesystem storage for YAML program documents."""

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
        """Validate and atomically store a new YAML program."""
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
            raw = _load_editable_yaml(content)
        except RoundTripYAMLError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid YAML: {exc}") from exc
        if not isinstance(raw, dict):
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Program YAML must be an object")
        try:
            load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        temporary = path.with_suffix(path.suffix + ".tmp")
        try:
            temporary.write_text(content, encoding="utf-8")
            temporary.replace(path)
        except OSError as exc:
            temporary.unlink(missing_ok=True)
            raise WebError(HTTPStatus.INTERNAL_SERVER_ERROR, "Could not save program") from exc
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
            except (OSError, RoundTripYAMLError, WorkoutDefinitionError):
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
            raw = _load_editable_yaml(text)
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
        path = self.path(name)
        raw, text = self._read(path)
        try:
            model = load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        try:
            pace = parse_pace(
                fallback_pace_value
                or os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"),
                "RUNPLAN_DEFAULT_PACE",
            )
        except ValueError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        fallback_pace = sum(pace) / len(pace)
        lifecycle = self._lifecycle(
            name,
            model.id,
            repository or self.repository,
            fallback_pace_value=fallback_pace_value,
        )
        weeks = []
        raw_weeks = raw["weeks"]
        for week, raw_week in zip(model.weeks, raw_weeks, strict=True):
            workouts = []
            for workout, raw_workout in zip(week.workouts, raw_week["workouts"], strict=True):
                estimate = estimate_steps(workout.steps, fallback_pace)
                workouts.append(
                    {
                        "id": workout.id,
                        "day": workout.day,
                        "name": workout.name,
                        "description": workout.description,
                        "date": workout.schedule_date.isoformat(),
                        "estimated_distance_meters": estimate.distance_meters,
                        "estimated_duration_seconds": estimate.duration_seconds,
                        "distance_is_approximate": estimate.distance_is_approximate,
                        "duration_is_approximate": estimate.duration_is_approximate,
                        "status": lifecycle.get((week.number, workout.id), "planned"),
                        "yaml": _dump_editable_yaml(raw_workout),
                    }
                )
            weeks.append(
                {
                    "week": week.number,
                    "start_date": (
                        model.start_date + timedelta(weeks=week.number - 1)
                    ).isoformat(),
                    "focus": week.focus,
                    "estimated_distance_meters": sum(
                        workout["estimated_distance_meters"] for workout in workouts
                    ),
                    "distance_is_approximate": any(
                        workout["distance_is_approximate"] for workout in workouts
                    ),
                    "workouts": workouts,
                }
            )
        return {
            "file": path.name,
            "revision": _revision(text),
            "program": {
                "id": model.id,
                "name": model.name,
                "short_name": model.short_name,
                "description": model.description,
                "start_week": model.start_week,
            },
            "weeks": weeks,
        }

    def _lifecycle(
        self,
        name: str,
        program_id: str,
        repository: StateRepository,
        *,
        fallback_pace_value: str | None = None,
    ) -> dict[tuple[int, str], str]:
        """Derive offline calendar states from the current plan and sync state."""
        from .cli import prepare_sync_selections

        try:
            selections = prepare_sync_selections(
                Namespace(
                    yaml_file=self.path(name),
                    select_weeks="all",
                    weeks_ahead=None,
                    delete_all=False,
                    today=None,
                ),
                fallback_pace_value=fallback_pace_value,
            )
            records = repository.load(program_id)["workouts"]
        except (SystemExit, WorkoutDefinitionError, ValueError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

        statuses: dict[tuple[int, str], str] = {}
        terminal = {"completed", "missed", "retired"}
        for program, compiled in selections:
            week = program["week"]
            for definition, workout in compiled:
                record = records.get(f"week-{week:02d}/{definition['id']}")
                if not isinstance(record, dict):
                    continue
                status = record.get("status")
                if status in terminal:
                    statuses[(week, definition["id"])] = status
                elif record.get("date") != definition["schedule_date"]:
                    statuses[(week, definition["id"])] = "changed"
                elif (
                    record.get("content_hash")
                    and record["content_hash"] != workout_content_hash(workout)
                ):
                    statuses[(week, definition["id"])] = "changed"
                elif record.get("schedule_id"):
                    statuses[(week, definition["id"])] = "scheduled"
        return statuses

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

        try:
            load_program_model(raw)
        except WorkoutDefinitionError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        rendered = _dump_editable_yaml(raw)
        self._atomic_write(path, rendered)
        return self.get(
            name,
            repository=repository,
            fallback_pace_value=fallback_pace_value,
        )

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
        occupied = next((item for item in target["workouts"] if item.get("day") == target_day), None)
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
            replacement = _load_editable_yaml(edit["yaml"])
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

    def export(
        self, name: str, format_name: str, *, fallback_pace_value: str | None = None
    ) -> tuple[bytes, str, str]:
        path = self.path(name)
        raw, _ = self._read(path)
        try:
            model = load_program_model(raw)
            pace = parse_pace(
                fallback_pace_value
                or os.getenv("RUNPLAN_DEFAULT_PACE", "6:00 min/km"),
                "defaultPace",
            )
            export = build_program_export(
                model, WeekSelection.all(), fallback_pace_seconds_per_km=sum(pace) / len(pace)
            )
        except (WorkoutDefinitionError, ValueError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        stem = path.stem
        if format_name == "markdown":
            return format_program_markdown(export).encode(), "text/markdown; charset=utf-8", f"{stem}.md"
        if format_name == "yaml":
            return path.read_bytes(), "application/yaml; charset=utf-8", path.name
        if format_name == "pdf":
            with tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / f"{stem}.pdf"
                export_pdf(export, output, False)
                return output.read_bytes(), "application/pdf", output.name
        raise WebError(HTTPStatus.BAD_REQUEST, "Format must be yaml, markdown, or pdf")


def _login_for_web(user: RunplanUser) -> GarminClient:
    """Log in without allowing an MFA prompt to block the HTTP server."""
    from .integrations.garmin.client import login_to_garmin

    def reject_mfa() -> str:
        raise RuntimeError(
            "Garmin requested MFA; authenticate once with the CLI before web sync"
        )

    return login_to_garmin(
        prompt_mfa=reject_mfa,
        credentials_file=user.credentials_file,
        token_store=user.token_store,
    )


class WebSyncService:
    """Prepare and execute confirmed web sync operations."""

    def __init__(
        self,
        store: ProgramStore,
        *,
        users: UserRegistry | None = None,
        repository: StateRepository | None = None,
        client_factory: Callable[[], GarminClient] | None = None,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.store = store
        self.users = users or UserRegistry([RunplanUser(
            id="local-default",
            name="Local user",
            credentials_file=Path(os.getenv(
                "GARMIN_CREDENTIALS_FILE", "~/.config/runplan/credentials.toml"
            )).expanduser(),
            token_store=Path(os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect")).expanduser(),
            state_directory=Path(os.getenv(
                "GARMIN_STATE_DIR", "~/.local/state/runplan"
            )).expanduser(),
        )])
        self.repository = repository
        self.client_factory = client_factory
        self.today = today

    def store_for(self, user_id: str | None) -> ProgramStore:
        user = self.users.get(user_id or self.users.default_id)
        return self.store.for_user(user.id)

    def repository_for(self, user_id: str | None) -> StateRepository:
        user = self.users.get(user_id or self.users.default_id)
        return self.repository or JsonStateRepository(user.state_directory)

    def client_for(self, user_id: str | None) -> GarminClient:
        user = self.users.get(user_id or self.users.default_id)
        return self.client_factory() if self.client_factory else _login_for_web(user)

    def _selections(self, name: str, user_id: str | None = None):
        from .cli import prepare_sync_selections
        from .domain.selectors import WeekSelectionError

        try:
            user = self.users.get(user_id or self.users.default_id)
            return prepare_sync_selections(
                Namespace(
                    yaml_file=self.store_for(user.id).path(name),
                    select_weeks=None,
                    weeks_ahead=None,
                    delete_all=False,
                    today=self.today(),
                ),
                fallback_pace_value=user.default_pace,
            )
        except (WorkoutDefinitionError, WeekSelectionError, ValueError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

    def _all_selections(self, name: str, user_id: str):
        from .cli import prepare_sync_selections

        user = self.users.get(user_id)
        return prepare_sync_selections(
            Namespace(
                yaml_file=self.store_for(user.id).path(name),
                select_weeks="all",
                weeks_ahead=None,
                delete_all=False,
                today=self.today(),
            ),
            fallback_pace_value=user.default_pace,
        )

    @staticmethod
    def _token(user_id: str, revision: str, plan: dict[str, Any]) -> str:
        payload = json.dumps(plan, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(f"{user_id}:{revision}:{payload}".encode()).hexdigest()

    def preview(self, name: str, user_id: str | None = None) -> dict[str, Any]:
        user = self.users.get(user_id or self.users.default_id)
        revision = self.store_for(user.id).revision(name)
        selections = self._selections(name, user.id)
        try:
            plan = plan_program_weeks(
                self.repository_for(user.id), selections, today=self.today()
            ).to_dict()
        except SystemExit as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        return {
            "userId": user.id,
            "revision": revision,
            "confirmationToken": self._token(user.id, revision, plan),
            "plan": plan,
        }

    def execute(self, name: str, request: dict[str, Any]) -> dict[str, Any]:
        user = self.users.get(request.get("userId") or self.users.default_id)
        if not isinstance(request.get("confirmationToken"), str):
            raise WebError(
                HTTPStatus.BAD_REQUEST, "Sync requires a preview confirmation token"
            )
        preview = self.preview(name, user.id)
        if request["confirmationToken"] != preview["confirmationToken"]:
            raise WebError(
                HTTPStatus.CONFLICT,
                "The plan or sync state changed; review the sync preview again",
            )
        selections = self._selections(name, user.id)
        try:
            client = self.client_for(user.id)
            results = synchronize_program_weeks(
                client,
                self.repository_for(user.id),
                selections,
                today=self.today(),
                owner_id=user.id,
            )
        except SystemExit as exc:
            raise WebError(HTTPStatus.BAD_GATEWAY, str(exc)) from exc
        except Exception as exc:
            raise WebError(
                HTTPStatus.BAD_GATEWAY,
                f"Garmin sync failed: {type(exc).__name__}: {exc}",
            ) from exc
        return {
            "userId": user.id,
            "programId": preview["plan"]["programId"],
            "weeks": preview["plan"]["weeks"],
            "results": [result.to_dict() for result in results],
        }

    def recovery_preview(self, name: str, user_id: str | None = None) -> dict[str, Any]:
        user = self.users.get(user_id or self.users.default_id)
        revision = self.store_for(user.id).revision(name)
        try:
            discovery = discover_sync_state(
                self.client_for(user.id),
                self._all_selections(name, user.id),
                owner_id=user.id,
                today=self.today(),
            )
        except Exception as exc:
            raise WebError(
                HTTPStatus.BAD_GATEWAY,
                f"Garmin recovery failed: {type(exc).__name__}: {exc}",
            ) from exc
        token = self._token(user.id, revision, discovery)
        return {
            "userId": user.id,
            "revision": revision,
            "confirmationToken": token,
            "discovery": {key: value for key, value in discovery.items() if key != "records"},
            "_records": discovery["records"],
        }

    def recovery_execute(self, name: str, request: dict[str, Any]) -> dict[str, Any]:
        user = self.users.get(request.get("userId") or self.users.default_id)
        token = request.get("confirmationToken")
        if not isinstance(token, str):
            raise WebError(HTTPStatus.BAD_REQUEST, "Recovery requires a preview confirmation token")
        preview = self.recovery_preview(name, user.id)
        if token != preview["confirmationToken"]:
            raise WebError(
                HTTPStatus.CONFLICT,
                "Garmin data or the local plan changed; review recovery again",
            )
        discovery = {**preview["discovery"], "records": preview["_records"]}
        state = rebuild_sync_state(self.repository_for(user.id), discovery)
        return {
            "userId": user.id,
            "programId": discovery["programId"],
            "recoveredCount": len(state["workouts"]),
            "discovery": preview["discovery"],
        }


def make_handler(
    store: ProgramStore,
    sync_service: WebSyncService | None = None,
    users: UserRegistry | None = None,
) -> type[BaseHTTPRequestHandler]:
    sync = sync_service or WebSyncService(store, users=users)
    registry = users or sync.users

    class RunplanHandler(BaseHTTPRequestHandler):
        server_version = "RunplanWeb/0.1"

        def do_GET(self) -> None:  # noqa: N802
            try:
                self._get()
            except WebError as exc:
                self._json(exc.status, {"error": str(exc)})
            except Exception:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})

        def do_POST(self) -> None:  # noqa: N802
            try:
                payload = self._body()
                if urlsplit(self.path).path == "/api/users":
                    self._json(
                        HTTPStatus.CREATED,
                        {"user": registry.create(
                            payload.get("username"), payload.get("fullName")
                        )},
                    )
                    return
                if urlsplit(self.path).path == "/api/programs":
                    user = registry.get(payload.get("userId"))
                    uploaded = sync.store_for(user.id).upload(
                        payload.get("filename"),
                        payload.get("content"),
                        repository=sync.repository_for(user.id),
                        fallback_pace_value=user.default_pace,
                    )
                    self._json(HTTPStatus.CREATED, uploaded)
                    return
                user_parts = self._api_user_parts(required=False)
                if len(user_parts) == 2 and user_parts[1] == "settings":
                    self._json(
                        HTTPStatus.OK,
                        registry.update_settings(user_parts[0], payload),
                    )
                    return
                parts = self._api_program_parts()
                if len(parts) == 1:
                    user = registry.get(payload.get("userId"))
                    repository = sync.repository_for(user.id)
                    self._json(
                        HTTPStatus.OK,
                        sync.store_for(user.id).edit(
                            parts[0],
                            payload,
                            repository=repository,
                            fallback_pace_value=user.default_pace,
                        ),
                    )
                    return
                if len(parts) == 2 and parts[1] == "sync":
                    self._json(HTTPStatus.OK, sync.execute(parts[0], payload))
                    return
                if len(parts) == 3 and parts[1:] == ["sync", "recovery"]:
                    self._json(HTTPStatus.OK, sync.recovery_execute(parts[0], payload))
                    return
                raise WebError(HTTPStatus.NOT_FOUND, "Not found")
            except WebError as exc:
                self._json(exc.status, {"error": str(exc)})
            except Exception:
                self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})

        def _get(self) -> None:
            parsed = urlsplit(self.path)
            query = parse_qs(parsed.query)
            if parsed.path == "/api/users":
                self._json(HTTPStatus.OK, {"users": registry.list()})
                return
            user_parts = self._api_user_parts(required=False)
            if len(user_parts) == 2 and user_parts[1] == "settings":
                self._json(HTTPStatus.OK, registry.settings(user_parts[0]))
                return
            if parsed.path == "/api/programs":
                user_id = query.get("user", [None])[0]
                user = registry.get(user_id)
                self._json(
                    HTTPStatus.OK,
                    {"programs": sync.store_for(user.id).list()},
                )
                return
            if parsed.path.startswith("/api/programs/"):
                parts = self._api_program_parts()
                user_id = query.get("user", [registry.default_id])[0]
                user = registry.get(user_id)
                if len(parts) == 1:
                    self._json(
                        HTTPStatus.OK,
                        sync.store_for(user.id).get(
                            parts[0],
                            repository=sync.repository_for(user.id),
                            fallback_pace_value=user.default_pace,
                        ),
                    )
                    return
                if len(parts) == 2 and parts[1] == "export":
                    format_name = query.get("format", [""])[0]
                    content, content_type, filename = sync.store_for(user.id).export(
                        parts[0],
                        format_name,
                        fallback_pace_value=user.default_pace,
                    )
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(len(content)))
                    self.end_headers()
                    self.wfile.write(content)
                    return
                if len(parts) == 3 and parts[1:] == ["sync", "preview"]:
                    self._json(HTTPStatus.OK, sync.preview(parts[0], user_id))
                    return
                if len(parts) == 4 and parts[1:] == ["sync", "recovery", "preview"]:
                    preview = sync.recovery_preview(parts[0], user_id)
                    preview.pop("_records", None)
                    self._json(HTTPStatus.OK, preview)
                    return
            assets = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"), "/styles.css": ("styles.css", "text/css")}
            asset = assets.get(parsed.path)
            if asset is None:
                raise WebError(HTTPStatus.NOT_FOUND, "Not found")
            content = (ASSET_DIR / asset[0]).read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{asset[1]}; charset=utf-8")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

        def _api_program_parts(self) -> list[str]:
            path = urlsplit(self.path).path
            prefix = "/api/programs/"
            if not path.startswith(prefix):
                raise WebError(HTTPStatus.NOT_FOUND, "Not found")
            return [unquote(part) for part in path[len(prefix):].split("/") if part]

        def _api_user_parts(self, *, required: bool = True) -> list[str]:
            path = urlsplit(self.path).path
            prefix = "/api/users/"
            if not path.startswith(prefix):
                if required:
                    raise WebError(HTTPStatus.NOT_FOUND, "Not found")
                return []
            return [unquote(part) for part in path[len(prefix):].split("/") if part]

        def _body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise WebError(HTTPStatus.BAD_REQUEST, "Invalid content length") from exc
            if length <= 0 or length > 1_000_000:
                raise WebError(HTTPStatus.BAD_REQUEST, "Request body must be 1 MB or less")
            try:
                payload = json.loads(self.rfile.read(length))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise WebError(HTTPStatus.BAD_REQUEST, "Invalid JSON") from exc
            if not isinstance(payload, dict):
                raise WebError(HTTPStatus.BAD_REQUEST, "JSON body must be an object")
            return payload

        def _json(self, status: HTTPStatus, payload: Any) -> None:
            content = json.dumps(payload, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(content)))
            self.end_headers()
            self.wfile.write(content)

    return RunplanHandler


def serve(host: str, port: int, program_dir: Path) -> int:
    """Serve the web frontend until interrupted."""
    users = load_user_registry()
    program_dir = program_dir.expanduser()
    program_dir.mkdir(parents=True, exist_ok=True)
    store = ProgramStore(program_dir, user_scoped=True)
    server = ThreadingHTTPServer((host, port), make_handler(store, users=users))
    print("WARNING: Runplan web has no authentication; use only on a trusted network.")
    print(f"Serving {store.root} for {len(users.list())} user(s) on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopping Runplan web.")
    finally:
        server.server_close()
    return 0


__all__ = [
    "ProgramStore",
    "RunplanUser",
    "UserRegistry",
    "WebError",
    "WebSyncService",
    "load_user_registry",
    "make_handler",
    "serve",
]
