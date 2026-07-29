import json
from pathlib import Path

import pytest

from runplan import load_state, save_state, state_path
from runplan.state.json_repository import CURRENT_STATE_VERSION


@pytest.fixture
def state_directory(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("GARMIN_STATE_DIR", str(tmp_path))
    return tmp_path


def test_state_round_trip_is_utf8_and_atomic_temp_file_is_removed(state_directory) -> None:
    state = {
        "program_id": "unicode-plan",
        "workouts": {"week-01/a": {"name": "Løb med overskud"}},
    }

    save_state("unicode-plan", state)

    loaded = load_state("unicode-plan")
    assert loaded.pop("schema_version") == CURRENT_STATE_VERSION
    assert loaded["workouts"]["week-01/a"].pop("status") == "planned"
    assert loaded == state
    assert "ø" in state_path("unicode-plan").read_text(encoding="utf-8")
    assert not (state_directory / "unicode-plan.tmp").exists()


def test_invalid_state_is_rejected(state_directory) -> None:
    (state_directory / "expected.json").write_text(
        json.dumps({"program_id": "other", "workouts": {}}), encoding="utf-8"
    )

    with pytest.raises(SystemExit, match="invalid format"):
        load_state("expected")


def test_legacy_state_without_version_is_migrated_in_memory(state_directory) -> None:
    path = state_directory / "legacy.json"
    path.write_text(json.dumps({"program_id": "legacy", "workouts": {}}), encoding="utf-8")

    state = load_state("legacy")

    assert state["schema_version"] == CURRENT_STATE_VERSION
    assert "schema_version" not in json.loads(path.read_text())


def test_version_one_state_gains_lifecycle_status(state_directory) -> None:
    path = state_directory / "legacy.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "program_id": "legacy",
                "workouts": {"scheduled": {"schedule_id": 10}, "planned": {}},
            }
        ),
        encoding="utf-8",
    )

    state = load_state("legacy")

    assert state["schema_version"] == CURRENT_STATE_VERSION
    assert state["workouts"]["scheduled"]["status"] == "scheduled"
    assert state["workouts"]["planned"]["status"] == "planned"


def test_state_from_newer_schema_is_rejected(state_directory) -> None:
    (state_directory / "future.json").write_text(
        json.dumps(
            {
                "schema_version": CURRENT_STATE_VERSION + 1,
                "program_id": "future",
                "workouts": {},
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit, match="newer than supported"):
        load_state("future")


def test_non_object_state_is_rejected_as_invalid_format(state_directory) -> None:
    (state_directory / "list-state.json").write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit, match="invalid format"):
        load_state("list-state")
