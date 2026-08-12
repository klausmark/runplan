"""Workout recipe domain contract.

Step 3 introduces :class:`WorkoutRecipe` as a schedule-independent domain
value with typed parameters and an instantiation function. The tests
cover the contract, parameter validation, the form labelling, the
catalogue wiring, and the schedule-free guarantee.
"""

from __future__ import annotations

import pytest

from runplan import (
    RECIPE_CATALOG,
    WORKOUT_SCHEDULE_SENTINEL,
    Step,
    Workout,
    WorkoutWithForm,
    get_recipe,
    recipes_by_form,
)
from runplan.domain.errors import WorkoutDefinitionError
from runplan.domain.recipes import (
    ContinuousTempoParameters,
    CruiseIntervalsParameters,
    EasyContinuousParameters,
    EasyWithStridesParameters,
    FartlekParameters,
    HillRepeatsParameters,
    LongSteadyParameters,
    LongWithFinishParameters,
    LongWithHillSurgesParameters,
    LongWithKickoutsParameters,
    RecoveryRunParameters,
    RunWalkIntervalsParameters,
    Track1kParameters,
    Track400mParameters,
    WarmupRunParameters,
)
from runplan.domain.recipes.base import (
    RecipeInstantiationError,
    WorkoutRecipe,
)
from runplan.domain.workout_form import (
    EASY_RUN,
    FORM_BY_NAME,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    RUN_WALK,
    TEMPO_RUN,
)

# ---------------------------------------------------------------------------
# Contract — construction
# ---------------------------------------------------------------------------


def test_recipe_rejects_empty_key() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        WorkoutRecipe(
            key="",
            form=EASY_RUN,
            label="label",
            description="description",
            parameters_type=EasyContinuousParameters,
            build_steps=lambda _params: (),
        )


def test_recipe_rejects_empty_label() -> None:
    with pytest.raises(ValueError, match="non-empty string"):
        WorkoutRecipe(
            key="easy.continuous",
            form=EASY_RUN,
            label="",
            description="description",
            parameters_type=EasyContinuousParameters,
            build_steps=lambda _params: (),
        )


def test_recipe_rejects_unknown_form_constant() -> None:
    class FakeForm:
        name = "imaginary"
        label = "Imaginary"

    with pytest.raises(ValueError, match="unknown workout form"):
        WorkoutRecipe(
            key="imaginary.run",
            form=FakeForm(),  # type: ignore[arg-type]
            label="Imaginary",
            description="description",
            parameters_type=EasyContinuousParameters,
            build_steps=lambda _params: (),
        )


def test_recipe_rejects_parameters_type_outside_hierarchy() -> None:
    class NotParameters:
        pass

    with pytest.raises(ValueError, match="RecipeParameters subclass"):
        WorkoutRecipe(
            key="easy.continuous",
            form=EASY_RUN,
            label="Easy",
            description="description",
            parameters_type=NotParameters,  # type: ignore[arg-type]
            build_steps=lambda _params: (),
        )


def test_recipe_rejects_non_callable_build_steps() -> None:
    with pytest.raises(ValueError, match="build_steps must be callable"):
        WorkoutRecipe(
            key="easy.continuous",
            form=EASY_RUN,
            label="Easy",
            description="description",
            parameters_type=EasyContinuousParameters,
            build_steps="not-callable",  # type: ignore[arg-type]
        )


def test_recipe_catalog_keys_are_unique() -> None:
    keys = [recipe.key for recipe in RECIPE_CATALOG]
    assert len(keys) == len(set(keys))


def test_recipe_catalog_covers_six_forms() -> None:
    grouped = recipes_by_form()
    assert set(grouped) == set(FORM_BY_NAME)
    for form_name in grouped:
        assert grouped[form_name], f"no recipes for form {form_name}"


def test_recipe_catalog_keys_are_stable_strings() -> None:
    for recipe in RECIPE_CATALOG:
        assert isinstance(recipe.key, str) and recipe.key
        assert "." in recipe.key, f"recipe key {recipe.key!r} should be dotted"


def test_recipe_catalog_recipes_are_immutable() -> None:
    recipe = RECIPE_CATALOG[0]
    with pytest.raises((AttributeError, TypeError)):
        recipe.key = "something.else"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Contract — instantiation
# ---------------------------------------------------------------------------


def test_recipe_instantiate_returns_workout_with_form() -> None:
    recipe = get_recipe("easy.continuous")

    pair = recipe.instantiate(EasyContinuousParameters(minutes=30))

    assert isinstance(pair, WorkoutWithForm)
    assert pair.workout.name == "Easy continuous run"
    assert pair.workout.description is not None
    assert pair.form is EASY_RUN


def test_recipe_instantiate_leaves_schedule_and_garmin_fields_at_defaults() -> None:
    recipe = get_recipe("long.steady")

    pair = recipe.instantiate(LongSteadyParameters(target_km=12.0))

    workout = pair.workout
    assert workout.id == ""
    assert workout.day == 0
    assert workout.schedule_date == WORKOUT_SCHEDULE_SENTINEL
    assert workout.status == "planned"
    assert workout.garmin_workout_id is None
    assert workout.garmin_schedule_id is None
    assert workout.activity_id is None
    assert workout.completed_at is None
    assert workout.actual_distance_meters is None
    assert workout.actual_duration_seconds is None


def test_recipe_instantiate_is_idempotent() -> None:
    recipe = get_recipe("easy.continuous")

    first = recipe.instantiate(EasyContinuousParameters(minutes=30))
    second = recipe.instantiate(EasyContinuousParameters(minutes=30))

    assert first == second
    assert first.workout.steps == second.workout.steps
    assert first.form is second.form


def test_recipe_instantiate_rejects_wrong_parameter_type() -> None:
    recipe = get_recipe("easy.continuous")

    with pytest.raises(RecipeInstantiationError, match="EasyContinuousParameters"):
        recipe.instantiate(RunWalkIntervalsParameters())  # type: ignore[arg-type]


def test_recipe_instantiate_rejects_non_recipe_parameters_instance() -> None:
    recipe = get_recipe("easy.continuous")

    class Foreign:
        pass

    with pytest.raises(RecipeInstantiationError, match="EasyContinuousParameters"):
        recipe.instantiate(Foreign())  # type: ignore[arg-type]


def test_recipe_instantiate_rejects_non_step_in_build_output() -> None:
    recipe = WorkoutRecipe(
        key="easy.continuous",
        form=EASY_RUN,
        label="Easy",
        description="description",
        parameters_type=EasyContinuousParameters,
        build_steps=lambda _params: (
            Step(action="run", end_kind="time", end_value=60.0),
            "not-a-step",
        ),
    )

    with pytest.raises(RecipeInstantiationError, match="steps\\[2\\]"):
        recipe.instantiate(EasyContinuousParameters())


def test_recipe_instantiate_uses_build_name_and_description_when_provided() -> None:
    recipe = WorkoutRecipe(
        key="easy.continuous",
        form=EASY_RUN,
        label="Easy",
        description="Default description",
        parameters_type=EasyContinuousParameters,
        build_steps=lambda _params: (),
        build_name=lambda params: f"Easy {params.minutes} minutes",
        build_description=lambda params: f"Custom description for {params.minutes} minutes",
    )

    pair = recipe.instantiate(EasyContinuousParameters(minutes=45))

    assert pair.workout.name == "Easy 45 minutes"
    assert pair.workout.description == "Custom description for 45 minutes"


def test_recipe_instantiate_inherits_label_and_description_by_default() -> None:
    recipe = get_recipe("easy.continuous")

    pair = recipe.instantiate(EasyContinuousParameters(minutes=30))

    assert pair.workout.name == "Easy continuous run"
    assert pair.workout.description is not None


def test_recipe_instantiate_error_is_a_workout_definition_error() -> None:
    assert issubclass(RecipeInstantiationError, WorkoutDefinitionError)


def test_recipe_form_is_declared_on_recipe() -> None:
    paired = {
        "easy.continuous": EASY_RUN,
        "easy.with_strides": EASY_RUN,
        "recovery.run": RECOVERY_RUN,
        "run_walk.intervals": RUN_WALK,
        "easy.warmup_run": EASY_RUN,
        "long.steady": LONG_RUN,
        "long.with_finish": LONG_RUN,
        "long.with_hill_surges": LONG_RUN,
        "long.with_kickouts": LONG_RUN,
        "tempo.continuous": TEMPO_RUN,
        "tempo.cruise_intervals": TEMPO_RUN,
        "interval.track_400m": INTERVAL_WORKOUT,
        "interval.track_1k": INTERVAL_WORKOUT,
        "interval.hill_repeats": INTERVAL_WORKOUT,
        "interval.fartlek": INTERVAL_WORKOUT,
    }
    for key, expected_form in paired.items():
        recipe = get_recipe(key)
        assert recipe.form is expected_form, (
            f"recipe {key!r} should declare form {expected_form.label!r}"
        )


def test_long_run_recipes_carry_long_run_form_even_when_step_shape_mimics_easy() -> None:
    """Long-run recipes must declare LONG_RUN explicitly. The step shape
    alone is not enough to classify a long run as such."""
    for key in ("long.steady", "long.with_finish", "long.with_hill_surges", "long.with_kickouts"):
        recipe = get_recipe(key)
        assert recipe.form is LONG_RUN


def test_schedule_fields_visible_in_recipe_instantiation_summary() -> None:
    exercise = get_recipe("interval.track_400m").instantiate(
        Track400mParameters(reps=5, pace=("4:30", "4:30"))
    )

    summary = {
        "id": exercise.workout.id,
        "day": exercise.workout.day,
        "schedule_date": exercise.workout.schedule_date,
        "status": exercise.workout.status,
        "garmin_workout_id": exercise.workout.garmin_workout_id,
        "garmin_schedule_id": exercise.workout.garmin_schedule_id,
        "activity_id": exercise.workout.activity_id,
    }
    assert summary == {
        "id": "",
        "day": 0,
        "schedule_date": WORKOUT_SCHEDULE_SENTINEL,
        "status": "planned",
        "garmin_workout_id": None,
        "garmin_schedule_id": None,
        "activity_id": None,
    }


# ---------------------------------------------------------------------------
# Parameter validation — defaults and rejected values
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("factory", "match"),
    [
        (lambda: EasyContinuousParameters(minutes=0), "minutes must be greater than 0"),
        (lambda: EasyContinuousParameters(minutes=-1), "minutes must be greater than 0"),
        (lambda: EasyWithStridesParameters(minutes=0), "minutes must be greater than 0"),
        (lambda: RecoveryRunParameters(minutes=0), "minutes must be greater than 0"),
        (lambda: WarmupRunParameters(minutes=0), "minutes must be greater than 0"),
        (lambda: RunWalkIntervalsParameters(run_minutes=0), "run_minutes must be greater than 0"),
        (lambda: RunWalkIntervalsParameters(walk_minutes=0), "walk_minutes must be greater than 0"),
        (lambda: RunWalkIntervalsParameters(cycles=0), "cycles must be greater than 0"),
        (lambda: LongSteadyParameters(target_km=0), "target_km must be greater than 0"),
        (lambda: LongWithFinishParameters(target_km=0), "target_km must be greater than 0"),
        (lambda: LongWithHillSurgesParameters(target_km=0), "target_km must be greater than 0"),
        (lambda: LongWithHillSurgesParameters(surge_count=0), "surge_count must be greater than 0"),
        (lambda: LongWithKickoutsParameters(target_km=0), "target_km must be greater than 0"),
        (lambda: LongWithKickoutsParameters(kick_count=0), "kick_count must be greater than 0"),
        (lambda: LongWithKickoutsParameters(kick_minutes=0), "kick_minutes must be greater than 0"),
        (lambda: ContinuousTempoParameters(minutes=0), "minutes must be greater than 0"),
        (lambda: ContinuousTempoParameters(pace=("4:30",)), "pace must be a pair"),
        (lambda: CruiseIntervalsParameters(reps=0), "reps must be greater than 0"),
        (lambda: CruiseIntervalsParameters(rep_minutes=0), "rep_minutes must be greater than 0"),
        (lambda: Track400mParameters(reps=0), "reps must be greater than 0"),
        (lambda: Track1kParameters(reps=0), "reps must be greater than 0"),
        (lambda: HillRepeatsParameters(reps=0), "reps must be greater than 0"),
        (lambda: HillRepeatsParameters(effort_seconds=0), "effort_seconds must be greater than 0"),
        (lambda: FartlekParameters(cycles=0), "cycles must be greater than 0"),
        (lambda: FartlekParameters(hard_minutes=0), "hard_minutes must be greater than 0"),
        (lambda: FartlekParameters(easy_minutes=0), "easy_minutes must be greater than 0"),
    ],
)
def test_recipe_parameters_reject_invalid_values(
    factory: callable,
    match: str,  # type: ignore[type-arg]
) -> None:
    with pytest.raises(ValueError, match=match):
        factory()


def test_recipe_parameters_default_minutes_is_positive() -> None:
    params = EasyContinuousParameters()
    assert params.minutes == 30


# ---------------------------------------------------------------------------
# Per-recipe instantiation — concrete parity with the existing builders
# ---------------------------------------------------------------------------


def test_easy_continuous_recipe_matches_builder() -> None:
    pair = get_recipe("easy.continuous").instantiate(EasyContinuousParameters(minutes=45))

    actions = tuple(step.action for step in pair.workout.steps)
    assert actions == ("warmup", "run", "cooldown")
    durations = tuple(step.end_value for step in pair.workout.steps)
    assert durations == (300.0, 2700.0, 300.0)


def test_easy_with_strides_recipe_includes_repeat_block() -> None:
    pair = get_recipe("easy.with_strides").instantiate(EasyWithStridesParameters(minutes=30))

    actions = tuple(step.action for step in pair.workout.steps)
    assert actions == ("warmup", "run", "repeat", "cooldown")
    repeat = pair.workout.steps[2]
    assert repeat.count == 4
    assert tuple(child.action for child in repeat.steps) == ("run", "recovery")


def test_recovery_run_recipe_is_single_step() -> None:
    pair = get_recipe("recovery.run").instantiate(RecoveryRunParameters(minutes=20))

    assert len(pair.workout.steps) == 1
    assert pair.workout.steps[0].action == "run"
    assert pair.workout.steps[0].end_value == 20 * 60


def test_run_walk_recipe_alternates_run_and_walk() -> None:
    pair = get_recipe("run_walk.intervals").instantiate(
        RunWalkIntervalsParameters(run_minutes=1, walk_minutes=2, cycles=4)
    )

    actions = tuple(step.action for step in pair.workout.steps)
    assert actions == ("warmup", "repeat", "cooldown")
    repeat = pair.workout.steps[1]
    assert repeat.count == 4
    assert tuple(child.action for child in repeat.steps) == ("run", "walk")


def test_long_steady_recipe_carries_distance() -> None:
    pair = get_recipe("long.steady").instantiate(LongSteadyParameters(target_km=12.0))

    actions = tuple(step.action for step in pair.workout.steps)
    assert actions == ("warmup", "run", "cooldown")
    run = pair.workout.steps[1]
    assert run.end_kind == "distance"
    assert run.end_value == 12_000.0


def test_long_with_finish_recipe_splits_distance() -> None:
    pair = get_recipe("long.with_finish").instantiate(LongWithFinishParameters(target_km=12.0))

    run_steps = tuple(step for step in pair.workout.steps if step.action == "run")
    assert len(run_steps) == 2
    assert run_steps[0].end_value is not None
    assert run_steps[1].end_value is not None
    assert run_steps[0].end_value + run_steps[1].end_value == pytest.approx(12_000.0)


def test_long_with_hill_surges_recipe_repeats_runs() -> None:
    pair = get_recipe("long.with_hill_surges").instantiate(
        LongWithHillSurgesParameters(target_km=10.0, surge_count=6)
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    assert repeat.count == 6
    assert tuple(child.action for child in repeat.steps) == ("run", "recovery")


def test_long_with_kickouts_recipe_repeats_runs() -> None:
    pair = get_recipe("long.with_kickouts").instantiate(
        LongWithKickoutsParameters(target_km=10.0, kick_count=4, kick_minutes=2)
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    assert repeat.count == 4
    assert tuple(child.action for child in repeat.steps) == ("run", "recovery")


def test_continuous_tempo_recipe_carries_pace() -> None:
    pair = get_recipe("tempo.continuous").instantiate(
        ContinuousTempoParameters(minutes=20, pace=("4:30", "4:45"))
    )

    run = next(step for step in pair.workout.steps if step.action == "run")
    assert run.pace == (270.0, 285.0)


def test_cruise_intervals_recipe_repeats_with_pace() -> None:
    pair = get_recipe("tempo.cruise_intervals").instantiate(
        CruiseIntervalsParameters(reps=4, rep_minutes=5, pace=("4:30", "4:45"))
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    assert repeat.count == 4
    run = repeat.steps[0]
    assert run.pace == (270.0, 285.0)


def test_track_400m_recipe_uses_400m_distance() -> None:
    pair = get_recipe("interval.track_400m").instantiate(
        Track400mParameters(reps=6, pace=("4:00", "4:00"))
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    run = repeat.steps[0]
    assert run.end_kind == "distance"
    assert run.end_value == 400.0


def test_track_1k_recipe_uses_1km_distance() -> None:
    pair = get_recipe("interval.track_1k").instantiate(
        Track1kParameters(reps=5, pace=("4:30", "4:30"))
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    run = repeat.steps[0]
    assert run.end_kind == "distance"
    assert run.end_value == 1000.0


def test_hill_repeats_recipe_repeats_with_effort_seconds() -> None:
    pair = get_recipe("interval.hill_repeats").instantiate(
        HillRepeatsParameters(reps=6, effort_seconds=60)
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    assert repeat.count == 6
    run = repeat.steps[0]
    assert run.end_value == 60.0


def test_fartlek_recipe_alternates_hard_and_easy() -> None:
    pair = get_recipe("interval.fartlek").instantiate(
        FartlekParameters(cycles=5, hard_minutes=2, easy_minutes=1)
    )

    repeat = next(step for step in pair.workout.steps if step.action == "repeat")
    assert repeat.count == 5
    durs = tuple(child.end_value for child in repeat.steps)
    assert durs == (120.0, 60.0)


# ---------------------------------------------------------------------------
# Workouts round-trippable through the typed loader
# ---------------------------------------------------------------------------


def test_recipe_instantiation_survives_typed_load() -> None:
    from runplan import load_program_model

    pair = get_recipe("interval.track_400m").instantiate(
        Track400mParameters(reps=5, pace=("4:30", "4:45"))
    )
    mini_program = {
        "program": {
            "id": "tmp",
            "name": "tmp",
            "short_name": "TMP",
            "start_week": "2026-W01",
        },
        "weeks": [
            {
                "week": 1,
                "workouts": [
                    {
                        "id": "s1",
                        "day": 1,
                        "name": pair.workout.name,
                        "description": pair.workout.description,
                        "steps": [
                            {
                                "warmup": "5m",
                            },
                            {
                                "repeat": {
                                    "count": 5,
                                    "steps": [
                                        {"run": {"distance": "400m", "pace": "4:30-4:45 min/km"}},
                                        {"recovery": {"time": "90s"}},
                                    ],
                                }
                            },
                            {"cooldown": "5m"},
                        ],
                    }
                ],
            }
        ],
    }
    model = load_program_model(mini_program)
    assert model.week(1).workouts[0].steps[1].count == 5


def test_recipe_step_outputs_are_step_instances() -> None:
    for recipe in RECIPE_CATALOG:
        params = recipe.parameters_type()
        pair = recipe.instantiate(params)
        for index, step in enumerate(pair.workout.steps, start=1):
            assert isinstance(step, Step), (
                f"{recipe.key} produced {type(step).__name__} at step {index}"
            )


# ---------------------------------------------------------------------------
# Catalogue access helpers
# ---------------------------------------------------------------------------


def test_get_recipe_finds_known_key() -> None:
    recipe = get_recipe("long.steady")
    assert recipe.key == "long.steady"


def test_get_recipe_raises_for_unknown_key() -> None:
    with pytest.raises(KeyError, match="unknown recipe key"):
        get_recipe("not.a.recipe")


def test_recipes_by_form_groups_by_canonical_form() -> None:
    grouped = recipes_by_form()
    for form_name, recipes in grouped.items():
        for recipe in recipes:
            assert recipe.form.name == form_name


def test_recipes_by_form_returns_tuple_values() -> None:
    grouped = recipes_by_form()
    for value in grouped.values():
        assert isinstance(value, tuple)


def test_schedule_aware_workout_starts_empty() -> None:
    """A schedule-aware ``Workout`` constructed without ids keeps the
    schedule-free defaults. Step 6 relies on this when assigning ids."""
    workout = Workout()
    assert workout.id == ""
    assert workout.day == 0
    assert workout.schedule_date == WORKOUT_SCHEDULE_SENTINEL
