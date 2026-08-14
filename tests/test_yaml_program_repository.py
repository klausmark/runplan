"""Production implementation of the :class:`ProgramRepository` port.

The tests exercise the load/save contract and the error paths for an
unknown ``program_id``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runplan.state.yaml_program_repository import YamlProgramRepository
from tests.helpers import program_data


@pytest.fixture
def yaml_file(tmp_path: Path) -> Path:
    import yaml

    path = tmp_path / "plan.yaml"
    yaml.safe_dump(program_data(), path.open("w"), sort_keys=False, allow_unicode=True)
    return path


def test_load_returns_program_document(yaml_file: Path) -> None:
    repo = YamlProgramRepository(yaml_file)
    document = repo.load("characterization-plan")
    assert document["program"]["id"] == "characterization-plan"


def test_load_unknown_program_id_raises_key_error(yaml_file: Path) -> None:
    repo = YamlProgramRepository(yaml_file)
    with pytest.raises(KeyError):
        repo.load("not-this-program")


def test_load_missing_file_raises_key_error(tmp_path: Path) -> None:
    repo = YamlProgramRepository(tmp_path / "missing.yaml")
    with pytest.raises(KeyError):
        repo.load("anything")


def test_save_writes_updated_document(yaml_file: Path) -> None:
    repo = YamlProgramRepository(yaml_file)
    raw = repo.load("characterization-plan")
    new_week = {"week": 3, "workouts": []}
    raw["weeks"].append(new_week)
    repo.save("characterization-plan", raw)

    # Re-read the file directly
    import yaml

    with yaml_file.open() as f:
        document = yaml.safe_load(f)
    assert any(week.get("week") == 3 for week in document["weeks"])


def test_save_rejects_mismatched_program_id(yaml_file: Path) -> None:
    repo = YamlProgramRepository(yaml_file)
    raw = repo.load("characterization-plan")
    raw["program"]["id"] = "different"
    with pytest.raises(ValueError, match="program.id"):
        repo.save("characterization-plan", raw)


def test_save_then_load_returns_modified_program(yaml_file: Path) -> None:
    repo = YamlProgramRepository(yaml_file)
    raw = repo.load("characterization-plan")
    raw["weeks"][0]["workouts"].append(
        {
            "id": "added-workout",
            "day": 7,
            "name": "Added workout",
            "steps": [{"run": {"distance": "3km"}}],
            "schedule_date": "2027-01-03",
        }
    )
    repo.save("characterization-plan", raw)

    fresh = YamlProgramRepository(yaml_file)
    reloaded = fresh.load("characterization-plan")
    assert any(workout.get("id") == "added-workout" for workout in reloaded["weeks"][0]["workouts"])


def test_save_isolates_subsequent_mutations_from_disk(yaml_file: Path) -> None:
    repo = YamlProgramRepository(yaml_file)
    raw = repo.load("characterization-plan")
    raw["weeks"][0]["workouts"].append({"id": "x", "day": 5, "name": "x", "steps": []})
    repo.save("characterization-plan", raw)

    # Mutate after save; this must not affect the file on disk.
    raw["weeks"][0]["workouts"].clear()

    fresh = YamlProgramRepository(yaml_file)
    reloaded = fresh.load("characterization-plan")
    assert any(workout.get("id") == "x" for workout in reloaded["weeks"][0]["workouts"])
