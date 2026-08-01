from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from runplan.integrations.minimax import (
    MiniMaxAuthenticationError,
    MiniMaxRateLimitError,
    MiniMaxTimeoutError,
    MiniMaxUnconfiguredError,
    MiniMaxUpstreamError,
)
from runplan.users import RunplanUser, UserRegistry
from runplan.web import ProgramStore, make_handler
from runplan.web_generation import GenerationBusyError, WebProgramGenerationService
from tests.test_generate_first_10k import candidate_yaml
from tests.test_web_generation import TODAY, generation_payload
from tests.web_helpers import fake_authenticator


class FakeGenerator:
    def __init__(self, *responses: object, configured: bool = True) -> None:
        self.responses = list(responses)
        self.configured = configured

    def generate(self, prompt: str) -> str:
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, str)
        return response


def registry(tmp_path: Path) -> UserRegistry:
    return UserRegistry(
        [
            RunplanUser(
                "runner",
                "Runner",
                tmp_path / "credentials.toml",
                tmp_path / "tokens",
                tmp_path / "state",
            )
        ]
    )


def request_handler(
    tmp_path: Path,
    generator: FakeGenerator,
    path: str,
    *,
    body: dict | None = None,
):
    users = registry(tmp_path)
    generation = WebProgramGenerationService(generator, users, today=lambda: TODAY)
    handler_type = make_handler(
        ProgramStore(tmp_path),
        users=users,
        authenticator=fake_authenticator(),
        generation_service=generation,
    )
    handler = object.__new__(handler_type)
    content = json.dumps(body).encode() if body is not None else b""
    handler.path = path
    handler.command = "POST" if body is not None else "GET"
    handler.client_address = ("127.0.0.1", 1234)
    handler.headers = {"Content-Length": str(len(content))}
    handler.rfile = BytesIO(content)
    handler.wfile = BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    handler.auth = Mock()
    handler.auth.get.return_value = None
    handler.auth.post.return_value = None
    return handler


def response_json(handler) -> dict:
    return json.loads(handler.wfile.getvalue())


@pytest.mark.parametrize("configured", [True, False])
def test_status_returns_only_configuration_boolean(tmp_path: Path, configured: bool) -> None:
    handler = request_handler(
        tmp_path,
        FakeGenerator(configured=configured),
        "/api/program-generation/status",
    )

    handler.do_GET()

    assert response_json(handler) == {"configured": configured}


def test_generate_route_precedes_filename_route_and_does_not_persist(tmp_path: Path) -> None:
    handler = request_handler(
        tmp_path,
        FakeGenerator(candidate_yaml()),
        "/api/programs/generate",
        body=generation_payload(),
    )

    handler.do_POST()

    response = response_json(handler)
    handler.send_response.assert_called_once_with(200)
    assert response["filename"] == "first-10k-2026-08-03.yaml"
    assert response["summary"] == {"weeks": 4, "workouts": 12}
    assert response["attemptCount"] == 1
    assert response["warnings"] == []
    assert list(tmp_path.iterdir()) == []


def test_invalid_input_returns_400(tmp_path: Path) -> None:
    payload = generation_payload()
    payload["durationWeeks"] = True
    handler = request_handler(tmp_path, FakeGenerator(), "/api/programs/generate", body=payload)

    handler.do_POST()

    handler.send_response.assert_called_once_with(400)


def test_repeated_invalid_candidate_returns_bounded_structured_422(tmp_path: Path) -> None:
    handler = request_handler(
        tmp_path,
        FakeGenerator("not: valid: yaml", "still: invalid: yaml"),
        "/api/programs/generate",
        body=generation_payload(),
    )

    handler.do_POST()

    response = response_json(handler)
    handler.send_response.assert_called_once_with(422)
    assert response["candidate"] == "still: invalid: yaml"
    assert response["diagnostics"][0]["severity"] == "error"
    assert response["diagnostics"][0]["code"] == "candidate_parse_error"
    assert response["attemptCount"] == 2


@pytest.mark.parametrize(
    ("error", "status"),
    [
        (MiniMaxRateLimitError("rate"), 429),
        (MiniMaxTimeoutError("timeout"), 504),
        (MiniMaxUnconfiguredError("secret detail"), 503),
        (MiniMaxAuthenticationError("secret detail"), 503),
        (MiniMaxUpstreamError("upstream detail"), 503),
    ],
)
def test_provider_errors_have_stable_http_mapping(
    tmp_path: Path, error: BaseException, status: int
) -> None:
    handler = request_handler(
        tmp_path,
        FakeGenerator(error),
        "/api/programs/generate",
        body=generation_payload(),
    )

    handler.do_POST()

    response = response_json(handler)
    handler.send_response.assert_called_once_with(status)
    if status == 503:
        assert response == {"error": "Program generation is unavailable"}
        assert "detail" not in handler.wfile.getvalue().decode()


def test_busy_generation_returns_409(tmp_path: Path) -> None:
    handler = request_handler(
        tmp_path, FakeGenerator(), "/api/programs/generate", body=generation_payload()
    )
    handler.generation = Mock()
    handler.generation.generate.side_effect = GenerationBusyError("already running")

    handler.do_POST()

    handler.send_response.assert_called_once_with(409)
    assert response_json(handler) == {"error": "already running"}
