"""HTTP protocol mapping for the Runplan web authenticator."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from typing import Any
from urllib.parse import urlsplit

from .users import WebError
from .web_auth import COOKIE_NAME, WebAuthenticator


@dataclass(frozen=True)
class AuthResponse:
    status: HTTPStatus
    payload: dict[str, Any]
    headers: dict[str, str] | None = None


class WebAuthHttpAdapter:
    """Gate application APIs and map the three authentication endpoints."""

    def __init__(self, authenticator: WebAuthenticator) -> None:
        self.authenticator = authenticator

    @staticmethod
    def _forwarded_proto(headers: Mapping[str, str]) -> str | None:
        return headers.get("X-Forwarded-Proto")

    @staticmethod
    def _cookie(headers: Mapping[str, str]) -> str | None:
        cookie = SimpleCookie()
        try:
            cookie.load(headers.get("Cookie", ""))
        except Exception:
            return None
        morsel = cookie.get(COOKIE_NAME)
        return morsel.value if morsel is not None else None

    def authorize(self, request_path: str, peer: str, headers: Mapping[str, str]) -> None:
        path = urlsplit(request_path).path
        if not path.startswith("/api/") or path in {"/api/health", "/api/auth/status"}:
            return
        self.authenticator.require_secure_transport(peer, self._forwarded_proto(headers))
        if path in {"/api/auth/challenge", "/api/auth/login"}:
            return
        if not self.authenticator.is_authorized(self._cookie(headers)):
            raise WebError(HTTPStatus.UNAUTHORIZED, "Authentication required")

    def get(self, request_path: str, peer: str, headers: Mapping[str, str]) -> AuthResponse | None:
        path = urlsplit(request_path).path
        if path == "/api/health":
            return AuthResponse(HTTPStatus.OK, {"status": "ok"})
        if path == "/api/auth/status":
            return AuthResponse(
                HTTPStatus.OK,
                {"authenticated": self.authenticator.is_authorized(self._cookie(headers))},
            )
        if path == "/api/auth/challenge":
            return AuthResponse(HTTPStatus.OK, self.authenticator.issue_challenge(peer))
        return None

    def post(
        self,
        request_path: str,
        peer: str,
        headers: Mapping[str, str],
        payload: Mapping[str, Any],
    ) -> AuthResponse | None:
        if urlsplit(request_path).path != "/api/auth/login":
            return None
        self.authenticator.verify_login(peer, payload)
        secure = (self._forwarded_proto(headers) or "").split(",", 1)[0].strip().lower() == "https"
        return AuthResponse(
            HTTPStatus.OK,
            {"authenticated": True},
            {"Set-Cookie": self.authenticator.cookie_header(secure=secure)},
        )
