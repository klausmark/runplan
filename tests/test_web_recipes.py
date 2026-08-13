"""Server tests for the recipe HTTP surface (Step 7)."""

from __future__ import annotations

import json
from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from runplan.web import ProgramStore, make_handler
from runplan.web_auth import login_proof
from runplan.web_recipes import (
    FORM_ORDER,
    list_recipes_response,
    preview_recipe_response,
)
from tests.web_helpers import fake_authenticator


def request_recipes(
    tmp_path: Path,
    path: str,
    *,
    body: dict | None = None,
    method: str = "GET",
    authenticator=None,
    cookie: str | None = None,
):
    auth = authenticator or fake_authenticator()
    handler = object.__new__(make_handler(ProgramStore(tmp_path), authenticator=auth))
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
    challenge = request_recipes(tmp_path, "/api/auth/challenge", authenticator=auth)
    challenge.do_GET()
    challenge_payload = response_json(challenge)
    login = request_recipes(
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


# ---------------------------------------------------------------------------
# list_recipes_response — catalogue projection
# ---------------------------------------------------------------------------


def test_list_recipes_response_returns_all_six_forms_in_stable_order() -> None:
    response = list_recipes_response()
    assert [form["name"] for form in response["forms"]] == list(FORM_ORDER)


def test_list_recipes_response_groups_easy_recipes_under_easy_run() -> None:
    response = list_recipes_response()
    by_name = {form["name"]: form for form in response["forms"]}
    easy = by_name["easy_run"]["recipes"]
    assert {recipe["key"] for recipe in easy} >= {
        "easy.continuous",
        "easy.with_strides",
        "easy.warmup_run",
    }


def test_list_recipes_response_includes_parameter_schema() -> None:
    response = list_recipes_response()
    steady = next(
        recipe
        for form in response["forms"]
        for recipe in form["recipes"]
        if recipe["key"] == "long.steady"
    )
    field_map = {field["name"]: field for field in steady["parameters"]}
    assert field_map["target_km"]["type"] == "number"
    assert field_map["target_km"]["default"] == 10.0
    assert field_map["pace"]["type"] == "pace_range"
    assert field_map["pace"]["default"] is None
    assert field_map["pace"]["required"] is True


def test_list_recipes_response_flags_pace_range_for_tempo_recipes() -> None:
    response = list_recipes_response()
    tempo = next(
        recipe
        for form in response["forms"]
        for recipe in form["recipes"]
        if recipe["key"] == "tempo.continuous"
    )
    pace = next(field for field in tempo["parameters"] if field["name"] == "pace")
    assert pace["type"] == "pace_range"
    assert pace["default"] == ("5:00", "5:00")


def test_get_recipes_endpoint_returns_catalogue(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    handler = request_recipes(tmp_path, "/api/recipes", authenticator=auth, cookie=cookie)
    handler.do_GET()
    handler.send_response.assert_called_once_with(200)
    payload = response_json(handler)
    assert [form["name"] for form in payload["forms"]] == list(FORM_ORDER)
    assert sum(len(form["recipes"]) for form in payload["forms"]) >= 18


# ---------------------------------------------------------------------------
# preview_recipe_response — parameter coercion and step projection
# ---------------------------------------------------------------------------


def test_preview_recipe_response_returns_steps_and_totals_for_easy_continuous() -> None:
    payload = preview_recipe_response(
        {"recipe_key": "easy.continuous", "parameters": {"minutes": 30}}
    )
    assert payload["form"] == "easy_run"
    assert payload["name"] == "Easy continuous run"
    assert len(payload["steps"]) == 3
    assert payload["estimated_duration_seconds"] > 0
    assert payload["estimated_distance_meters"] > 0


def test_preview_recipe_response_handles_pace_range_fields() -> None:
    payload = preview_recipe_response(
        {
            "recipe_key": "tempo.continuous",
            "parameters": {"minutes": 25, "pace": ["5:00", "5:10"]},
        }
    )
    assert payload["form"] == "tempo_run"
    paced_step = next(step for step in payload["steps"] if step["action"] == "run")
    assert paced_step["pace_display"] == "5:00-5:10 min/km"


def test_preview_recipe_response_treats_blank_optional_pace_as_no_pace() -> None:
    payload = preview_recipe_response(
        {
            "recipe_key": "long.steady",
            "parameters": {"target_km": 10.0, "pace": ["", ""]},
        }
    )
    assert payload["form"] == "long_run"
    paced_step = next(step for step in payload["steps"] if step["action"] == "run")
    assert paced_step["pace_display"] is None


def test_preview_recipe_response_rejects_half_filled_pace_range(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    handler = request_recipes(
        tmp_path,
        "/api/recipes/preview",
        body={
            "recipe_key": "long.steady",
            "parameters": {"target_km": 10.0, "pace": ["5:00", ""]},
        },
        method="POST",
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(422)
    payload = response_json(handler)
    assert "both sides" in payload["error"]


def test_preview_recipe_response_returns_422_on_invalid_parameters(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    handler = request_recipes(
        tmp_path,
        "/api/recipes/preview",
        body={"recipe_key": "easy.continuous", "parameters": {"minutes": -1}},
        method="POST",
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(422)
    payload = response_json(handler)
    assert "minutes" in payload["error"].lower()


def test_preview_recipe_response_returns_404_for_unknown_recipe(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    handler = request_recipes(
        tmp_path,
        "/api/recipes/preview",
        body={"recipe_key": "not.a.recipe", "parameters": {}},
        method="POST",
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(404)


def test_preview_recipe_response_returns_400_for_missing_recipe_key(tmp_path: Path) -> None:
    auth = fake_authenticator()
    cookie = authorized_cookie(tmp_path, auth)
    handler = request_recipes(
        tmp_path,
        "/api/recipes/preview",
        body={"parameters": {}},
        method="POST",
        authenticator=auth,
        cookie=cookie,
    )
    handler.do_POST()
    handler.send_response.assert_called_once_with(400)


# ---------------------------------------------------------------------------
# Round-trip — preview step projection survives the same projection as a saved
# workout so the Studio week preview does not drift from the calendar.
# ---------------------------------------------------------------------------


def test_preview_steps_use_the_same_view_shape_as_saved_workouts() -> None:
    import yaml

    from runplan.web_programs import ProgramStore
    from tests.helpers import program_data
    from tests.web_helpers import MemoryStateRepository

    preview = preview_recipe_response(
        {"recipe_key": "easy.continuous", "parameters": {"minutes": 30}}
    )
    preview_keys = sorted(preview["steps"][0].keys())

    path = Path("/tmp/runplan-recipes-roundtrip.yaml")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    store = ProgramStore(path.parent, repository=MemoryStateRepository())
    view = store.get(path.name)
    saved_step = view["weeks"][0]["workouts"][0]["steps"][0]
    saved_keys = sorted(saved_step.keys())

    assert preview_keys == saved_keys
    assert preview["steps"][0]["kind_label"] == saved_step["kind_label"]
