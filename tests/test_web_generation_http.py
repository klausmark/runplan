from __future__ import annotations

import json
import logging
from collections.abc import Callable
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from runplan.integrations.minimax import (
    MiniMaxAuthenticationError,
    MiniMaxProtocolError,
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
    generation_service: WebProgramGenerationService | None = None,
):
    users = registry(tmp_path)
    generation = generation_service or WebProgramGenerationService(
        generator, users, today=lambda: TODAY
    )
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


def test_background_generation_job_starts_and_polls_to_completion(tmp_path: Path) -> None:
    workers: list[Callable[[], None]] = []
    users = registry(tmp_path)
    generation = WebProgramGenerationService(
        FakeGenerator(candidate_yaml()),
        users,
        today=lambda: TODAY,
        start_worker=workers.append,
    )
    start = request_handler(
        tmp_path,
        FakeGenerator(),
        "/api/program-generation/jobs",
        body=generation_payload(),
        generation_service=generation,
    )

    start.do_POST()

    started = response_json(start)
    assert start.send_response.call_args.args == (202,)
    assert started["status"] == "running"
    assert started["phase"] == "queued"
    workers.pop()()

    poll = request_handler(
        tmp_path,
        FakeGenerator(),
        f"/api/program-generation/jobs/{started['jobId']}?user=runner",
        generation_service=generation,
    )
    poll.do_GET()

    completed = response_json(poll)
    assert poll.send_response.call_args.args == (200,)
    assert completed["status"] == "complete"
    assert completed["draft"]["summary"] == {"weeks": 4, "workouts": 12}


def test_unknown_background_generation_job_returns_404(tmp_path: Path) -> None:
    handler = request_handler(
        tmp_path,
        FakeGenerator(),
        "/api/program-generation/jobs/missing?user=runner",
    )

    handler.do_GET()

    assert handler.send_response.call_args.args == (404,)
    assert response_json(handler) == {"error": "Program generation job not found"}


def test_background_generation_job_returns_safe_provider_failure(tmp_path: Path) -> None:
    workers: list[Callable[[], None]] = []
    users = registry(tmp_path)
    generation = WebProgramGenerationService(
        FakeGenerator(MiniMaxTimeoutError("private detail")),
        users,
        today=lambda: TODAY,
        start_worker=workers.append,
    )
    start = request_handler(
        tmp_path,
        FakeGenerator(),
        "/api/program-generation/jobs",
        body=generation_payload(),
        generation_service=generation,
    )
    start.do_POST()
    started = response_json(start)
    workers.pop()()
    poll = request_handler(
        tmp_path,
        FakeGenerator(),
        f"/api/program-generation/jobs/{started['jobId']}?user=runner",
        generation_service=generation,
    )

    poll.do_GET()

    result = response_json(poll)
    assert result["status"] == "failed"
    assert result["error"] == {
        "httpStatus": 504,
        "error": "Program generation timed out",
    }
    assert "private detail" not in poll.wfile.getvalue().decode()


@pytest.mark.parametrize(
    ("reason", "message"),
    [
        ("output_limit", "MiniMax reached its output limit before completing the program"),
        ("content_filtered", "MiniMax filtered the generated program"),
        ("missing_content", "MiniMax returned an incomplete response; try generating again"),
    ],
)
def test_background_generation_job_reports_safe_protocol_reason(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    reason: str,
    message: str,
) -> None:
    workers: list[Callable[[], None]] = []
    users = registry(tmp_path)
    generation = WebProgramGenerationService(
        FakeGenerator(MiniMaxProtocolError("private detail", reason=reason)),
        users,
        today=lambda: TODAY,
        start_worker=workers.append,
    )
    start = request_handler(
        tmp_path,
        FakeGenerator(),
        "/api/program-generation/jobs",
        body=generation_payload(),
        generation_service=generation,
    )
    start.do_POST()
    started = response_json(start)

    with caplog.at_level(logging.ERROR, logger="runplan.web"):
        workers.pop()()

    poll = request_handler(
        tmp_path,
        FakeGenerator(),
        f"/api/program-generation/jobs/{started['jobId']}?user=runner",
        generation_service=generation,
    )
    poll.do_GET()

    result = response_json(poll)
    assert result["error"] == {"httpStatus": 503, "error": message}
    assert f"reason={reason}" in caplog.text
    assert "private detail" not in poll.wfile.getvalue().decode() + caplog.text


def test_invalid_input_returns_400(tmp_path: Path) -> None:
    payload = generation_payload()
    payload["durationWeeks"] = True
    handler = request_handler(tmp_path, FakeGenerator(), "/api/programs/generate", body=payload)

    handler.do_POST()

    handler.send_response.assert_called_once_with(400)


def test_client_error_log_omits_arbitrary_input_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    private_key = "PRIVATE-FORM-KEY-918"
    payload = generation_payload() | {private_key: "PRIVATE-FORM-VALUE-372"}
    handler = request_handler(tmp_path, FakeGenerator(), "/api/programs/generate", body=payload)

    with caplog.at_level(logging.WARNING, logger="runplan.web"):
        handler.do_POST()

    assert handler.send_response.call_args.args == (400,)
    assert private_key not in caplog.text
    assert "PRIVATE-FORM-VALUE-372" not in caplog.text
    assert "status=400" in caplog.text
    assert "exception=WebError" in caplog.text


def test_malformed_easy_pace_is_absent_from_http_and_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    private_pace = "PRIVATE-PACE-INPUT-624"
    payload = generation_payload()
    payload["currentTraining"] = {
        **payload["currentTraining"],
        "easyPace": private_pace,
    }
    handler = request_handler(tmp_path, FakeGenerator(), "/api/programs/generate", body=payload)

    with caplog.at_level(logging.WARNING, logger="runplan.web"):
        handler.do_POST()

    rendered = handler.wfile.getvalue().decode() + caplog.text
    assert handler.send_response.call_args.args == (400,)
    assert response_json(handler) == {
        "error": "currentTraining.easyPace must use M:SS or M:SS-M:SS per km"
    }
    assert private_pace not in rendered


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
        (MiniMaxRateLimitError("secret detail"), 429),
        (MiniMaxTimeoutError("secret detail"), 504),
        (MiniMaxUnconfiguredError("secret detail"), 503),
        (MiniMaxAuthenticationError("secret detail"), 503),
        (MiniMaxProtocolError("secret detail"), 503),
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
    assert "secret detail" not in handler.wfile.getvalue().decode()
    if status == 503:
        assert response == {"error": "Program generation is unavailable"}


def test_provider_http_error_and_log_exclude_prompt_notes_and_secrets(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    sensitive_note = "MEDICAL-NOTE-739"
    api_secret = "sk-minimax-http-secret-4821"
    payload = generation_payload() | {
        "additionalInstructions": f"Use private guidance {sensitive_note}"
    }
    handler = request_handler(
        tmp_path,
        FakeGenerator(MiniMaxUpstreamError(f"{sensitive_note} {api_secret}")),
        "/api/programs/generate",
        body=payload,
    )

    with caplog.at_level(logging.DEBUG, logger="runplan.web"):
        handler.do_POST()

    rendered = handler.wfile.getvalue().decode() + caplog.text
    handler.send_response.assert_called_once_with(503)
    assert response_json(handler) == {"error": "Program generation is unavailable"}
    assert sensitive_note not in rendered
    assert api_secret not in rendered


def test_disconnected_client_during_timeout_response_has_no_unhandled_exception(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    handler = request_handler(
        tmp_path,
        FakeGenerator(MiniMaxTimeoutError("private detail")),
        "/api/programs/generate",
        body=generation_payload(),
    )
    handler.wfile = Mock()
    handler.wfile.write.side_effect = BrokenPipeError

    with caplog.at_level(logging.INFO, logger="runplan.web"):
        handler.do_POST()

    assert "HTTP client disconnected" in caplog.text
    assert "Unhandled HTTP exception" not in caplog.text
    assert "private detail" not in caplog.text


def test_busy_generation_returns_409(tmp_path: Path) -> None:
    handler = request_handler(
        tmp_path, FakeGenerator(), "/api/programs/generate", body=generation_payload()
    )
    handler.generation = Mock()
    handler.generation.generate.side_effect = GenerationBusyError("already running")

    handler.do_POST()

    handler.send_response.assert_called_once_with(409)
    assert response_json(handler) == {"error": "already running"}
