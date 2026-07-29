from __future__ import annotations

import pytest

from runplan.domain.estimates import estimate_steps
from runplan.domain.workout_titles import format_compact_distance, garmin_workout_title
from runplan.parsing.yaml_loader import load_program_model
from tests.helpers import program_data


def test_exact_distance_is_formatted_compactly() -> None:
    workout = load_program_model(program_data()).week(2).workouts[0]

    estimate = estimate_steps(workout.steps)

    assert format_compact_distance(estimate) == "10k"
    assert garmin_workout_title("CHAR", 2, workout) == "CHAR - W2 - Week 2 - Long - 10k"


def test_fallback_pace_marks_timed_distance_as_approximate() -> None:
    workout = load_program_model(program_data()).week(1).workouts[0]

    estimate = estimate_steps(workout.steps)

    assert estimate.distance_is_approximate
    assert estimate.distance_meters == pytest.approx(2633.333, abs=0.001)
    assert format_compact_distance(estimate) == "~2.6k"
    assert garmin_workout_title("CHAR", 1, workout, workout_name="Mixed") == (
        "CHAR - W1 - Mixed - ~2.6k"
    )


def test_explicit_pace_keeps_timed_distance_exact() -> None:
    raw = program_data()
    raw["weeks"][0]["workouts"][0]["steps"] = [{"run": {"time": "10m", "pace": "5:00 min/km"}}]
    workout = load_program_model(raw).week(1).workouts[0]

    estimate = estimate_steps(workout.steps)

    assert not estimate.distance_is_approximate
    assert estimate.distance_meters == 2000
    assert format_compact_distance(estimate) == "2k"
