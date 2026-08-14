"""Server tests for the coaching recommendation HTTP surface (Step 8).

The endpoint accepts ``(userId, program_file, target_day, week,
readiness, request_kind)`` and returns the
:class:`WorkoutRecommendation` plus a ``week_key_forms`` list so the
Studio add-workout dialog can show its key-workout warning. The tests
focus on the contract — input validation, response shape, and key-form
detection — rather than the recommender itself.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import yaml

from runplan import KEY_WORKOUT_FORMS
from runplan.domain.workout_form import FORM_BY_NAME
from runplan.users import RunplanUser, WebError
from runplan.web import ProgramStore, WebSyncService
from runplan.web_auth import login_proof
from runplan.web_coaching import recommendation_response
from tests.helpers import program_data
from tests.web_helpers import MemoryStateRepository, fake_authenticator

_TODAY = date(2026, 8, 12)


def _request(
    tmp_path: Path,
    path: str,
    *,
    body: dict | None = None,
    method: str = "POST",
    authenticator=None,
    cookie: str | None = None,
    today=_TODAY,
):
    auth = authenticator or fake_authenticator()
    store = ProgramStore(tmp_path, repository=MemoryStateRepository())
    sync = WebSyncService(store, repository=MemoryStateRepository(), today=lambda: today)
    handler = object.__new__(make_handler_for_sync(store, sync, auth))
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
    return handler


def make_handler_for_sync(store: ProgramStore, sync: WebSyncService, auth):
    from runplan.web_auth_http import WebAuthHttpAdapter
    from runplan.web_http import make_handler

    handler_class = make_handler(store, sync_service=sync, authenticator=auth)
    return type(
        "BoundHandler",
        (handler_class,),
        {"auth": WebAuthHttpAdapter(auth)},
    )


def response_json(handler) -> dict:
    return json.loads(handler.wfile.getvalue())


def authorized_cookie(tmp_path: Path, auth) -> str:
    challenge = _request(tmp_path, "/api/auth/challenge", method="GET", authenticator=auth)
    challenge.do_GET()
    challenge_payload = response_json(challenge)
    login = _request(
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


def _write_program(tmp_path: Path, program: dict | None = None) -> Path:
    path = tmp_path / "plan.yaml"
    payload = deepcopy(program or program_data())
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _base_body(program_file: str = "plan.yaml", **overrides) -> dict:
    body = {
        "userId": "local-default",
        "program_file": program_file,
        "target_day": "2026-08-12",
        "week": 2,
        "readiness": "normal",
        "request_kind": "default",
    }
    body.update(overrides)
    return body


# ---------------------------------------------------------------------------
# Direct adapter — recommendation_response
# ---------------------------------------------------------------------------


def test_recommendation_response_returns_serialised_recommendation(tmp_path: Path) -> None:
    program_path = _write_program(tmp_path)
    user = RunplanUser(
        id="local-default",
        name="Local user",
        credentials_file=tmp_path / "credentials.toml",
        token_store=tmp_path / "tokens",
        state_directory=tmp_path / "state",
        five_k_best="25:00",
    )
    response = recommendation_response(
        _base_body(),
        user=user,
        program_file="plan.yaml",
        program_text=program_path.read_text(encoding="utf-8"),
        today=_TODAY,
    )
    assert response["target_day"] == "2026-08-12"
    assert response["week"] == 2
    assert isinstance(response["week_key_forms"], list)
    primary = response["primary"]
    assert primary["form"]
    assert primary["recipe_key"]
    assert isinstance(primary["parameters"], dict)
    assert isinstance(response["alternatives"], list)
    assert isinstance(response["reasoning"], list)
    assert isinstance(response["warnings"], list)
    assert {item["name"] for item in response["form_catalog"]} == {
        "easy_run",
        "run_walk",
        "recovery_run",
        "long_run",
        "tempo_run",
        "interval_workout",
    }


def test_recommendation_response_lists_tempo_key_in_target_week(tmp_path: Path) -> None:
    program = deepcopy(program_data())
    program["weeks"][1]["workouts"][0]["steps"] = [{"run": {"time": "20m", "pace": "5:00 min/km"}}]
    program_path = tmp_path / "plan.yaml"
    program_path.write_text(
        yaml.safe_dump(program, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    user = RunplanUser(
        id="local-default",
        name="Local",
        credentials_file=tmp_path / "credentials.toml",
        token_store=tmp_path / "tokens",
        state_directory=tmp_path / "state",
        five_k_best="30:00",
    )
    response = recommendation_response(
        _base_body(),
        user=user,
        program_file="plan.yaml",
        program_text=program_path.read_text(encoding="utf-8"),
        today=_TODAY,
    )
    assert "tempo_run" in response["week_key_forms"]


def test_recommendation_response_rejects_invalid_readiness(tmp_path: Path) -> None:
    program_path = _write_program(tmp_path)
    user = RunplanUser(
        id="local-default",
        name="Local",
        credentials_file=tmp_path / "credentials.toml",
        token_store=tmp_path / "tokens",
        state_directory=tmp_path / "state",
        five_k_best="30:00",
    )
    with __import__("pytest").raises(WebError) as excinfo:
        recommendation_response(
            _base_body(readiness="medium"),
            user=user,
            program_file="plan.yaml",
            program_text=program_path.read_text(encoding="utf-8"),
            today=_TODAY,
        )
    assert excinfo.value.status.value == 400
    assert "readiness" in str(excinfo.value)


def test_recommendation_response_rejects_invalid_request_kind(tmp_path: Path) -> None:
    program_path = _write_program(tmp_path)
    user = RunplanUser(
        id="local-default",
        name="Local",
        credentials_file=tmp_path / "credentials.toml",
        token_store=tmp_path / "tokens",
        state_directory=tmp_path / "state",
        five_k_best="30:00",
    )
    with __import__("pytest").raises(WebError) as excinfo:
        recommendation_response(
            _base_body(request_kind="surprise"),
            user=user,
            program_file="plan.yaml",
            program_text=program_path.read_text(encoding="utf-8"),
            today=_TODAY,
        )
    assert excinfo.value.status.value == 400
    assert "request_kind" in str(excinfo.value)


def test_recommendation_response_rejects_missing_target_day(tmp_path: Path) -> None:
    program_path = _write_program(tmp_path)
    user = RunplanUser(
        id="local-default",
        name="Local",
        credentials_file=tmp_path / "credentials.toml",
        token_store=tmp_path / "tokens",
        state_directory=tmp_path / "state",
        five_k_best="30:00",
    )
    payload = _base_body()
    payload.pop("target_day")
    with __import__("pytest").raises(WebError) as excinfo:
        recommendation_response(
            payload,
            user=user,
            program_file="plan.yaml",
            program_text=program_path.read_text(encoding="utf-8"),
            today=_TODAY,
        )
    assert excinfo.value.status.value == 400
    assert "target_day" in str(excinfo.value)


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def test_coaching_endpoint_returns_recommendation_for_known_program(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    program = deepcopy(program_data())
    program["weeks"][1]["workouts"][0]["steps"] = [{"run": {"time": "20m", "pace": "5:00 min/km"}}]
    _write_program(tmp_path, program)
    handler = _request(
        tmp_path,
        "/api/coaching/recommendation",
        body=_base_body(),
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(200)
    payload = response_json(handler)
    assert payload["week"] == 2
    assert payload["primary"]["recipe_key"]
    assert isinstance(payload["alternatives"], list)
    assert "tempo_run" in payload["week_key_forms"]


def test_coaching_endpoint_returns_400_for_invalid_readiness(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    _write_program(tmp_path)
    handler = _request(
        tmp_path,
        "/api/coaching/recommendation",
        body=_base_body(readiness="elevated"),
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(400)
    payload = response_json(handler)
    assert "readiness" in payload["error"]


def test_coaching_endpoint_returns_404_for_missing_program(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    handler = _request(
        tmp_path,
        "/api/coaching/recommendation",
        body=_base_body(program_file="ghost.yaml"),
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(404)


def test_coaching_endpoint_uses_linked_completions_to_classify_load(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    program = deepcopy(program_data())
    # Build enough completed sessions (>= 3, >= 90 minutes total) so the
    # key-workout rule allows a key session. Days 9/10/11 are all more than
    # one week before the 2026-08-18 target so the "no recent key" gate
    # stays open. Mixed workout (paced intervals) classifies as key via the
    # structural form inference.
    completed_dates = ["2026-08-09", "2026-08-10", "2026-08-11"]
    program["weeks"][0]["workouts"][0]["tracking"] = {
        "status": "completed",
        "actual": {
            "distance_meters": 12_000,
            "duration_seconds": 4_200,
            "completed_at": f"{completed_dates[0]}T08:00:00",
        },
    }
    program["weeks"][0]["workouts"][1]["tracking"] = {
        "status": "completed",
        "actual": {
            "distance_meters": 8_000,
            "duration_seconds": 3_000,
            "completed_at": f"{completed_dates[1]}T08:00:00",
        },
    }
    program["weeks"][1]["workouts"][0]["tracking"] = {
        "status": "completed",
        "actual": {
            "distance_meters": 6_000,
            "duration_seconds": 1_800,
            "completed_at": f"{completed_dates[2]}T08:00:00",
        },
    }
    _write_program(tmp_path, program)
    handler = _request(
        tmp_path,
        "/api/coaching/recommendation",
        body=_base_body(target_day="2026-08-18", week=2, request_kind="key"),
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(200)
    payload = response_json(handler)
    assert payload["primary"]["recipe_key"]
    assert FORM_BY_NAME[payload["primary"]["form"]] in KEY_WORKOUT_FORMS


def test_coaching_endpoint_recovery_request_returns_recovery_run(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    _write_program(tmp_path)
    handler = _request(
        tmp_path,
        "/api/coaching/recommendation",
        body=_base_body(request_kind="recovery"),
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(200)
    payload = response_json(handler)
    assert payload["primary"]["form"] == "recovery_run"


def test_coaching_endpoint_empty_history_defaults_to_easy_run(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    _write_program(tmp_path)
    handler = _request(
        tmp_path,
        "/api/coaching/recommendation",
        body=_base_body(),
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    payload = response_json(handler)
    assert payload["primary"]["form"] == "easy_run"
