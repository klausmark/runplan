"""Server tests for the rolling-plan HTTP surface (Step 11).

The two endpoints ``/api/everyday/propose`` and ``/api/everyday/accept``
expose the Step 10 ``propose_horizon`` and ``accept_horizon`` use cases
to the Studio. The tests focus on the HTTP contract — input validation,
response shape, and round-trip with the program repository — rather
than the generator itself.
"""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import date
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

import pytest
import yaml

from runplan.users import RunplanUser
from runplan.web import ProgramStore, WebSyncService
from runplan.web_auth import login_proof
from runplan.web_everyday import (
    DEFAULT_HORIZON_DAYS,
    DEFAULT_TRAINING_DAYS,
    EverydayRequestError,
    accept_response,
    propose_response,
)
from tests.fakes import InMemoryProgramRepository
from tests.helpers import program_data
from tests.web_helpers import MemoryStateRepository, fake_authenticator

_TODAY = date(2026, 8, 12)


# ---------------------------------------------------------------------------
# Direct adapter — propose_response
# ---------------------------------------------------------------------------


def _user(tmp_path: Path, *, five_k_best: str = "25:00") -> RunplanUser:
    return RunplanUser(
        id="local-default",
        name="Local user",
        credentials_file=tmp_path / "credentials.toml",
        token_store=tmp_path / "tokens",
        state_directory=tmp_path / "state",
        five_k_best=five_k_best,
    )


def _write_program(tmp_path: Path, program: dict | None = None) -> Path:
    path = tmp_path / "plan.yaml"
    payload = deepcopy(program or program_data())
    path.write_text(yaml.safe_dump(payload, allow_unicode=True, sort_keys=False), encoding="utf-8")
    return path


def _propose_payload(**overrides) -> dict:
    body = {"userId": "local-default", "program_file": "plan.yaml"}
    body.update(overrides)
    return body


def test_propose_response_returns_horizon_for_default_fixture(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    response = propose_response(
        _propose_payload(),
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        today=_TODAY,
        repository=repository,
    )
    assert response["goal"] == "maintain"
    assert response["horizon_days"] == DEFAULT_HORIZON_DAYS
    assert response["start_date"] == date(2027, 1, 11).isoformat()
    assert isinstance(response["days"], list)
    assert len(response["days"]) > 0
    assert all("recipe_key" in day and "form_label" in day for day in response["days"])
    assert all("estimate" in day for day in response["days"])
    assert all("reasoning" in day for day in response["days"])
    assert response["horizon_payload"]["days"]


def test_propose_response_defaults_training_days_when_missing(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    response = propose_response(
        _propose_payload(),
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        today=_TODAY,
        repository=repository,
    )
    assert response["horizon_payload"]["profile"]["training_days"] == list(DEFAULT_TRAINING_DAYS)


def test_propose_response_uses_explicit_start_date_when_provided(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    response = propose_response(
        _propose_payload(start_date="2027-02-01"),
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        today=_TODAY,
        repository=repository,
    )
    assert response["start_date"] == "2027-02-01"


def test_propose_response_uses_explicit_horizon_days_when_provided(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    response = propose_response(
        _propose_payload(horizon_days=7),
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        today=_TODAY,
        repository=repository,
    )
    assert response["horizon_days"] == 7


def test_propose_response_groups_days_by_iso_week(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    response = propose_response(
        _propose_payload(),
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        today=_TODAY,
        repository=repository,
    )
    weeks = response["weeks"]
    assert weeks, "expected at least one ISO week in the default fixture horizon"
    labels = [week["label"] for week in weeks]
    assert all(label.startswith("Week ") for label in labels)
    assert len(weeks) >= 2


def test_propose_response_rejects_unknown_goal(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    with pytest.raises(EverydayRequestError) as excinfo:
        propose_response(
            _propose_payload(goal="surprise"),
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            today=_TODAY,
            repository=repository,
        )
    assert excinfo.value.status.value == 400
    assert "goal" in str(excinfo.value)


def test_propose_response_rejects_invalid_training_day(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    with pytest.raises(EverydayRequestError) as excinfo:
        propose_response(
            _propose_payload(training_days=[1, 9]),
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            today=_TODAY,
            repository=repository,
        )
    assert excinfo.value.status.value == 400
    assert "training_days" in str(excinfo.value)


def test_propose_response_rejects_invalid_start_date(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    with pytest.raises(EverydayRequestError) as excinfo:
        propose_response(
            _propose_payload(start_date="2027/02/01"),
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            today=_TODAY,
            repository=repository,
        )
    assert excinfo.value.status.value == 400
    assert "start_date" in str(excinfo.value)


def test_propose_response_rejects_invalid_horizon_days(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    with pytest.raises(EverydayRequestError) as excinfo:
        propose_response(
            _propose_payload(horizon_days=0),
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            today=_TODAY,
            repository=repository,
        )
    assert excinfo.value.status.value == 400
    assert "horizon_days" in str(excinfo.value)


def test_propose_response_falls_back_when_program_text_is_empty(tmp_path: Path) -> None:
    repository = InMemoryProgramRepository({})
    with pytest.raises(EverydayRequestError) as excinfo:
        propose_response(
            _propose_payload(),
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text="",
            today=_TODAY,
            repository=repository,
        )
    assert excinfo.value.status.value == 404


# ---------------------------------------------------------------------------
# Direct adapter — accept_response
# ---------------------------------------------------------------------------


def _propose_and_payload(tmp_path: Path) -> tuple[InMemoryProgramRepository, dict]:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    response = propose_response(
        _propose_payload(),
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        today=_TODAY,
        repository=repository,
    )
    return repository, response["horizon_payload"]


def test_accept_response_writes_days_into_program(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository, horizon_payload = _propose_and_payload(tmp_path)
    response = accept_response(
        {"userId": "local-default", "program_file": "plan.yaml", "horizon": horizon_payload},
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        repository=repository,
    )
    accepted = response["accepted"]
    assert accepted["program_id"] == program_data()["program"]["id"]
    assert len(accepted["days"]) == len(horizon_payload["days"])
    assert all(entry["recipe_key"] for entry in accepted["days"])
    assert len(repository.saves) >= 1


def test_accept_response_rejects_double_accept_with_conflict(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository, horizon_payload = _propose_and_payload(tmp_path)
    accept_response(
        {"userId": "local-default", "program_file": "plan.yaml", "horizon": horizon_payload},
        user=_user(tmp_path),
        program_file="plan.yaml",
        program_text=path.read_text(encoding="utf-8"),
        repository=repository,
    )
    with pytest.raises(EverydayRequestError) as excinfo:
        accept_response(
            {"userId": "local-default", "program_file": "plan.yaml", "horizon": horizon_payload},
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            repository=repository,
        )
    assert excinfo.value.status.value == 409
    assert "day" in str(excinfo.value).lower()


def test_accept_response_rejects_missing_horizon_payload(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository = InMemoryProgramRepository(
        {program_data()["program"]["id"]: deepcopy(program_data())}
    )
    with pytest.raises(EverydayRequestError) as excinfo:
        accept_response(
            {"userId": "local-default", "program_file": "plan.yaml"},
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            repository=repository,
        )
    assert excinfo.value.status.value == 400
    assert "horizon" in str(excinfo.value).lower()


def test_accept_response_rejects_unknown_recipe(tmp_path: Path) -> None:
    path = _write_program(tmp_path)
    repository, horizon_payload = _propose_and_payload(tmp_path)
    broken = deepcopy(horizon_payload)
    broken["days"][0]["recipe_key"] = "does.not.exist"
    with pytest.raises(EverydayRequestError) as excinfo:
        accept_response(
            {"userId": "local-default", "program_file": "plan.yaml", "horizon": broken},
            user=_user(tmp_path),
            program_file="plan.yaml",
            program_text=path.read_text(encoding="utf-8"),
            repository=repository,
        )
    assert excinfo.value.status.value in (400, 422)


# ---------------------------------------------------------------------------
# HTTP endpoint
# ---------------------------------------------------------------------------


def make_handler_for_sync(store: ProgramStore, sync: WebSyncService, auth):
    from runplan.web_auth_http import WebAuthHttpAdapter
    from runplan.web_http import make_handler

    handler_class = make_handler(store, sync_service=sync, authenticator=auth)
    return type(
        "BoundHandler",
        (handler_class,),
        {"auth": WebAuthHttpAdapter(auth)},
    )


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


def _authed_request(tmp_path: Path, path: str, body: dict) -> tuple[object, object]:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    _write_program(tmp_path)
    handler = _request(tmp_path, path, body=body, authenticator=auth, cookie=cookie)
    return handler, auth


def test_propose_endpoint_returns_horizon_for_known_program(tmp_path: Path) -> None:
    handler, _ = _authed_request(tmp_path, "/api/everyday/propose", _propose_payload())
    handler.do_POST()
    handler.send_response.assert_called_once_with(200)
    payload = response_json(handler)
    assert payload["goal"] == "maintain"
    assert payload["horizon_days"] == 14
    assert isinstance(payload["days"], list) and payload["days"]
    assert payload["horizon_payload"]["days"]


def test_propose_endpoint_returns_400_for_unknown_goal(tmp_path: Path) -> None:
    handler, _ = _authed_request(
        tmp_path, "/api/everyday/propose", _propose_payload(goal="surprise")
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(400)
    payload = response_json(handler)
    assert "goal" in payload["error"]


def test_propose_endpoint_returns_404_for_missing_program(tmp_path: Path) -> None:
    handler, _ = _authed_request(
        tmp_path, "/api/everyday/propose", _propose_payload(program_file="ghost.yaml")
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(404)


def test_accept_endpoint_writes_days_and_returns_summary(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    _write_program(tmp_path)
    propose_handler = _request(
        tmp_path,
        "/api/everyday/propose",
        body=_propose_payload(),
        authenticator=auth,
        cookie=cookie,
    )
    propose_handler.do_POST()
    propose_payload = response_json(propose_handler)
    accept_body = {
        "userId": "local-default",
        "program_file": "plan.yaml",
        "horizon": propose_payload["horizon_payload"],
    }
    accept_handler = _request(
        tmp_path, "/api/everyday/accept", body=accept_body, authenticator=auth, cookie=cookie
    )
    accept_handler.do_POST()
    accept_handler.send_response.assert_called_once_with(200)
    accept_response_payload = response_json(accept_handler)
    accepted = accept_response_payload["accepted"]
    assert accepted["program_id"] == program_data()["program"]["id"]
    assert len(accepted["days"]) == len(propose_payload["days"])
    assert all(entry["recipe_key"] for entry in accepted["days"])


def test_accept_endpoint_returns_409_on_double_accept(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    _write_program(tmp_path)
    propose_handler = _request(
        tmp_path,
        "/api/everyday/propose",
        body=_propose_payload(),
        authenticator=auth,
        cookie=cookie,
    )
    propose_handler.do_POST()
    propose_payload = response_json(propose_handler)
    accept_body = {
        "userId": "local-default",
        "program_file": "plan.yaml",
        "horizon": propose_payload["horizon_payload"],
    }
    first = _request(
        tmp_path, "/api/everyday/accept", body=accept_body, authenticator=auth, cookie=cookie
    )
    first.do_POST()
    second = _request(
        tmp_path, "/api/everyday/accept", body=accept_body, authenticator=auth, cookie=cookie
    )
    second.do_POST()
    second.send_response.assert_called_once_with(409)
