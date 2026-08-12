"""Per-action coverage for the canonical step vocabulary.

Step 1 makes `walk` and `rest` first-class actions alongside the existing
`warmup`, `run`, `recovery`, `cooldown`, and `repeat`. This module asserts the
parser, estimator, Garmin mapper, and presentation formatters all behave
consistently for every supported action.
"""

from __future__ import annotations

import pytest

from runplan import WorkoutDefinitionError, compile_steps
from runplan.domain.estimates import estimate_steps
from runplan.domain.models import Step
from runplan.domain.steps import normalize_action
from runplan.presentation.text import (
    format_model_step_summary,
    format_model_steps,
    format_step_overview,
    step_summary,
)


@pytest.mark.parametrize("action", ["warmup", "run", "walk", "recovery", "rest", "cooldown"])
def test_normalize_action_accepts_canonical_action(action: str) -> None:
    assert normalize_action(action, "steps[1]") == action


@pytest.mark.parametrize("action", ["WALK", " Recovery ", "Rest"])
def test_normalize_action_accepts_canonical_action_with_case_and_whitespace(action: str) -> None:
    expected = action.strip().lower()
    assert normalize_action(action, "steps[1]") == expected


def test_normalize_action_rejects_unknown_action() -> None:
    with pytest.raises(WorkoutDefinitionError, match="unknown step 'jog'"):
        normalize_action("jog", "steps[1]")


def test_normalize_action_error_lists_full_action_set() -> None:
    with pytest.raises(
        WorkoutDefinitionError, match="warmup, run, walk, recovery, rest, cooldown or repeat"
    ):
        normalize_action("jog", "steps[1]")


def test_non_text_action_is_rejected() -> None:
    with pytest.raises(WorkoutDefinitionError, match="the step name must be text"):
        normalize_action(42, "steps[1]")


@pytest.mark.parametrize(
    ("action", "expected_label"),
    [
        ("warmup", "Warmup"),
        ("run", "Run"),
        ("walk", "Walk"),
        ("recovery", "Recovery"),
        ("rest", "Rest"),
        ("cooldown", "Cooldown"),
    ],
)
def test_format_model_steps_uses_per_action_label(action: str, expected_label: str) -> None:
    step = Step(action=action, end_kind="time", end_value=60.0)

    rendered = format_model_steps((step,), indent="")

    assert rendered.startswith(f"{expected_label}:")


@pytest.mark.parametrize(
    ("action", "expected_label"),
    [
        ("warmup", "Warmup"),
        ("run", "Run"),
        ("walk", "Walk"),
        ("recovery", "Recovery"),
        ("rest", "Rest"),
        ("cooldown", "Cooldown"),
    ],
)
def test_format_model_step_summary_uses_per_action_label(action: str, expected_label: str) -> None:
    step = Step(action=action, end_kind="time", end_value=60.0)

    summary = format_model_step_summary((step,))

    assert summary.startswith(f"{expected_label} ")


@pytest.mark.parametrize(
    ("action", "expected_label"),
    [
        ("warmup", "Warmup"),
        ("run", "Run"),
        ("walk", "Walk"),
        ("recovery", "Recovery"),
        ("rest", "Rest"),
        ("cooldown", "Cooldown"),
    ],
)
def test_step_summary_uses_per_action_label(action: str, expected_label: str) -> None:
    summary = step_summary([{action: "1m"}])

    assert summary.startswith(f"{expected_label} 1 min")


@pytest.mark.parametrize(
    ("action", "expected_label"),
    [
        ("warmup", "Warmup"),
        ("run", "Run"),
        ("walk", "Walk"),
        ("recovery", "Recovery"),
        ("rest", "Rest"),
        ("cooldown", "Cooldown"),
    ],
)
def test_format_step_overview_uses_per_action_label(action: str, expected_label: str) -> None:
    rendered = format_step_overview([{action: "1m"}])

    assert f"{expected_label}: 1 min" in rendered


def test_warmup_and_cooldown_keep_default_garmin_descriptions() -> None:
    warmup, cooldown = compile_steps([{"warmup": "5m"}, {"cooldown": "5m"}])

    assert warmup.description == "Warm up"
    assert cooldown.description == "Cool down"


def test_walk_and_rest_have_empty_default_garmin_description() -> None:
    walk, rest = compile_steps([{"walk": "1m"}, {"rest": "1m"}])

    assert walk.description == ""
    assert rest.description == ""


def test_walk_and_rest_use_note_as_garmin_description() -> None:
    walk, rest = compile_steps(
        [
            {"walk": {"time": "1m", "note": "Brisk pace"}},
            {"rest": {"time": "30s", "note": "Stand easy"}},
        ]
    )

    assert walk.description == "Brisk pace"
    assert rest.description == "Stand easy"


def test_walk_compiles_to_recovery_garmin_step_type() -> None:
    walk = compile_steps([{"walk": "1m"}])[0]

    assert walk.stepType["stepTypeKey"] == "recovery"
    assert walk.stepType["stepTypeId"] == 4


def test_rest_compiles_to_rest_garmin_step_type() -> None:
    rest = compile_steps([{"rest": "30s"}])[0]

    assert rest.stepType["stepTypeKey"] == "rest"
    assert rest.stepType["stepTypeId"] == 5


def test_recovery_compiles_to_recovery_garmin_step_type_with_default_label() -> None:
    recovery = compile_steps([{"recovery": "90s"}])[0]

    assert recovery.stepType["stepTypeKey"] == "recovery"
    assert recovery.stepType["stepTypeId"] == 4
    assert recovery.description == "Recovery"


def test_walk_and_rest_round_trip_inside_repeat_group() -> None:
    compiled = compile_steps(
        [
            {
                "repeat": {
                    "count": 2,
                    "steps": [
                        {"walk": "1m"},
                        {"rest": "30s"},
                    ],
                }
            }
        ]
    )

    assert compiled[0].numberOfIterations == 2
    walk, rest = compiled[0].workoutSteps
    assert walk.stepType["stepTypeKey"] == "recovery"
    assert rest.stepType["stepTypeKey"] == "rest"


def test_walk_time_step_contributes_distance_via_fallback_pace() -> None:
    estimate = estimate_steps((Step(action="walk", end_kind="time", end_value=600.0),))

    assert estimate.duration_seconds == 600.0
    assert estimate.distance_meters == pytest.approx(1666.67, rel=0.01)
    assert estimate.distance_is_approximate is True


def test_recovery_time_step_does_not_contribute_distance() -> None:
    estimate = estimate_steps((Step(action="recovery", end_kind="time", end_value=120.0),))

    assert estimate.duration_seconds == 120.0
    assert estimate.distance_meters == 0.0
    assert estimate.distance_is_approximate is False


def test_rest_time_step_does_not_contribute_distance() -> None:
    estimate = estimate_steps((Step(action="rest", end_kind="time", end_value=120.0),))

    assert estimate.duration_seconds == 120.0
    assert estimate.distance_meters == 0.0
    assert estimate.distance_is_approximate is False


def test_walk_with_distance_end_uses_explicit_distance() -> None:
    estimate = estimate_steps((Step(action="walk", end_kind="distance", end_value=400.0),))

    assert estimate.distance_meters == 400.0
    assert estimate.duration_is_approximate is True


def test_step_action_literal_includes_walk_and_rest() -> None:
    from runplan.domain.models import StepAction

    sample: StepAction = "walk"
    assert sample == "walk"
    sample_rest: StepAction = "rest"
    assert sample_rest == "rest"


def test_walk_and_rest_round_trip_through_typed_program() -> None:
    from runplan import load_program_model
    from tests.helpers import program_data

    raw = program_data()
    raw["weeks"][0]["workouts"][0]["steps"] = [
        {"warmup": "5m"},
        {
            "repeat": {
                "count": 3,
                "steps": [
                    {"run": "1m"},
                    {"walk": "1m"},
                    {"rest": "30s"},
                ],
            }
        },
        {"cooldown": "5m"},
    ]

    workout = load_program_model(raw).week(1).workouts[0]
    actions = [step.action for step in workout.steps]
    assert actions[0] == "warmup"
    assert actions[1] == "repeat"
    assert [step.action for step in workout.steps[1].steps] == ["run", "walk", "rest"]
    assert actions[2] == "cooldown"


def test_walk_and_rest_round_trip_through_garmin_payload() -> None:
    from runplan import build_workout, load_program_model
    from tests.helpers import program_data

    raw = program_data()
    raw["weeks"][0]["workouts"][0]["steps"] = [
        {"warmup": "5m"},
        {
            "repeat": {
                "count": 2,
                "steps": [
                    {"walk": "1m"},
                    {"rest": "30s"},
                ],
            }
        },
        {"cooldown": "5m"},
    ]

    workout = load_program_model(raw).week(1).workouts[0]
    payload = build_workout(workout).to_dict()
    steps = payload["workoutSegments"][0]["workoutSteps"]
    repeat = steps[1]
    walk, rest = repeat["workoutSteps"]

    assert walk["stepType"]["stepTypeKey"] == "recovery"
    assert rest["stepType"]["stepTypeKey"] == "rest"
