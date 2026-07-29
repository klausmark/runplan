"""Single-password authentication for the Runplan web adapter."""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import logging
import os
import secrets
import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from http import HTTPStatus
from typing import Any

from .users import WebError

logger = logging.getLogger(__name__)

ALGORITHM = "PBKDF2-HMAC-SHA256"
HASH_PREFIX = "pbkdf2_sha256"
PBKDF2_ITERATIONS = 600_000
SALT_BYTES = 16
KEY_BYTES = 32
CHALLENGE_SECONDS = 60
MAX_CHALLENGES = 256
FAILURE_WINDOW_SECONDS = 300
MAX_FAILURES = 5
BLOCK_SECONDS = 60
COOKIE_NAME = "runplan_auth"
COOKIE_MAX_AGE = 315_360_000


def _encode(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _decode(value: str) -> bytes:
    if not isinstance(value, str):
        raise ValueError("value is not text")
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def derive_password_key(password: str, salt: bytes, iterations: int = PBKDF2_ITERATIONS) -> bytes:
    """Derive the browser-compatible proof key for one password."""
    return hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations, KEY_BYTES)


def format_password_hash(password: str, *, salt: bytes | None = None) -> str:
    """Return an encoded, salted verifier suitable for RUNPLAN_WEB_PASSWORD_HASH."""
    if not password:
        raise ValueError("Web password must not be empty")
    chosen_salt = salt or secrets.token_bytes(SALT_BYTES)
    verifier = derive_password_key(password, chosen_salt)
    return f"{HASH_PREFIX}:{PBKDF2_ITERATIONS}:{_encode(chosen_salt)}:{_encode(verifier)}"


def parse_password_hash(value: str) -> tuple[int, bytes, bytes]:
    """Validate and decode the configured password verifier."""
    try:
        prefix, iterations_text, salt_text, verifier_text = value.split(":")
        iterations = int(iterations_text)
        salt = _decode(salt_text)
        verifier = _decode(verifier_text)
    except (AttributeError, ValueError, TypeError) as exc:
        raise ValueError("RUNPLAN_WEB_PASSWORD_HASH has an invalid format") from exc
    if prefix != HASH_PREFIX or iterations < PBKDF2_ITERATIONS:
        raise ValueError("RUNPLAN_WEB_PASSWORD_HASH uses an unsupported algorithm or work factor")
    if len(salt) != SALT_BYTES or len(verifier) != KEY_BYTES:
        raise ValueError("RUNPLAN_WEB_PASSWORD_HASH has an invalid salt or verifier")
    return iterations, salt, verifier


def _environment_bool(environment: Mapping[str, str], name: str, default: bool) -> bool:
    value = environment.get(name)
    if value is None:
        return default
    normalized = value.strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"{name} must be true or false")


@dataclass
class _Challenge:
    nonce: bytes
    peer: str
    expires_at: float


@dataclass
class _Failures:
    attempts: deque[float]
    blocked_until: float = 0


class WebAuthenticator:
    """Issue one-time login challenges and validate persistent auth cookies."""

    def __init__(
        self,
        *,
        iterations: int,
        salt: bytes,
        proof_key: bytes,
        cookie_key: bytes,
        require_https: bool = True,
        trust_proxy: bool = False,
        clock: Callable[[], float] = time.monotonic,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self.iterations = iterations
        self.salt = salt
        self.proof_key = proof_key
        self.require_https = require_https
        self.trust_proxy = trust_proxy
        self.clock = clock
        self.random_bytes = random_bytes
        self._cookie_value = _encode(hmac.digest(cookie_key, b"runplan-auth-cookie-v1", "sha256"))
        self._challenges: dict[str, _Challenge] = {}
        self._failures: dict[str, _Failures] = {}
        self._lock = threading.RLock()

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        **overrides: Any,
    ) -> WebAuthenticator:
        """Build the authenticator from exactly one supported password source."""
        values = os.environ if environment is None else environment
        encoded_hash = values.get("RUNPLAN_WEB_PASSWORD_HASH", "").strip()
        password = values.get("RUNPLAN_WEB_PASSWORD", "")
        if bool(encoded_hash) == bool(password):
            raise ValueError("Set exactly one of RUNPLAN_WEB_PASSWORD_HASH or RUNPLAN_WEB_PASSWORD")
        if encoded_hash:
            iterations, salt, proof_key = parse_password_hash(encoded_hash)
            cookie_key = hmac.digest(proof_key, b"runplan-auth-cookie-key-v1", "sha256")
        else:
            logger.warning(
                "RUNPLAN_WEB_PASSWORD contains a raw password; use RUNPLAN_WEB_PASSWORD_HASH"
            )
            iterations = PBKDF2_ITERATIONS
            salt = secrets.token_bytes(SALT_BYTES)
            proof_key = derive_password_key(password, salt, iterations)
            cookie_key = hmac.digest(
                password.encode("utf-8"), b"runplan-auth-raw-cookie-key-v1", "sha256"
            )
        return cls(
            iterations=iterations,
            salt=salt,
            proof_key=proof_key,
            cookie_key=cookie_key,
            require_https=_environment_bool(values, "RUNPLAN_WEB_REQUIRE_HTTPS", True),
            trust_proxy=_environment_bool(values, "RUNPLAN_WEB_TRUST_PROXY", False),
            **overrides,
        )

    def _prune_challenges(self, now: float) -> None:
        self._challenges = {
            key: challenge
            for key, challenge in self._challenges.items()
            if challenge.expires_at > now
        }
        while len(self._challenges) >= MAX_CHALLENGES:
            self._challenges.pop(next(iter(self._challenges)))

    def transport_is_secure(self, peer: str, forwarded_proto: str | None) -> bool:
        """Return whether auth may be used over the represented transport."""
        try:
            if ipaddress.ip_address(peer).is_loopback:
                return True
        except ValueError:
            pass
        if not self.require_https:
            return True
        return (
            self.trust_proxy and (forwarded_proto or "").split(",", 1)[0].strip().lower() == "https"
        )

    def require_secure_transport(self, peer: str, forwarded_proto: str | None) -> None:
        if not self.transport_is_secure(peer, forwarded_proto):
            raise WebError(
                HTTPStatus.UPGRADE_REQUIRED,
                "HTTPS is required for Runplan web authentication",
            )

    def issue_challenge(self, peer: str) -> dict[str, Any]:
        with self._lock:
            now = self.clock()
            self._prune_challenges(now)
            challenge_id = _encode(self.random_bytes(18))
            nonce = self.random_bytes(32)
            self._challenges[challenge_id] = _Challenge(nonce, peer, now + CHALLENGE_SECONDS)
        return {
            "challengeId": challenge_id,
            "nonce": _encode(nonce),
            "salt": _encode(self.salt),
            "iterations": self.iterations,
            "algorithm": ALGORITHM,
        }

    def _failure_state(self, peer: str, now: float) -> _Failures:
        state = self._failures.setdefault(peer, _Failures(deque()))
        while state.attempts and state.attempts[0] <= now - FAILURE_WINDOW_SECONDS:
            state.attempts.popleft()
        if state.blocked_until <= now:
            state.blocked_until = 0
        return state

    def retry_after(self, peer: str) -> int:
        with self._lock:
            state = self._failure_state(peer, self.clock())
            return max(0, int(state.blocked_until - self.clock() + 0.999))

    def verify_login(self, peer: str, payload: Mapping[str, Any]) -> None:
        with self._lock:
            now = self.clock()
            state = self._failure_state(peer, now)
            if state.blocked_until > now:
                raise WebError(
                    HTTPStatus.TOO_MANY_REQUESTS,
                    "Too many failed login attempts",
                    headers={"Retry-After": str(self.retry_after(peer))},
                )
            challenge_id = payload.get("challengeId")
            proof = payload.get("proof")
            challenge = self._challenges.pop(challenge_id, None)
            valid = False
            if challenge is not None and challenge.peer == peer and challenge.expires_at > now:
                expected = _encode(hmac.digest(self.proof_key, challenge.nonce, "sha256"))
                valid = isinstance(proof, str) and hmac.compare_digest(expected, proof)
            if not valid:
                state.attempts.append(now)
                if len(state.attempts) >= MAX_FAILURES:
                    state.blocked_until = now + BLOCK_SECONDS
                raise WebError(HTTPStatus.UNAUTHORIZED, "Incorrect password")
            self._failures.pop(peer, None)

    def is_authorized(self, cookie_value: str | None) -> bool:
        return isinstance(cookie_value, str) and hmac.compare_digest(
            self._cookie_value, cookie_value
        )

    def cookie_header(self, *, secure: bool) -> str:
        parts = [
            f"{COOKIE_NAME}={self._cookie_value}",
            "Path=/",
            f"Max-Age={COOKIE_MAX_AGE}",
            "HttpOnly",
            "SameSite=Strict",
        ]
        if secure:
            parts.append("Secure")
        return "; ".join(parts)


def login_proof(password: str, challenge: Mapping[str, Any]) -> str:
    """Build a proof in Python for tests and non-browser clients."""
    key = derive_password_key(password, _decode(challenge["salt"]), challenge["iterations"])
    return _encode(hmac.digest(key, _decode(challenge["nonce"]), "sha256"))
