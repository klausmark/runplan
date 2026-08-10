"""Small dependency-free HTTP adapter for the Runplan web MVP."""

from __future__ import annotations

import hashlib
import json
import logging
import os
from argparse import Namespace
from collections.abc import Callable
from datetime import date
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from typing import Any

from ruamel.yaml.error import YAMLError as RoundTripYAMLError

from .application.ports import GarminClient, StateRepository
from .application.sync import (
    plan_program_weeks,
    synchronize_program_weeks,
)
from .domain.errors import WorkoutDefinitionError
from .integrations.garmin.client import login_to_garmin
from .integrations.garmin.logging_client import LoggingGarminClient
from .logging_config import configure_server_logging
from .state.json_repository import JsonStateRepository
from .state.yaml_repository import YamlStateRepository
from .users import RunplanUser, UserRegistry, WebError, load_user_registry
from .web_auth import WebAuthenticator
from .web_http import make_handler
from .web_programs import ProgramStore
from .web_yaml import load_editable_yaml

ASSET_DIR = Path(__file__).with_name("web_assets")
logger = logging.getLogger(__name__)


def _login_for_web(user: RunplanUser) -> GarminClient:
    """Log in without allowing an MFA prompt to block the HTTP server."""

    def reject_mfa() -> str:
        raise RuntimeError("Garmin requested MFA; authenticate once with the CLI before web sync")

    logger.info("Garmin login started user=%s", user.id)
    try:
        client = login_to_garmin(
            prompt_mfa=reject_mfa,
            credentials_file=user.credentials_file,
            token_store=user.token_store,
        )
    except BaseException as exc:
        logger.exception("Garmin login failed user=%s", user.id)
        try:
            exc._runplan_logged = True
        except Exception:
            pass
        raise
    logger.info("Garmin login succeeded user=%s", user.id)
    return client


class WebSyncService:
    """Provide the web application's synchronization boundary.

    Structural rationale: the facade owns dependency selection and preview/confirmation;
    mutation execution and response mapping are delegated.
    """

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
        self.users = users or UserRegistry(
            [
                RunplanUser(
                    id="local-default",
                    name="Local user",
                    credentials_file=Path(
                        os.getenv("GARMIN_CREDENTIALS_FILE", "~/.config/runplan/credentials.toml")
                    ).expanduser(),
                    token_store=Path(
                        os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect")
                    ).expanduser(),
                    state_directory=Path(
                        os.getenv("GARMIN_STATE_DIR", "~/.local/state/runplan")
                    ).expanduser(),
                )
            ]
        )
        self.repository = repository
        self.client_factory = client_factory
        self.today = today
        from .web_activity_links import WebActivityLinkService

        self.activity_links = WebActivityLinkService(self)

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
        )

    def client_for(self, user_id: str | None) -> GarminClient:
        user = self.users.get(user_id or self.users.default_id)
        client = self.client_factory() if self.client_factory else _login_for_web(user)
        if isinstance(client, LoggingGarminClient):
            return client
        return LoggingGarminClient(client, user_id=user.id)

    def _selections(self, name: str, user_id: str | None = None):
        from .cli import prepare_sync_selections
        from .domain.selectors import WeekSelectionError

        try:
            user = self.users.get(user_id or self.users.default_id)
            return prepare_sync_selections(
                Namespace(
                    yaml_file=self.store_for(user.id).path(name),
                    select_weeks="all",
                    weeks_ahead=None,
                    delete_all=False,
                    today=self.today(),
                ),
                fallback_pace_value=user.five_k_best,
                pace_zone_seconds_per_km=user.pace_zone_seconds_per_km,
            )
        except (WorkoutDefinitionError, WeekSelectionError, ValueError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc

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
        from .web_sync_execution import execute_confirmed_sync

        return execute_confirmed_sync(self, name, request, synchronize_program_weeks)

    def delete_program(self, user_id: str | None, filename: str) -> dict[str, Any]:
        """Remove a program, its local state, and any Garmin-owned workouts.

        Structural rationale: Garmin-side cleanup runs before local file removal so
        the live network error surfaces while rollback is still possible; the YAML
        and active-program pointer are cleared only after the destructive network
        calls succeed. Programs with no tracked Garmin workouts skip the login
        entirely so accounts without Garmin credentials can still clean up local
        state.
        """
        from .application.sync_cleanup import delete_managed_workouts

        user = self.users.get(user_id or self.users.default_id)
        store = self.store_for(user.id)
        path = store.path(filename)
        if not path.is_file():
            raise WebError(HTTPStatus.NOT_FOUND, "Program not found")
        try:
            raw = load_editable_yaml(path.read_text(encoding="utf-8"))
        except (OSError, RoundTripYAMLError) as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, f"Invalid YAML: {exc}") from exc
        program_id = raw.get("program", {}).get("id") if isinstance(raw, dict) else None
        if not isinstance(program_id, str) or not program_id:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, "Program is missing a program.id")

        repository = self.repository_for(user.id, filename)
        state = repository.load(program_id)
        needs_garmin = any(
            isinstance(record, dict) and (record.get("workout_id") or record.get("schedule_id"))
            for record in state.get("workouts", {}).values()
        )

        if needs_garmin:
            client = self.client_for(user.id)
            delete_managed_workouts(client, repository, {"program_id": program_id}, [])

        store.delete(filename)

        cleared = False
        if user.active_program == filename:
            self.users.clear_active_program(user.id)
            cleared = True

        logger.info(
            "Program deleted user=%s file=%s program_id=%s garmin_cleaned_up=%s active_program_cleared=%s",
            user.id,
            filename,
            program_id,
            needs_garmin,
            cleared,
        )
        return {
            "deleted": filename,
            "activeProgramCleared": cleared,
            "garminCleanedUp": needs_garmin,
        }


def serve(host: str, port: int, program_dir: Path, *, log_level: str = "INFO") -> int:
    """Serve the web frontend until interrupted."""
    configure_server_logging(log_level)
    try:
        users = load_user_registry()
        program_dir = program_dir.expanduser()
        program_dir.mkdir(parents=True, exist_ok=True)
        store = ProgramStore(program_dir, user_scoped=True)
        authenticator = WebAuthenticator.from_environment()
        server = ThreadingHTTPServer(
            (host, port), make_handler(store, users=users, authenticator=authenticator)
        )
    except BaseException:
        logger.critical(
            "Runplan server startup failed host=%s port=%s program_dir=%s",
            host,
            port,
            program_dir,
            exc_info=True,
        )
        raise
    logger.info(
        "Runplan server started root=%s users=%d url=http://%s:%s log_level=%s auth=enabled",
        store.root,
        len(users.list()),
        host,
        port,
        log_level,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Runplan server interrupted")
    except BaseException:
        logger.exception("Runplan server failed while serving")
        raise
    finally:
        server.server_close()
        logger.info("Runplan server stopped")
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
