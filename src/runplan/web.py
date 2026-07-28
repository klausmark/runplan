"""Small dependency-free HTTP adapter for the Runplan web MVP."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import copy
from argparse import Namespace
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
from .state.yaml_repository import YamlStateRepository, tracking_from_record
from .users import RunplanUser, UserRegistry, WebError, load_user_registry


ASSET_DIR = Path(__file__).with_name("web_assets")


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
                record = lifecycle.get((week.number, workout.id), {})
                status = record.get("display_status", record.get("status", "planned"))
                actual_distance = record.get("actual_distance_meters")
                actual_duration = record.get("actual_duration_seconds")
                if status == "completed" and actual_distance is not None and actual_duration is not None:
                    effective_distance = actual_distance
                    effective_duration = actual_duration
                    actual = True
                elif status in ("missed", "retired"):
                    effective_distance = effective_duration = 0.0
                    actual = False
                else:
                    effective_distance = estimate.distance_meters
                    effective_duration = estimate.duration_seconds
                    actual = False
                editable = copy.deepcopy(raw_workout)
                if "tracking" not in editable and record:
                    editable["tracking"] = tracking_from_record(record)
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
                        "status": status,
                        "actual_distance_meters": actual_distance,
                        "actual_duration_seconds": actual_duration,
                        "effective_distance_meters": effective_distance,
                        "effective_duration_seconds": effective_duration,
                        "totals_are_actual": actual,
                        "yaml": _dump_editable_yaml(editable),
                    }
                )
            weeks.append(
                {
                    "week": week.number,
                    "start_date": (
                        model.start_date + timedelta(weeks=week.number - 1)
                    ).isoformat(),
                    "focus": week.focus,
                    "effective_distance_meters": sum(
                        workout["effective_distance_meters"] for workout in workouts
                    ),
                    "effective_duration_seconds": sum(
                        workout["effective_duration_seconds"] for workout in workouts
                    ),
                    "estimated_distance_meters": sum(
                        workout["effective_distance_meters"] for workout in workouts
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
    ) -> dict[tuple[int, str], dict[str, Any]]:
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

        statuses: dict[tuple[int, str], dict[str, Any]] = {}
        terminal = {"completed", "missed", "retired"}
        for program, compiled in selections:
            week = program["week"]
            for definition, workout in compiled:
                record = records.get(f"week-{week:02d}/{definition['id']}")
                if not isinstance(record, dict):
                    continue
                status = record.get("status")
                view_record = dict(record)
                if status in terminal:
                    statuses[(week, definition["id"])] = view_record
                elif record.get("date") != definition["schedule_date"]:
                    view_record["display_status"] = "changed"
                    statuses[(week, definition["id"])] = view_record
                elif (
                    record.get("content_hash")
                    and record["content_hash"] != workout_content_hash(workout)
                ):
                    view_record["display_status"] = "changed"
                    statuses[(week, definition["id"])] = view_record
                elif record.get("schedule_id"):
                    view_record["status"] = "scheduled"
                    statuses[(week, definition["id"])] = view_record
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

    def repository_for(self, user_id: str | None, name: str | None = None) -> StateRepository:
        user = self.users.get(user_id or self.users.default_id)
        if self.repository is not None:
            return self.repository
        if name is None:
            if user.active_program is None:
                return JsonStateRepository(user.state_directory)
            name = user.active_program
        return YamlStateRepository(
            self.store_for(user.id).path(name),
            legacy_directory=user.state_directory,
            owner_id=user.id,
        )

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
                self.repository_for(user.id, name), selections, today=self.today()
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
                self.repository_for(user.id, name),
                selections,
                today=self.today(),
                owner_id=user.id,
                active_plan_selections=self._all_selections(name, user.id),
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
        state = rebuild_sync_state(self.repository_for(user.id, name), discovery)
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
                        repository=sync.repository_for(user.id, payload.get("filename")),
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
                if len(user_parts) == 2 and user_parts[1] == "active-program":
                    user = registry.get(user_parts[0])
                    filename = payload.get("filename")
                    if not isinstance(filename, str):
                        raise WebError(
                            HTTPStatus.BAD_REQUEST, "Program filename is required"
                        )
                    path = sync.store_for(user.id).path(filename)
                    if not path.is_file():
                        raise WebError(HTTPStatus.NOT_FOUND, "Program not found")
                    updated = registry.set_active_program(user.id, filename)
                    self._json(HTTPStatus.OK, {"user": updated.public()})
                    return
                parts = self._api_program_parts()
                if len(parts) == 1:
                    user = registry.get(payload.get("userId"))
                    repository = sync.repository_for(user.id, parts[0])
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
                            repository=sync.repository_for(user.id, parts[0]),
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
            assets = {
                "/": ("index.html", "text/html"),
                "/app.js": ("app.js", "text/javascript"),
                "/styles.css": ("styles.css", "text/css"),
                "/favicon.svg": ("favicon.svg", "image/svg+xml"),
            }
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
