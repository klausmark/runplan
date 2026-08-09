import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from runplan.web import ProgramStore, make_handler
from runplan.web_auth import COOKIE_NAME, login_proof
from tests.web_helpers import fake_authenticator


def request_handler(
    tmp_path: Path,
    path: str,
    *,
    method: str = "GET",
    body: dict | None = None,
    cookie: str | None = None,
    peer: str = "127.0.0.1",
    forwarded_proto: str | None = None,
    authenticator=None,
    sync_service=None,
):
    auth = authenticator or fake_authenticator()
    handler = object.__new__(
        make_handler(ProgramStore(tmp_path), authenticator=auth, sync_service=sync_service)
    )
    content = json.dumps(body).encode() if body is not None else b""
    headers = {"Content-Length": str(len(content))}
    if cookie:
        headers["Cookie"] = cookie
    if forwarded_proto:
        headers["X-Forwarded-Proto"] = forwarded_proto
    handler.path = path
    handler.command = method
    handler.client_address = (peer, 1234)
    handler.headers = headers
    handler.rfile = BytesIO(content)
    handler.wfile = BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    return handler, auth


def response_json(handler) -> dict:
    return json.loads(handler.wfile.getvalue())


def test_health_and_auth_status_are_public_but_program_api_requires_cookie(tmp_path: Path) -> None:
    health, auth = request_handler(tmp_path, "/api/health")
    health.do_GET()
    assert response_json(health) == {"status": "ok"}

    status, _ = request_handler(tmp_path, "/api/auth/status", authenticator=auth)
    status.do_GET()
    assert response_json(status) == {"authenticated": False}

    programs, _ = request_handler(tmp_path, "/api/programs", authenticator=auth)
    programs.do_GET()
    programs.send_response.assert_called_once_with(401)
    assert response_json(programs) == {"error": "Authentication required"}


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/users"),
        ("GET", "/api/programs"),
        ("GET", "/api/programs/plan.yaml/export?format=pdf"),
        ("POST", "/api/users"),
        ("POST", "/api/programs/plan.yaml/sync"),
        ("POST", "/api/users/runner/settings"),
        ("DELETE", "/api/programs/plan.yaml"),
    ],
)
def test_every_application_api_is_gated_before_routing_or_body_parsing(
    tmp_path: Path, method: str, path: str
) -> None:
    handler, _ = request_handler(tmp_path, path, method=method)

    getattr(handler, f"do_{method}")()

    handler.send_response.assert_called_once_with(401)
    assert response_json(handler) == {"error": "Authentication required"}


def test_challenge_login_sets_cookie_and_authorizes_later_requests(tmp_path: Path) -> None:
    challenge_handler, auth = request_handler(tmp_path, "/api/auth/challenge")
    challenge_handler.do_GET()
    challenge = response_json(challenge_handler)

    login, _ = request_handler(
        tmp_path,
        "/api/auth/login",
        method="POST",
        body={
            "challengeId": challenge["challengeId"],
            "proof": login_proof("secret", challenge),
        },
        authenticator=auth,
    )
    login.do_POST()

    assert response_json(login) == {"authenticated": True}
    cookie_header = next(
        call.args[1] for call in login.send_header.call_args_list if call.args[0] == "Set-Cookie"
    )
    assert "HttpOnly" in cookie_header
    cookie = cookie_header.split(";", 1)[0]
    assert cookie.startswith(f"{COOKIE_NAME}=")

    users, _ = request_handler(tmp_path, "/api/users", cookie=cookie, authenticator=auth)
    users.do_GET()
    users.send_response.assert_called_once_with(200)
    assert "users" in response_json(users)


def test_login_rejects_wrong_proof_without_setting_cookie(tmp_path: Path) -> None:
    challenge_handler, auth = request_handler(tmp_path, "/api/auth/challenge")
    challenge_handler.do_GET()
    challenge = response_json(challenge_handler)
    login, _ = request_handler(
        tmp_path,
        "/api/auth/login",
        method="POST",
        body={"challengeId": challenge["challengeId"], "proof": "wrong"},
        authenticator=auth,
    )

    login.do_POST()

    login.send_response.assert_called_once_with(401)
    assert all(call.args[0] != "Set-Cookie" for call in login.send_header.call_args_list)


def test_remote_http_is_rejected_before_authentication(tmp_path: Path) -> None:
    handler, _ = request_handler(tmp_path, "/api/auth/challenge", peer="203.0.113.5")

    handler.do_GET()

    handler.send_response.assert_called_once_with(426)
    assert response_json(handler) == {"error": "HTTPS is required for Runplan web authentication"}


def test_trusted_https_proxy_sets_secure_cookie(tmp_path: Path) -> None:
    auth = fake_authenticator()
    auth.trust_proxy = True
    challenge_handler, _ = request_handler(
        tmp_path,
        "/api/auth/challenge",
        peer="203.0.113.5",
        forwarded_proto="https",
        authenticator=auth,
    )
    challenge_handler.do_GET()
    challenge = response_json(challenge_handler)
    login, _ = request_handler(
        tmp_path,
        "/api/auth/login",
        method="POST",
        body={
            "challengeId": challenge["challengeId"],
            "proof": login_proof("secret", challenge),
        },
        peer="203.0.113.5",
        forwarded_proto="https",
        authenticator=auth,
    )
    login.do_POST()

    cookie = next(
        call.args[1] for call in login.send_header.call_args_list if call.args[0] == "Set-Cookie"
    )
    assert "; Secure" in cookie


def _authorized_cookie(tmp_path: Path, auth) -> str:
    challenge, _ = request_handler(tmp_path, "/api/auth/challenge", authenticator=auth)
    challenge.do_GET()
    challenge_payload = response_json(challenge)
    login, _ = request_handler(
        tmp_path,
        "/api/auth/login",
        method="POST",
        body={
            "challengeId": challenge_payload["challengeId"],
            "proof": login_proof("secret", challenge_payload),
        },
        authenticator=auth,
    )
    login.do_POST()
    return next(
        call.args[1] for call in login.send_header.call_args_list if call.args[0] == "Set-Cookie"
    ).split(";", 1)[0]


def test_delete_program_routes_to_sync_service_and_returns_json(tmp_path: Path) -> None:
    sync = Mock()
    sync.delete_program.return_value = {"deleted": "plan.yaml", "activeProgramCleared": True}
    sync.users.default_id = "local-default"
    auth = fake_authenticator()
    cookie = _authorized_cookie(tmp_path, auth)

    handler, _ = request_handler(
        tmp_path,
        "/api/programs/plan.yaml?user=local-default",
        method="DELETE",
        cookie=cookie,
        authenticator=auth,
        sync_service=sync,
    )

    handler.do_DELETE()

    sync.delete_program.assert_called_once_with("local-default", "plan.yaml")
    handler.send_response.assert_called_once_with(200)
    assert response_json(handler) == {"deleted": "plan.yaml", "activeProgramCleared": True}


def test_delete_unknown_subpath_returns_not_found(tmp_path: Path) -> None:
    sync = Mock()
    sync.users.default_id = "local-default"
    auth = fake_authenticator()
    cookie = _authorized_cookie(tmp_path, auth)

    handler, _ = request_handler(
        tmp_path,
        "/api/programs/plan.yaml/extra?user=local-default",
        method="DELETE",
        cookie=cookie,
        authenticator=auth,
        sync_service=sync,
    )

    handler.do_DELETE()

    sync.delete_program.assert_not_called()
    handler.send_response.assert_called_once_with(404)
