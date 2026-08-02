from __future__ import annotations

import json
import logging
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from runplan.users import RunplanUser, UserRegistry
from runplan.web import ProgramStore, make_handler
from runplan.web_generation import WebProgramGenerationService
from tests.test_web_generation import TODAY, generation_payload
from tests.web_helpers import fake_authenticator


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
    path: str,
    *,
    body: dict | None = None,
):
    users = registry(tmp_path)
    generation = WebProgramGenerationService(users, today=lambda: TODAY)
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


def test_generate_route_returns_local_draft_without_persistence(tmp_path: Path) -> None:
    handler = request_handler(
        tmp_path,
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
    assert "program:" in response["content"]
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "path",
    [
        "/api/program-generation/status",
        "/api/program-generation/jobs/missing?user=runner",
    ],
)
def test_removed_provider_and_job_routes_return_404(tmp_path: Path, path: str) -> None:
    handler = request_handler(tmp_path, path)

    handler.do_GET()

    assert handler.send_response.call_args.args == (404,)


def test_invalid_input_returns_400(tmp_path: Path) -> None:
    payload = generation_payload()
    payload["durationWeeks"] = True
    handler = request_handler(tmp_path, "/api/programs/generate", body=payload)

    handler.do_POST()

    assert handler.send_response.call_args.args == (400,)


def test_infeasible_constraints_return_422(tmp_path: Path) -> None:
    payload = generation_payload() | {"maximumWeeklyKm": 9}
    handler = request_handler(tmp_path, "/api/programs/generate", body=payload)

    handler.do_POST()

    assert handler.send_response.call_args.args == (422,)
    assert "maximum weekly distance" in response_json(handler)["error"]


def test_additional_instructions_return_explicit_safe_error(tmp_path: Path) -> None:
    private_note = "PRIVATE-MEDICAL-NOTE-739"
    payload = generation_payload() | {"additionalInstructions": private_note}
    handler = request_handler(tmp_path, "/api/programs/generate", body=payload)

    handler.do_POST()

    rendered = handler.wfile.getvalue().decode()
    assert handler.send_response.call_args.args == (400,)
    assert response_json(handler) == {
        "error": "additional instructions are no longer supported; use the structured controls"
    }
    assert private_note not in rendered


def test_client_error_log_omits_arbitrary_input_text(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    private_key = "PRIVATE-FORM-KEY-918"
    payload = generation_payload() | {private_key: "PRIVATE-FORM-VALUE-372"}
    handler = request_handler(tmp_path, "/api/programs/generate", body=payload)

    with caplog.at_level(logging.WARNING, logger="runplan.web"):
        handler.do_POST()

    assert handler.send_response.call_args.args == (400,)
    assert private_key not in caplog.text
    assert "PRIVATE-FORM-VALUE-372" not in caplog.text
    assert "status=400" in caplog.text


def test_malformed_easy_pace_is_absent_from_http_and_log(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    private_pace = "PRIVATE-PACE-INPUT-624"
    payload = generation_payload()
    payload["currentTraining"] = {
        **payload["currentTraining"],
        "easyPace": private_pace,
    }
    handler = request_handler(tmp_path, "/api/programs/generate", body=payload)

    with caplog.at_level(logging.WARNING, logger="runplan.web"):
        handler.do_POST()

    rendered = handler.wfile.getvalue().decode() + caplog.text
    assert handler.send_response.call_args.args == (400,)
    assert response_json(handler) == {
        "error": "currentTraining.easyPace must use M:SS or M:SS-M:SS per km"
    }
    assert private_pace not in rendered
