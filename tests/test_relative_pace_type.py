"""Tests for the relative pace_type YAML field on workout steps."""

from __future__ import annotations

import pytest

from runplan import WorkoutDefinitionError, load_program_model
from runplan.domain.pace import PACE_INTENSITIES, TRAINING_INTENSITY_OFFSETS
from runplan.domain.steps import estimate_duration
from runplan.integrations.garmin.mapper import build_workout, compile_steps

VALID_INTENSITIES = sorted(PACE_INTENSITIES | TRAINING_INTENSITY_OFFSETS)


def _program_with_step(step):
    return {
        "program": {
            "id": "pace-type",
            "name": "Pace type",
            "short_name": "PT",
            "description": "",
            "start_week": "2026-W01",
        },
        "weeks": [
            {
                "week": 1,
                "focus": "",
                "workouts": [
                    {
                        "id": "w",
                        "day": 1,
                        "name": "W",
                        "description": "",
                        "steps": [step],
                    }
                ],
            }
        ],
    }


def test_step_parses_pace_type_label() -> None:
    raw = _program_with_step({"run": {"time": "10m", "pace_type": "5k"}})
    workout = load_program_model(raw).week(1).workouts[0]
    step = workout.steps[0]
    assert step.pace is None
    assert step.pace_type == "5k"


@pytest.mark.parametrize("label", VALID_INTENSITIES)
def test_every_known_pace_type_is_accepted(label: str) -> None:
    raw = _program_with_step({"run": {"time": "10m", "pace_type": label}})
    workout = load_program_model(raw).week(1).workouts[0]
    assert workout.steps[0].pace_type == label


def test_unknown_pace_type_label_is_rejected() -> None:
    raw = _program_with_step({"run": {"time": "10m", "pace_type": "sprint"}})
    with pytest.raises(WorkoutDefinitionError, match="unknown pace_type"):
        load_program_model(raw)


def test_pace_and_pace_type_cannot_be_combined() -> None:
    raw = _program_with_step({"run": {"time": "10m", "pace": "5:00 min/km", "pace_type": "5k"}})
    with pytest.raises(ValueError, match="combine pace and pace_type"):
        load_program_model(raw)


def test_build_workout_resolves_symbolic_pace_to_garmin_target() -> None:
    raw = _program_with_step({"run": {"time": "10m", "pace_type": "5k"}})
    workout = load_program_model(raw).week(1).workouts[0]
    resolver_calls: list[str] = []

    def resolver(label: str) -> tuple[float, float]:
        resolver_calls.append(label)
        # 5K = 25:00 = 5:00/km = 300s/km. Zone ±5s => (295, 305).
        return (295.0, 305.0)

    garmin = build_workout(workout, resolve_pace_type=resolver)
    assert resolver_calls == ["5k"]
    step = garmin.workoutSegments[0].workoutSteps[0]
    # Garmin stores pace in m/s. (295, 305) seconds/km -> (3.39, 3.33) m/s.
    assert step.targetValueOne == pytest.approx(1000.0 / 305.0)
    assert step.targetValueTwo == pytest.approx(1000.0 / 295.0)


def test_compile_steps_requires_resolver_when_pace_type_is_set() -> None:
    with pytest.raises(WorkoutDefinitionError, match="pace_type"):
        compile_steps([{"run": {"time": "10m", "pace_type": "tempo"}}])


def test_compile_steps_keeps_explicit_pace_without_resolver() -> None:
    compiled = compile_steps([{"run": {"time": "10m", "pace": "5:00-5:10 min/km"}}])
    assert compiled[0].targetValueOne == pytest.approx(1000.0 / 310.0)


def test_repeat_with_pace_type_is_rejected() -> None:
    raw = {
        "program": {
            "id": "repeat-pt",
            "name": "Repeat pace type",
            "short_name": "RP",
            "description": "",
            "start_week": "2026-W01",
        },
        "weeks": [
            {
                "week": 1,
                "focus": "",
                "workouts": [
                    {
                        "id": "w",
                        "day": 1,
                        "name": "W",
                        "description": "",
                        "steps": [
                            {
                                "repeat": {
                                    "count": 2,
                                    "steps": [
                                        {"run": {"time": "1m", "pace_type": "5k"}},
                                    ],
                                }
                            }
                        ],
                    }
                ],
            }
        ],
    }
    with pytest.raises(WorkoutDefinitionError, match="cannot carry pace_type"):
        load_program_model(raw)


def test_estimate_duration_handles_pace_type_independently() -> None:
    duration = estimate_duration([{"run": {"time": "10m"}}])
    assert duration == 600
