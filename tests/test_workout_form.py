"""Workout form taxonomy and inference.

Step 2 introduces ``WorkoutForm`` as an authoring value that never enters
program YAML. Recipes pair an instantiated workout with an explicit form;
the parser infers a form from a workout's step structure when no recipe is
involved.
"""

from __future__ import annotations

from datetime import date

import pytest

from runplan import (
    Step,
    Workout,
    WorkoutForm,
    WorkoutFormName,
    WorkoutWithForm,
    load_program_model,
)
from runplan.domain.workout_form import (
    EASY_RUN,
    FORM_BY_NAME,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    RUN_WALK,
    TEMPO_RUN,
    infer_workout_form,
)
from tests.helpers import program_data


def _workout(steps: tuple[Step, ...]) -> Workout:
    return Workout(
        id="w1",
        day=1,
        name="Test",
        description=None,
        steps=steps,
        schedule_date=date(2026, 1, 5),
    )


# ---------------------------------------------------------------------------
# WorkoutForm and WorkoutWithForm construction
# ---------------------------------------------------------------------------


def test_workout_form_label_is_locked_to_canonical_value() -> None:
    with pytest.raises(ValueError, match="requires label 'Easy run'"):
        WorkoutForm(name="easy_run", label="Easy jog")


def test_workout_form_rejects_unknown_name() -> None:
    with pytest.raises(ValueError, match="unknown workout form"):
        WorkoutForm(name="hilly_run", label="Hilly run")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("form", "expected_label"),
    [
        (EASY_RUN, "Easy run"),
        (RUN_WALK, "Run/walk"),
        (RECOVERY_RUN, "Recovery run"),
        (LONG_RUN, "Long run"),
        (TEMPO_RUN, "Tempo run"),
        (INTERVAL_WORKOUT, "Interval workout"),
    ],
)
def test_canonical_constants_have_expected_labels(form: WorkoutForm, expected_label: str) -> None:
    assert form.label == expected_label


def test_form_by_name_contains_all_six_forms() -> None:
    expected_names: set[WorkoutFormName] = {
        "easy_run",
        "run_walk",
        "recovery_run",
        "long_run",
        "tempo_run",
        "interval_workout",
    }
    assert set(FORM_BY_NAME) == expected_names
    assert all(isinstance(form, WorkoutForm) for form in FORM_BY_NAME.values())


def test_workout_with_form_holds_workout_and_form() -> None:
    workout = _workout((Step(action="run", end_kind="time", end_value=600.0),))

    pair = WorkoutWithForm(workout=workout, form=EASY_RUN)

    assert pair.workout is workout
    assert pair.form is EASY_RUN


def test_workout_with_form_is_immutable() -> None:
    pair = WorkoutWithForm(workout=_workout(()), form=EASY_RUN)

    with pytest.raises((AttributeError, TypeError)):
        pair.form = LONG_RUN  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Inference — easy run (default) and recovery run
# ---------------------------------------------------------------------------


def test_infer_easy_run_for_continuous_run_with_warmup_and_cooldown() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=300.0),
            Step(action="run", end_kind="time", end_value=1800.0),
            Step(action="cooldown", end_kind="time", end_value=300.0),
        )
    )

    assert infer_workout_form(workout) is EASY_RUN


def test_infer_easy_run_for_long_distance_run() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(action="run", end_kind="distance", end_value=12000.0),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is EASY_RUN


def test_infer_recovery_run_when_single_short_run_step() -> None:
    workout = _workout((Step(action="run", end_kind="time", end_value=1200.0),))

    assert infer_workout_form(workout) is RECOVERY_RUN


def test_infer_easy_run_when_single_run_step_exceeds_recovery_threshold() -> None:
    workout = _workout((Step(action="run", end_kind="time", end_value=2400.0),))

    assert infer_workout_form(workout) is EASY_RUN


def test_infer_easy_run_when_single_run_step_has_distance() -> None:
    workout = _workout((Step(action="run", end_kind="distance", end_value=3000.0),))

    assert infer_workout_form(workout) is EASY_RUN


def test_infer_with_empty_steps_returns_easy_run() -> None:
    assert infer_workout_form(_workout(())) is EASY_RUN


# ---------------------------------------------------------------------------
# Inference — tempo run
# ---------------------------------------------------------------------------


def test_infer_tempo_run_when_single_run_step_has_pace() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(action="run", end_kind="time", end_value=1200.0, pace=(270.0, 285.0)),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is TEMPO_RUN


def test_infer_tempo_run_when_continuous_tempo_with_warmup_and_cooldown() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(action="run", end_kind="time", end_value=1200.0, pace=(270.0, 270.0)),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is TEMPO_RUN


def test_infer_does_not_consider_pace_on_recovery_step() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=300.0),
            Step(action="run", end_kind="time", end_value=600.0),
            Step(action="recovery", end_kind="time", end_value=120.0, pace=(300.0, 300.0)),
            Step(action="cooldown", end_kind="time", end_value=300.0),
        )
    )

    assert infer_workout_form(workout) is EASY_RUN


def test_infer_does_not_consider_pace_on_warmup_step() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=300.0, pace=(270.0, 285.0)),
            Step(action="run", end_kind="time", end_value=600.0),
            Step(action="cooldown", end_kind="time", end_value=300.0),
        )
    )

    assert infer_workout_form(workout) is EASY_RUN


# ---------------------------------------------------------------------------
# Inference — interval workout
# ---------------------------------------------------------------------------


def test_infer_interval_workout_when_repeat_has_run_and_recovery() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(
                action="repeat",
                count=4,
                steps=(
                    Step(action="run", end_kind="time", end_value=300.0, pace=(270.0, 285.0)),
                    Step(action="recovery", end_kind="time", end_value=90.0),
                ),
            ),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is INTERVAL_WORKOUT


def test_infer_interval_workout_when_repeat_has_run_and_rest() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(
                action="repeat",
                count=4,
                steps=(
                    Step(action="run", end_kind="time", end_value=300.0, pace=(270.0, 285.0)),
                    Step(action="rest", end_kind="time", end_value=60.0),
                ),
            ),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is INTERVAL_WORKOUT


def test_infer_interval_workout_takes_priority_over_paced_run() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(
                action="repeat",
                count=4,
                steps=(
                    Step(action="run", end_kind="time", end_value=300.0, pace=(270.0, 285.0)),
                    Step(action="recovery", end_kind="time", end_value=90.0),
                ),
            ),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is INTERVAL_WORKOUT
    assert infer_workout_form(workout) is not TEMPO_RUN


def test_infer_interval_workout_for_hill_repeats_without_pace() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(
                action="repeat",
                count=5,
                steps=(
                    Step(action="run", end_kind="time", end_value=60.0),
                    Step(action="recovery", end_kind="time", end_value=90.0),
                ),
            ),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is INTERVAL_WORKOUT


def test_infer_interval_workout_in_nested_repeat() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=600.0),
            Step(
                action="repeat",
                count=2,
                steps=(
                    Step(action="run", end_kind="time", end_value=300.0, pace=(270.0, 285.0)),
                    Step(
                        action="repeat",
                        count=3,
                        steps=(
                            Step(action="run", end_kind="time", end_value=60.0),
                            Step(action="recovery", end_kind="time", end_value=30.0),
                        ),
                    ),
                ),
            ),
            Step(action="cooldown", end_kind="time", end_value=600.0),
        )
    )

    assert infer_workout_form(workout) is INTERVAL_WORKOUT


# ---------------------------------------------------------------------------
# Inference — run/walk
# ---------------------------------------------------------------------------


def test_infer_run_walk_when_walk_step_present() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=420.0),
            Step(
                action="repeat",
                count=6,
                steps=(
                    Step(action="run", end_kind="time", end_value=30.0),
                    Step(action="walk", end_kind="time", end_value=120.0),
                ),
            ),
            Step(action="cooldown", end_kind="time", end_value=300.0),
        )
    )

    assert infer_workout_form(workout) is RUN_WALK


def test_infer_run_walk_when_walk_step_not_in_repeat() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=300.0),
            Step(action="run", end_kind="time", end_value=600.0),
            Step(action="walk", end_kind="time", end_value=600.0),
            Step(action="cooldown", end_kind="time", end_value=300.0),
        )
    )

    assert infer_workout_form(workout) is RUN_WALK


def test_infer_run_walk_takes_priority_over_paced_run() -> None:
    workout = _workout(
        (
            Step(action="warmup", end_kind="time", end_value=300.0),
            Step(action="run", end_kind="time", end_value=600.0, pace=(270.0, 285.0)),
            Step(action="walk", end_kind="time", end_value=300.0),
            Step(action="cooldown", end_kind="time", end_value=300.0),
        )
    )

    assert infer_workout_form(workout) is RUN_WALK
    assert infer_workout_form(workout) is not TEMPO_RUN


# ---------------------------------------------------------------------------
# Inference — round trip through the typed loader
# ---------------------------------------------------------------------------


def test_infer_form_after_round_trip_through_typed_program() -> None:
    raw = program_data()
    raw["weeks"][0]["workouts"][0]["steps"] = [
        {"warmup": "5m"},
        {
            "repeat": {
                "count": 4,
                "steps": [
                    {"run": {"time": "2m", "pace": "4:30-4:45 min/km"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "5m"},
    ]

    workout = load_program_model(raw).week(1).workouts[0]

    assert infer_workout_form(workout) is INTERVAL_WORKOUT
