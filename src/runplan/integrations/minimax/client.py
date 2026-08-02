"""Synchronous MiniMax chat-completions client."""

from __future__ import annotations

import json
import math
import os
from collections.abc import Mapping
from dataclasses import dataclass
from http.client import HTTPResponse
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ENDPOINT = "https://api.minimax.io/v1/chat/completions"
MODEL = "MiniMax-M3"
TIMEOUT_SECONDS = 600.0
MIN_TIMEOUT_SECONDS = 30.0
MAX_TIMEOUT_SECONDS = 900.0
MAX_COMPLETION_TOKENS = 131_072
MAX_PROMPT_BYTES = 256 * 1024
MAX_REQUEST_BYTES = 300 * 1024
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class MiniMaxError(RuntimeError):
    """Base class for safe MiniMax adapter failures."""


class MiniMaxUnconfiguredError(MiniMaxError):
    """Raised when generation is requested without an API key."""


class MiniMaxAuthenticationError(MiniMaxError):
    """Raised when MiniMax rejects the configured key."""


class MiniMaxRateLimitError(MiniMaxError):
    """Raised when MiniMax reports a quota or rate limit."""


class MiniMaxTimeoutError(MiniMaxError):
    """Raised when the MiniMax request times out."""


class MiniMaxUpstreamError(MiniMaxError):
    """Raised for unavailable or unsuccessful upstream requests."""


class MiniMaxProtocolError(MiniMaxError):
    """Raised for bounded-input or invalid-response failures."""

    def __init__(self, message: str, *, reason: str = "invalid_response") -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class TransportResponse:
    """Bounded HTTP response returned by a MiniMax transport."""

    status: int
    body: bytes


class HttpTransport(Protocol):
    """Minimal injectable synchronous HTTP transport."""

    def send(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
        max_response_bytes: int,
    ) -> TransportResponse: ...


class _ResponseTooLargeError(Exception):
    pass


class UrllibTransport:
    """Stdlib HTTP transport with no retry behavior."""

    def send(
        self,
        *,
        url: str,
        headers: Mapping[str, str],
        body: bytes,
        timeout: float,
        max_response_bytes: int,
    ) -> TransportResponse:
        request = Request(url, data=body, headers=dict(headers), method="POST")
        try:
            with urlopen(request, timeout=timeout) as response:  # noqa: S310 - fixed HTTPS URL
                return TransportResponse(
                    status=response.status,
                    body=_read_bounded(response, max_response_bytes),
                )
        except HTTPError as exc:
            exc.close()
            return TransportResponse(status=exc.code, body=b"")


def _read_bounded(response: HTTPResponse, maximum: int) -> bytes:
    body = response.read(maximum + 1)
    if len(body) > maximum:
        raise _ResponseTooLargeError
    return body


def _transport_response(response: object) -> tuple[int, bytes]:
    try:
        status, body = response.status, response.body  # type: ignore[attr-defined]
    except (AttributeError, TypeError):
        raise MiniMaxProtocolError(
            "MiniMax returned an invalid response", reason="invalid_transport_response"
        ) from None
    if not isinstance(status, int) or isinstance(status, bool) or not isinstance(body, bytes):
        raise MiniMaxProtocolError(
            "MiniMax returned an invalid response", reason="invalid_transport_response"
        )
    if len(body) > MAX_RESPONSE_BYTES:
        raise MiniMaxProtocolError(
            "MiniMax response exceeds the supported size", reason="response_too_large"
        )
    return status, body


def _successful_payload(body: bytes) -> Mapping[str, object]:
    try:
        payload = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise MiniMaxProtocolError(
            "MiniMax returned an invalid response", reason="invalid_json"
        ) from None
    if not isinstance(payload, Mapping):
        raise MiniMaxProtocolError(
            "MiniMax returned an invalid response", reason="invalid_response_root"
        )
    base_response = payload.get("base_resp", {})
    if not isinstance(base_response, Mapping):
        raise MiniMaxProtocolError(
            "MiniMax returned an invalid response", reason="invalid_base_response"
        )
    base_status = base_response.get("status_code", 0)
    if base_status in (1004,):
        raise MiniMaxAuthenticationError("MiniMax authentication failed")
    if base_status in (1002, 1008):
        raise MiniMaxRateLimitError("MiniMax quota or rate limit reached")
    if base_status in (1001,):
        raise MiniMaxTimeoutError("MiniMax request timed out")
    if base_status:
        raise MiniMaxUpstreamError("MiniMax returned an unsuccessful response")
    return payload


def _completion_content(payload: Mapping[str, object]) -> str:
    choices = payload.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], Mapping):
        raise MiniMaxProtocolError("MiniMax returned an invalid response", reason="missing_choices")
    choice = choices[0]
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise MiniMaxProtocolError(
            "MiniMax reached the completion token limit", reason="output_limit"
        )
    if finish_reason == "content_filter":
        raise MiniMaxProtocolError(
            "MiniMax filtered the generated response", reason="content_filtered"
        )
    if finish_reason == "tool_calls":
        raise MiniMaxProtocolError(
            "MiniMax returned an unsupported response", reason="unexpected_tool_call"
        )
    if finish_reason not in (None, "stop"):
        raise MiniMaxProtocolError(
            "MiniMax returned an invalid response", reason="invalid_finish_reason"
        )
    message = choice.get("message")
    if not isinstance(message, Mapping):
        raise MiniMaxProtocolError("MiniMax returned an invalid response", reason="missing_message")
    content = message.get("content")
    if not isinstance(content, str):
        raise MiniMaxProtocolError("MiniMax returned an invalid response", reason="missing_content")
    return content


def _response_content(response: object) -> str:
    status, body = _transport_response(response)
    if status in (401, 403):
        raise MiniMaxAuthenticationError("MiniMax authentication failed")
    if status == 429:
        raise MiniMaxRateLimitError("MiniMax quota or rate limit reached")
    if status in (408, 504):
        raise MiniMaxTimeoutError("MiniMax request timed out")
    if status < 200 or status >= 300:
        raise MiniMaxUpstreamError("MiniMax returned an unsuccessful response")
    return _completion_content(_successful_payload(body))


class MiniMaxClient:
    """Generate text with the fixed MiniMax MVP configuration."""

    def __init__(
        self,
        api_key: str | None,
        *,
        transport: HttpTransport | None = None,
        timeout_seconds: float = TIMEOUT_SECONDS,
    ) -> None:
        if (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(timeout_seconds)
            or not MIN_TIMEOUT_SECONDS <= timeout_seconds <= MAX_TIMEOUT_SECONDS
        ):
            raise ValueError("MiniMax timeout must be from 30 to 900 seconds")
        self._api_key = api_key.strip() if isinstance(api_key, str) and api_key.strip() else None
        self._transport = transport or UrllibTransport()
        self._timeout_seconds = float(timeout_seconds)

    @classmethod
    def from_environment(
        cls,
        environment: Mapping[str, str] | None = None,
        *,
        transport: HttpTransport | None = None,
    ) -> MiniMaxClient:
        values = os.environ if environment is None else environment
        raw_timeout = values.get("RUNPLAN_MINIMAX_TIMEOUT_SECONDS", "").strip()
        if raw_timeout:
            try:
                timeout_seconds = float(raw_timeout)
            except ValueError:
                raise ValueError("MiniMax timeout must be from 30 to 900 seconds") from None
        else:
            timeout_seconds = TIMEOUT_SECONDS
        return cls(
            values.get("RUNPLAN_MINIMAX_API_KEY"),
            transport=transport,
            timeout_seconds=timeout_seconds,
        )

    @property
    def configured(self) -> bool:
        return self._api_key is not None

    def generate(self, prompt: str) -> str:
        if self._api_key is None:
            raise MiniMaxUnconfiguredError("MiniMax plan generation is not configured")
        if not isinstance(prompt, str) or len(prompt.encode("utf-8")) > MAX_PROMPT_BYTES:
            raise MiniMaxProtocolError(
                "MiniMax prompt exceeds the supported size", reason="prompt_too_large"
            )

        body = json.dumps(
            {
                "model": MODEL,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "thinking": {"type": "adaptive"},
                "reasoning_split": True,
                "tools": [],
                "max_completion_tokens": MAX_COMPLETION_TOKENS,
            },
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(body) > MAX_REQUEST_BYTES:
            raise MiniMaxProtocolError(
                "MiniMax request exceeds the supported size", reason="request_too_large"
            )

        try:
            response = self._transport.send(
                url=ENDPOINT,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                body=body,
                timeout=self._timeout_seconds,
                max_response_bytes=MAX_RESPONSE_BYTES,
            )
        except TimeoutError:
            raise MiniMaxTimeoutError("MiniMax request timed out") from None
        except URLError as exc:
            if isinstance(exc.reason, TimeoutError):
                raise MiniMaxTimeoutError("MiniMax request timed out") from None
            raise MiniMaxUpstreamError("MiniMax request failed") from None
        except _ResponseTooLargeError:
            raise MiniMaxProtocolError(
                "MiniMax response exceeds the supported size", reason="response_too_large"
            ) from None
        except OSError:
            raise MiniMaxUpstreamError("MiniMax request failed") from None
        except MiniMaxError:
            raise
        except Exception:
            raise MiniMaxUpstreamError("MiniMax request failed") from None

        return _response_content(response)


__all__ = [
    "ENDPOINT",
    "MAX_COMPLETION_TOKENS",
    "MAX_PROMPT_BYTES",
    "MAX_REQUEST_BYTES",
    "MAX_RESPONSE_BYTES",
    "MODEL",
    "TIMEOUT_SECONDS",
    "HttpTransport",
    "MiniMaxAuthenticationError",
    "MiniMaxClient",
    "MiniMaxError",
    "MiniMaxProtocolError",
    "MiniMaxRateLimitError",
    "MiniMaxTimeoutError",
    "MiniMaxUnconfiguredError",
    "MiniMaxUpstreamError",
    "TransportResponse",
    "UrllibTransport",
]
