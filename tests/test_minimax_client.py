import json
from dataclasses import dataclass, field

import pytest

from runplan.application.ports import PlanGenerator
from runplan.integrations.minimax.client import (
    ENDPOINT,
    MAX_COMPLETION_TOKENS,
    MAX_PROMPT_BYTES,
    MAX_RESPONSE_BYTES,
    MODEL,
    TIMEOUT_SECONDS,
    MiniMaxAuthenticationError,
    MiniMaxClient,
    MiniMaxProtocolError,
    MiniMaxRateLimitError,
    MiniMaxTimeoutError,
    MiniMaxUnconfiguredError,
    MiniMaxUpstreamError,
    TransportResponse,
)


@dataclass
class FakeTransport:
    response: TransportResponse = TransportResponse(
        200, b'{"choices":[{"message":{"content":"program: generated"}}]}'
    )
    error: Exception | None = None
    calls: list[dict] = field(default_factory=list)

    def send(self, **request) -> TransportResponse:
        self.calls.append(request)
        if self.error is not None:
            raise self.error
        return self.response


def test_generate_sends_fixed_nonstreaming_request() -> None:
    transport = FakeTransport()
    generator: PlanGenerator = MiniMaxClient("subscription-key", transport=transport)

    result = generator.generate("Build YAML")

    assert result == "program: generated"
    assert len(transport.calls) == 1
    call = transport.calls[0]
    assert call["url"] == ENDPOINT
    assert call["headers"] == {
        "Authorization": "Bearer subscription-key",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }
    assert call["timeout"] == TIMEOUT_SECONDS == 300.0
    assert call["max_response_bytes"] == MAX_RESPONSE_BYTES
    assert json.loads(call["body"]) == {
        "model": MODEL,
        "messages": [{"role": "user", "content": "Build YAML"}],
        "stream": False,
        "thinking": {"type": "adaptive"},
        "reasoning_split": True,
        "tools": [],
        "max_completion_tokens": MAX_COMPLETION_TOKENS,
    }


def test_generate_ignores_separate_reasoning() -> None:
    transport = FakeTransport(
        TransportResponse(
            200,
            json.dumps(
                {
                    "choices": [
                        {
                            "message": {
                                "content": "safe output",
                                "reasoning_details": "private reasoning",
                            }
                        }
                    ]
                }
            ).encode(),
        )
    )

    assert MiniMaxClient("key", transport=transport).generate("prompt") == "safe output"


def test_environment_configuration_is_optional(monkeypatch) -> None:
    monkeypatch.delenv("RUNPLAN_MINIMAX_API_KEY", raising=False)
    unconfigured = MiniMaxClient.from_environment()
    configured = MiniMaxClient.from_environment({"RUNPLAN_MINIMAX_API_KEY": "environment-key"})

    assert not unconfigured.configured
    assert configured.configured
    with pytest.raises(MiniMaxUnconfiguredError, match="not configured"):
        unconfigured.generate("prompt")

    assert not MiniMaxClient("   ").configured


def test_environment_configures_bounded_timeout() -> None:
    transport = FakeTransport()
    client = MiniMaxClient.from_environment(
        {
            "RUNPLAN_MINIMAX_API_KEY": "key",
            "RUNPLAN_MINIMAX_TIMEOUT_SECONDS": "450",
        },
        transport=transport,
    )

    client.generate("prompt")

    assert transport.calls[0]["timeout"] == 450.0


@pytest.mark.parametrize("timeout", ["invalid", "29", "901", "nan"])
def test_environment_rejects_invalid_timeout(timeout: str) -> None:
    with pytest.raises(ValueError, match="MiniMax timeout must be from 30 to 900 seconds"):
        MiniMaxClient.from_environment({"RUNPLAN_MINIMAX_TIMEOUT_SECONDS": timeout})


@pytest.mark.parametrize("status", [401, 403])
def test_generate_maps_authentication_errors(status: int) -> None:
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(status, b"secret")))

    with pytest.raises(MiniMaxAuthenticationError, match="authentication failed"):
        client.generate("prompt")


def test_generate_maps_rate_limit() -> None:
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(429, b"quota")))

    with pytest.raises(MiniMaxRateLimitError, match="quota or rate limit"):
        client.generate("prompt")


@pytest.mark.parametrize("status", [400, 500, 503])
def test_generate_maps_other_http_errors(status: int) -> None:
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(status, b"private")))

    with pytest.raises(MiniMaxUpstreamError, match="unsuccessful response"):
        client.generate("prompt")


def test_generate_maps_timeout() -> None:
    client = MiniMaxClient("key", transport=FakeTransport(error=TimeoutError("private")))

    with pytest.raises(MiniMaxTimeoutError, match="request timed out"):
        client.generate("prompt")


@pytest.mark.parametrize("status", [408, 504])
def test_generate_maps_http_timeout(status: int) -> None:
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(status, b"private")))

    with pytest.raises(MiniMaxTimeoutError, match="request timed out"):
        client.generate("prompt")


@pytest.mark.parametrize(
    ("base_status", "error_type"),
    [
        (1004, MiniMaxAuthenticationError),
        (1002, MiniMaxRateLimitError),
        (1008, MiniMaxRateLimitError),
        (1001, MiniMaxTimeoutError),
        (1013, MiniMaxUpstreamError),
    ],
)
def test_generate_maps_minimax_errors_returned_with_http_200(
    base_status: int, error_type: type[Exception]
) -> None:
    body = json.dumps(
        {
            "base_resp": {"status_code": base_status, "status_msg": "private upstream detail"},
            "choices": [],
        }
    ).encode()
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(200, body)))

    with pytest.raises(error_type) as raised:
        client.generate("private prompt")

    assert "private upstream detail" not in str(raised.value)


def test_generate_maps_transport_failure_without_leaking_input() -> None:
    key = "super-secret-key"
    prompt = "private health history"
    transport = FakeTransport(error=RuntimeError(f"{key}: {prompt}"))

    with pytest.raises(MiniMaxUpstreamError) as raised:
        MiniMaxClient(key, transport=transport).generate(prompt)

    rendered = str(raised.value)
    assert key not in rendered
    assert prompt not in rendered
    assert raised.value.__cause__ is None
    assert raised.value.__context__ is not None
    assert raised.value.__suppress_context__


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"null",
        b"[]",
        b"{}",
        b'{"base_resp":"invalid","choices":[]}',
        b'{"choices":[]}',
        b'{"choices":[null]}',
        b'{"choices":[{"message":[]}] }',
        b'{"choices":[{"message":{}}]}',
        b'{"choices":[{"message":{"content":42}}]}',
    ],
)
def test_generate_rejects_invalid_response_shapes(body: bytes) -> None:
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(200, body)))

    with pytest.raises(MiniMaxProtocolError, match="invalid response"):
        client.generate("prompt")


def test_generate_bounds_prompt_before_transport() -> None:
    transport = FakeTransport()

    with pytest.raises(MiniMaxProtocolError, match="prompt exceeds"):
        MiniMaxClient("key", transport=transport).generate("x" * (MAX_PROMPT_BYTES + 1))

    assert transport.calls == []


def test_generate_bounds_encoded_request_before_transport() -> None:
    transport = FakeTransport()

    with pytest.raises(MiniMaxProtocolError, match="request exceeds"):
        MiniMaxClient("key", transport=transport).generate("\0" * 60_000)

    assert transport.calls == []


def test_generate_rejects_transport_that_returns_oversized_response() -> None:
    transport = FakeTransport(TransportResponse(200, b"x" * (MAX_RESPONSE_BYTES + 1)))

    with pytest.raises(MiniMaxProtocolError, match="response exceeds"):
        MiniMaxClient("key", transport=transport).generate("prompt")


def test_generate_rejects_invalid_transport_response() -> None:
    transport = FakeTransport()
    transport.response = object()  # type: ignore[assignment]

    with pytest.raises(MiniMaxProtocolError, match="invalid response"):
        MiniMaxClient("key", transport=transport).generate("prompt")


def test_response_and_prompt_are_absent_from_protocol_diagnostics() -> None:
    body = b"private model response"
    prompt = "private medical constraint"
    client = MiniMaxClient("key", transport=FakeTransport(TransportResponse(200, body)))

    with pytest.raises(MiniMaxProtocolError) as raised:
        client.generate(prompt)

    assert body.decode() not in str(raised.value)
    assert prompt not in str(raised.value)
