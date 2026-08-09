"""Web projection exposes a structured step view for each workout."""

from __future__ import annotations

from pathlib import Path

import yaml

from runplan.web import ProgramStore
from tests.helpers import program_data
from tests.web_helpers import MemoryStateRepository


def _store_with_plan(tmp_path: Path) -> ProgramStore:
    path = tmp_path / "plan.yaml"
    path.write_text(
        yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return ProgramStore(tmp_path, repository=MemoryStateRepository())


def test_workout_projection_includes_structured_steps(tmp_path: Path) -> None:
    store = _store_with_plan(tmp_path)
    view = store.get("plan.yaml")
    workouts = {workout["id"]: workout for week in view["weeks"] for workout in week["workouts"]}

    mixed = workouts["mixed"]
    assert isinstance(mixed["steps"], list)
    warmup, repeat, cooldown = mixed["steps"]
    assert warmup["action"] == "warmup"
    assert warmup["kind_label"] == "Warmup"
    assert warmup["end_value_display"] == "1 km"
    assert warmup["note"] is None
    assert repeat["action"] == "repeat"
    assert repeat["count"] == 2
    interval, recovery = repeat["steps"]
    assert interval["action"] == "run"
    assert interval["end_value_display"] == "400 m"
    assert interval["pace_display"] == "4:30-4:45 min/km"
    assert recovery["action"] == "recovery"
    assert recovery["end_value_display"] == "1 min 30 sec"
    assert cooldown["action"] == "cooldown"
    assert cooldown["end_value_display"] == "5 min"


def test_workout_projection_carries_step_note(tmp_path: Path) -> None:
    path = tmp_path / "plan.yaml"
    data = program_data()
    week1 = data["weeks"][0]["workouts"][0]
    week1["steps"][0] = {"warmup": {"time": "10m", "note": "Start slow, loosen up"}}
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    store = ProgramStore(tmp_path, repository=MemoryStateRepository())
    view = store.get("plan.yaml")
    workout = view["weeks"][0]["workouts"][0]

    assert workout["steps"][0]["note"] == "Start slow, loosen up"
    assert workout["steps"][0]["kind_label"] == "Warmup"
    assert workout["steps"][0]["end_value_display"] == "10 min"


def test_workout_projection_includes_easy_run_without_note(tmp_path: Path) -> None:
    store = _store_with_plan(tmp_path)
    view = store.get("plan.yaml")
    workouts = {workout["id"]: workout for week in view["weeks"] for workout in week["workouts"]}

    easy = workouts["easy"]
    assert [step["kind_label"] for step in easy["steps"]] == ["Run"]
    assert easy["steps"][0]["end_value_display"] == "5 km"
    assert easy["steps"][0]["note"] is None
    assert easy["steps"][0]["pace_display"] is None
