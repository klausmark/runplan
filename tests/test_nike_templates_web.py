"""Web integration tests for the bundled plan templates."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest

from runplan.web import ProgramStore, make_handler
from runplan.web_auth import login_proof
from tests.web_helpers import fake_authenticator


@pytest.fixture
def store(tmp_path: Path) -> ProgramStore:
    return ProgramStore(tmp_path)


@pytest.fixture
def authenticated(make_handler_obj):  # type: ignore[no-untyped-def]
    return make_handler_obj


def make_handler_obj(
    store: ProgramStore,
    path: str,
    method: str = "GET",
    body: dict | None = None,
    cookie: str | None = None,
    authenticator=None,
):
    auth = authenticator or fake_authenticator()
    handler = object.__new__(make_handler(store, authenticator=auth))
    content = json.dumps(body).encode() if body is not None else b""
    headers = {"Content-Length": str(len(content))}
    if cookie:
        headers["Cookie"] = cookie
    handler.path = path
    handler.command = method
    handler.client_address = ("127.0.0.1", 1234)
    handler.headers = headers
    handler.rfile = BytesIO(content)
    handler.wfile = BytesIO()
    handler.send_response = Mock()
    handler.send_header = Mock()
    handler.end_headers = Mock()
    return handler, auth


def login(store: ProgramStore, authenticator) -> str:
    challenge_handler, _ = make_handler_obj(
        store, "/api/auth/challenge", authenticator=authenticator
    )
    challenge_handler.do_GET()
    challenge = json.loads(challenge_handler.wfile.getvalue())
    login_handler, _ = make_handler_obj(
        store,
        "/api/auth/login",
        method="POST",
        body={"challengeId": challenge["challengeId"], "proof": login_proof("secret", challenge)},
        authenticator=authenticator,
    )
    login_handler.do_POST()
    return next(
        call.args[1]
        for call in login_handler.send_header.call_args_list
        if call.args[0] == "Set-Cookie"
    ).split(";", 1)[0]


def test_templates_endpoint_requires_auth(store: ProgramStore) -> None:
    handler, _ = make_handler_obj(store, "/api/templates")
    handler.do_GET()
    handler.send_response.assert_called_once_with(401)


def test_templates_endpoint_lists_every_bundled_template(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store, "/api/templates", cookie=cookie, authenticator=authenticator
    )
    handler.do_GET()

    handler.send_response.assert_called_once_with(200)
    payload = json.loads(handler.wfile.getvalue())
    ids = [item["id"] for item in payload["templates"]]
    assert ids == ["nike-5k", "nike-10k", "nike-half-marathon", "nike-marathon"]
    first = payload["templates"][0]
    assert first["distanceLabel"] == "5K"
    assert first["durationWeeks"] == 8
    assert first["sessionsPerWeek"] == 5
    assert first["hasRaceWeek"] is True


def test_get_template_returns_metadata_and_suggested_filename(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store, "/api/templates/nike-10k", cookie=cookie, authenticator=authenticator
    )
    handler.do_GET()

    handler.send_response.assert_called_once_with(200)
    payload = json.loads(handler.wfile.getvalue())
    assert payload["template"]["id"] == "nike-10k"
    assert payload["suggestedFilename"].startswith("nike-10k-")
    assert payload["suggestedFilename"].endswith(".yaml")


def test_get_template_404_for_unknown_id(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store, "/api/templates/not-real", cookie=cookie, authenticator=authenticator
    )
    handler.do_GET()

    handler.send_response.assert_called_once_with(404)


def test_copy_template_returns_yaml_with_chosen_start_week(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store,
        "/api/templates/nike-5k/copy",
        method="POST",
        body={"start_week": "2026-W32"},
        cookie=cookie,
        authenticator=authenticator,
    )
    handler.do_POST()

    handler.send_response.assert_called_once_with(200)
    payload = json.loads(handler.wfile.getvalue())
    assert payload["templateId"] == "nike-5k"
    assert payload["filename"] == "nike-5k-2026-w32.yaml"
    assert "id: nike-5k-2026-w32" in payload["content"]
    assert "start_week: 2026-W32" in payload["content"]


def test_copy_template_default_start_week(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store,
        "/api/templates/nike-marathon/copy",
        method="POST",
        body={},
        cookie=cookie,
        authenticator=authenticator,
    )
    handler.do_POST()

    handler.send_response.assert_called_once_with(200)
    payload = json.loads(handler.wfile.getvalue())
    assert payload["filename"].startswith("nike-marathon-")
    assert payload["filename"].endswith(".yaml")
    assert payload["content"].startswith("program:\n  id: nike-marathon-")


def test_copy_template_rejects_malformed_start_week(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store,
        "/api/templates/nike-5k/copy",
        method="POST",
        body={"start_week": "not a week"},
        cookie=cookie,
        authenticator=authenticator,
    )
    handler.do_POST()

    handler.send_response.assert_called_once_with(422)
    payload = json.loads(handler.wfile.getvalue())
    assert "start_week" in payload["error"]


def test_copy_template_unknown_template_returns_422(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    handler, _ = make_handler_obj(
        store,
        "/api/templates/missing/copy",
        method="POST",
        body={},
        cookie=cookie,
        authenticator=authenticator,
    )
    handler.do_POST()

    handler.send_response.assert_called_once_with(422)


def test_copied_template_can_be_uploaded_and_appears_in_programs(store: ProgramStore) -> None:
    authenticator = fake_authenticator()
    cookie = login(store, authenticator)
    copy_handler, _ = make_handler_obj(
        store,
        "/api/templates/nike-half-marathon/copy",
        method="POST",
        body={"start_week": "2026-W30"},
        cookie=cookie,
        authenticator=authenticator,
    )
    copy_handler.do_POST()
    copy_payload = json.loads(copy_handler.wfile.getvalue())
    upload_handler, _ = make_handler_obj(
        store,
        "/api/programs",
        method="POST",
        body={
            "userId": "local-default",
            "filename": copy_payload["filename"],
            "content": copy_payload["content"],
        },
        cookie=cookie,
        authenticator=authenticator,
    )
    upload_handler.do_POST()
    assert upload_handler.send_response.call_args[0][0] == 201

    list_handler, _ = make_handler_obj(
        store,
        "/api/programs?user=local-default",
        cookie=cookie,
        authenticator=authenticator,
    )
    list_handler.do_GET()
    payload = json.loads(list_handler.wfile.getvalue())
    assert any(item["id"] == "nike-half-marathon-2026-w30" for item in payload["programs"])


def test_templates_endpoints_reject_unauthenticated_requests(store: ProgramStore) -> None:
    for method, path, body in [
        ("GET", "/api/templates", None),
        ("GET", "/api/templates/nike-5k", None),
        ("POST", "/api/templates/nike-5k/copy", {"start_week": "2026-W32"}),
    ]:
        handler, _ = make_handler_obj(store, path, method=method, body=body)
        getattr(handler, "do_" + method)()
        handler.send_response.assert_called_once_with(401)
