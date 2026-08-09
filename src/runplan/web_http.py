"""HTTP request routing and serialization for the Runplan web adapter."""

from __future__ import annotations

import json
import logging
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from typing import TYPE_CHECKING, Any
from urllib.parse import parse_qs, unquote, urlsplit

from .users import UserRegistry, WebError
from .web_auth import WebAuthenticator
from .web_auth_http import AuthResponse, WebAuthHttpAdapter
from .web_templates import (
    copy_template_dict_response,
    copy_template_response,
    get_template_response,
    list_templates_response,
)

if TYPE_CHECKING:
    from .web import ProgramStore, WebSyncService

logger = logging.getLogger("runplan.web")


class RunplanHandler(BaseHTTPRequestHandler):
    """Translate HTTP requests to registry, program, and sync operations.

    Structural rationale: the methods implement one HTTP protocol adapter; endpoint
    business operations are delegated to the injected registry, store, and sync services.
    """

    sync: WebSyncService
    registry: UserRegistry
    auth: WebAuthHttpAdapter

    server_version = "RunplanWeb/0.1"

    def log_message(self, format: str, *args: Any) -> None:
        status = args[1] if len(args) > 1 else "unknown"
        logger.debug(
            "HTTP request client=%s method=%s path=%s status=%s",
            self.client_address[0],
            self.command,
            urlsplit(self.path).path,
            status,
        )

    def _log_web_error(self, exc: WebError) -> None:
        cause = exc.__cause__
        level = logging.ERROR if exc.status >= HTTPStatus.INTERNAL_SERVER_ERROR else logging.WARNING
        logger.log(
            level,
            "HTTP request failed client=%s method=%s path=%s status=%d exception=%s cause=%s message=%s",
            self.client_address[0],
            self.command,
            urlsplit(self.path).path,
            exc.status,
            type(exc).__name__,
            type(cause).__name__ if cause is not None else "none",
            exc,
        )

    def do_GET(self) -> None:  # noqa: N802
        self._handle(self._get)

    def do_POST(self) -> None:  # noqa: N802
        self._handle(self._post)

    def _handle(self, operation: Any) -> None:
        try:
            self.auth.authorize(self.path, self.client_address[0], self.headers)
            operation()
        except WebError as exc:
            self._log_web_error(exc)
            self._json(exc.status, {"error": str(exc)}, headers=exc.headers)
        except Exception as exc:
            logger.exception(
                "Unhandled HTTP exception client=%s method=%s path=%s exception=%s",
                self.client_address[0],
                self.command,
                urlsplit(self.path).path,
                type(exc).__name__,
            )
            self._json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": "Internal server error"})

    def _post(self) -> None:
        payload = self._body()
        path = urlsplit(self.path).path
        if response := self.auth.post(path, self.client_address[0], self.headers, payload):
            self._auth_response(response)
            return
        if path == "/api/users":
            self._json(
                HTTPStatus.CREATED,
                {"user": self.registry.create(payload.get("username"), payload.get("fullName"))},
            )
            return
        if path == "/api/programs":
            self._upload_program(payload)
            return
        template_parts = self._api_template_parts()
        if len(template_parts) == 2 and template_parts[1] == "copy":
            self._copy_template(payload)
            return
        user_parts = self._api_user_parts(required=False)
        if len(user_parts) == 2 and user_parts[1] == "settings":
            self._json(HTTPStatus.OK, self.registry.update_settings(user_parts[0], payload))
            return
        if len(user_parts) == 2 and user_parts[1] == "active-program":
            self._set_active_program(user_parts[0], payload)
            return
        parts = self._api_program_parts()
        if len(parts) == 1:
            self._edit_program(parts[0], payload)
            return
        if len(parts) == 2 and parts[1] == "sync":
            self._json(HTTPStatus.OK, self.sync.execute(parts[0], payload))
            return
        if len(parts) == 5 and parts[1] == "workouts":
            if parts[4] == "activity-links":
                self._json(
                    HTTPStatus.OK,
                    self.sync.activity_links.apply(parts[0], parts[2], parts[3], payload),
                )
                return
        raise WebError(HTTPStatus.NOT_FOUND, "Not found")

    def _upload_program(self, payload: dict[str, Any]) -> None:
        user = self.registry.get(payload.get("userId"))
        filename = payload.get("filename")
        uploaded = self.sync.store_for(user.id).upload(
            filename,
            payload.get("content"),
            repository=self.sync.repository_for(user.id, filename),
            fallback_pace_value=user.default_pace,
        )
        self._json(HTTPStatus.CREATED, uploaded)

    def _copy_template(self, payload: dict[str, Any]) -> None:
        template_parts = self._api_template_parts()
        if len(template_parts) != 2 or template_parts[1] != "copy":
            raise WebError(HTTPStatus.NOT_FOUND, "Not found")
        template_id = template_parts[0]
        try:
            response = copy_template_response(template_id, payload)
        except ValueError as exc:
            raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
        except KeyError as exc:
            raise WebError(HTTPStatus.NOT_FOUND, str(exc)) from exc
        self._json(HTTPStatus.OK, response)

    def _set_active_program(self, user_id: str, payload: dict[str, Any]) -> None:
        user = self.registry.get(user_id)
        filename = payload.get("filename")
        if not isinstance(filename, str):
            raise WebError(HTTPStatus.BAD_REQUEST, "Program filename is required")
        if not self.sync.store_for(user.id).path(filename).is_file():
            raise WebError(HTTPStatus.NOT_FOUND, "Program not found")
        self._json(
            HTTPStatus.OK, {"user": self.registry.set_active_program(user.id, filename).public()}
        )

    def _edit_program(self, filename: str, payload: dict[str, Any]) -> None:
        user = self.registry.get(payload.get("userId"))
        self._json(
            HTTPStatus.OK,
            self.sync.store_for(user.id).edit(
                filename,
                payload,
                repository=self.sync.repository_for(user.id, filename),
                fallback_pace_value=user.default_pace,
            ),
        )

    def _get(self) -> None:
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if response := self.auth.get(parsed.path, self.client_address[0], self.headers):
            self._auth_response(response)
            return
        if parsed.path == "/api/users":
            self._json(HTTPStatus.OK, {"users": self.registry.list()})
            return
        if parsed.path == "/api/templates":
            self._json(HTTPStatus.OK, list_templates_response())
            return
        template_parts = self._api_template_parts()
        if len(template_parts) == 1:
            try:
                self._json(HTTPStatus.OK, get_template_response(template_parts[0]))
            except KeyError as exc:
                raise WebError(HTTPStatus.NOT_FOUND, str(exc)) from exc
            return
        if len(template_parts) == 3 and template_parts[1] == "preview":
            self._json(HTTPStatus.OK, copy_template_dict_response(template_parts[0], query))
            return
        user_parts = self._api_user_parts(required=False)
        if len(user_parts) == 2 and user_parts[1] == "settings":
            self._json(HTTPStatus.OK, self.registry.settings(user_parts[0]))
            return
        if parsed.path == "/api/programs":
            user = self.registry.get(query.get("user", [None])[0])
            self._json(HTTPStatus.OK, {"programs": self.sync.store_for(user.id).list()})
            return
        if parsed.path.startswith("/api/programs/"):
            self._get_program(query)
            return
        self._asset(parsed.path)

    def _get_program(self, query: dict[str, list[str]]) -> None:
        parts = self._api_program_parts()
        user_id = query.get("user", [self.registry.default_id])[0]
        user = self.registry.get(user_id)
        if len(parts) == 1:
            self._json(
                HTTPStatus.OK,
                self.sync.store_for(user.id).get(
                    parts[0],
                    repository=self.sync.repository_for(user.id, parts[0]),
                    fallback_pace_value=user.default_pace,
                ),
            )
            return
        if len(parts) == 2 and parts[1] == "export":
            content, content_type, filename = self.sync.store_for(user.id).export(
                parts[0],
                query.get("format", [""])[0],
                fallback_pace_value=user.default_pace,
            )
            self._bytes(content, content_type, filename)
            return
        if len(parts) == 3 and parts[1:] == ["sync", "preview"]:
            self._json(HTTPStatus.OK, self.sync.preview(parts[0], user_id))
            return
        if len(parts) == 5 and parts[1] == "workouts" and parts[4] == "activities":
            self._json(
                HTTPStatus.OK,
                self.sync.activity_links.candidates(
                    parts[0],
                    parts[2],
                    parts[3],
                    user_id,
                ),
            )
            return
        raise WebError(HTTPStatus.NOT_FOUND, "Not found")

    def _asset(self, path: str) -> None:
        from .web import ASSET_DIR

        assets = {
            "/": ("index.html", "text/html"),
            "/app.js": ("app.js", "text/javascript"),
            "/styles.css": ("styles.css", "text/css"),
            "/favicon.svg": ("favicon.svg", "image/svg+xml"),
        }
        asset = assets.get(path)
        if asset is None:
            raise WebError(HTTPStatus.NOT_FOUND, "Not found")
        content = (ASSET_DIR / asset[0]).read_bytes()
        self._bytes(content, f"{asset[1]}; charset=utf-8")

    def _bytes(self, content: bytes, content_type: str, filename: str | None = None) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        if filename:
            self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _api_program_parts(self) -> list[str]:
        return self._api_parts("/api/programs/", required=True)

    def _api_template_parts(self) -> list[str]:
        return self._api_parts("/api/templates/", required=False)

    def _api_user_parts(self, *, required: bool = True) -> list[str]:
        return self._api_parts("/api/users/", required=required)

    def _api_parts(self, prefix: str, *, required: bool) -> list[str]:
        path = urlsplit(self.path).path
        if not path.startswith(prefix):
            if required:
                raise WebError(HTTPStatus.NOT_FOUND, "Not found")
            return []
        return [unquote(part) for part in path[len(prefix) :].split("/") if part]

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

    def _json(
        self,
        status: HTTPStatus,
        payload: Any,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        content = json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _auth_response(self, response: AuthResponse) -> None:
        self._json(response.status, response.payload, headers=response.headers)


def make_handler(
    store: ProgramStore,
    sync_service: WebSyncService | None = None,
    users: UserRegistry | None = None,
    authenticator: WebAuthenticator | None = None,
) -> type[BaseHTTPRequestHandler]:
    """Bind an HTTP adapter subclass to the supplied application services."""
    if sync_service is None:
        from .web import WebSyncService

        sync_service = WebSyncService(store, users=users)
    registry = users or sync_service.users
    authenticator = authenticator or WebAuthenticator.from_environment()
    auth = WebAuthHttpAdapter(authenticator)
    return type(
        "ConfiguredRunplanHandler",
        (RunplanHandler,),
        {"sync": sync_service, "registry": registry, "auth": auth},
    )
