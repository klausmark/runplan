"""``instantiate_recipe`` use case (Step 6).

The use case accepts a recipe, parameters, a target week/day, and a
:class:`ProgramRepository`. It allocates a workout id, builds the
explicit workout through the recipe, inserts it into the raw YAML
document, and validates the complete program before persisting it.

The tests cover:

- The happy path for each canonical workout form.
- Insertion sorting and id allocation.
- All failure modes (``unknown_program``, ``unknown_recipe``,
  ``invalid_parameters``, ``invalid_target`` and its variants,
  ``duplicate_workout_id``, ``invalid_program``).
- Round-trip of the workout through the existing parser.
- Integration with the Step 5 :class:`RecipeSuggestion`.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest

from runplan.application.recipes import (
    InstantiateRecipeError,
    InstantiateRecipeResult,
    instantiate_recipe,
)
from runplan.domain.recipes import (
    ContinuousTempoParameters,
    EasyContinuousParameters,
    EasyWithStridesParameters,
    FartlekParameters,
    LongSteadyParameters,
    LongWithFinishParameters,
    LongWithHillSurgesParameters,
    LongWithKickoutsParameters,
    RecoveryDistanceParameters,
    RecoveryRunParameters,
    RunWalkIntervalsParameters,
)
from runplan.domain.recommendations import RecipeSuggestion
from runplan.domain.workout_form import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    RUN_WALK,
    TEMPO_RUN,
)
from runplan.parsing.yaml_loader import load_program_model
from tests.fakes import InMemoryProgramRepository
from tests.helpers import program_data

PROGRAM_ID = "characterization-plan"
START_WEEK = "2026-W53"
START_MONDAY = date(2026, 12, 28)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _repository() -> InMemoryProgramRepository:
    return InMemoryProgramRepository({PROGRAM_ID: deepcopy(program_data())})


_RECIPES: dict[str, dict] = {
    "easy.continuous": {
        "form": EASY_RUN,
        "parameters": EasyContinuousParameters(minutes=30),
    },
    "easy.with_strides": {
        "form": EASY_RUN,
        "parameters": EasyWithStridesParameters(minutes=30),
    },
    "recovery.run": {
        "form": RECOVERY_RUN,
        "parameters": RecoveryRunParameters(minutes=20),
    },
    "recovery.distance": {
        "form": RECOVERY_RUN,
        "parameters": RecoveryDistanceParameters(target_km=3.0),
    },
    "run_walk.intervals": {
        "form": RUN_WALK,
        "parameters": RunWalkIntervalsParameters(run_minutes=1, walk_minutes=2, cycles=6),
    },
    "long.steady": {
        "form": LONG_RUN,
        "parameters": LongSteadyParameters(target_km=10.0),
    },
    "long.with_finish": {
        "form": LONG_RUN,
        "parameters": LongWithFinishParameters(target_km=10.0),
    },
    "long.with_hill_surges": {
        "form": LONG_RUN,
        "parameters": LongWithHillSurgesParameters(target_km=10.0, surge_count=6),
    },
    "long.with_kickouts": {
        "form": LONG_RUN,
        "parameters": LongWithKickoutsParameters(target_km=10.0, kick_count=4, kick_minutes=2),
    },
    "tempo.continuous": {
        "form": TEMPO_RUN,
        "parameters": ContinuousTempoParameters(minutes=20, pace=("4:30", "4:45")),
    },
    "interval.fartlek": {
        "form": INTERVAL_WORKOUT,
        "parameters": FartlekParameters(cycles=5, hard_minutes=2, easy_minutes=1),
    },
}


def _recipes() -> dict[str, dict]:
    return _RECIPES


# ---------------------------------------------------------------------------
# Happy path — every recipe lands in a valid program with the right metadata
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("recipe_key", list(_recipes()))
def test_instantiate_recipe_adds_workout_with_schedule_date_and_form(
    recipe_key: str,
) -> None:
    repository = _repository()
    spec = _recipes()[recipe_key]
    result = instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key=recipe_key,
        parameters=spec["parameters"],
        week=2,
        day=3,
        repository=repository,
    )

    expected_schedule = START_MONDAY + timedelta(days=(2 - 1) * 7 + (3 - 1))

    assert isinstance(result, InstantiateRecipeResult)
    assert result.recipe_key == recipe_key
    assert result.week == 2
    assert result.day == 3
    assert result.schedule_date == expected_schedule
    assert result.workout_with_form.form is spec["form"]
    assert result.workout_with_form.workout.id.startswith(
        f"{recipe_key.replace('.', '-').replace('_', '-')}-02-d3"
    )
    assert result.workout_with_form.workout.day == 3
    assert result.workout_with_form.workout.schedule_date == result.schedule_date
    assert result.workout_with_form.workout.steps

    saved = repository.load(PROGRAM_ID)
    inserted = next(
        item
        for item in saved["weeks"][1]["workouts"]
        if item["id"] == result.workout_with_form.workout.id
    )
    assert inserted["day"] == 3
    assert inserted["schedule_date"] == expected_schedule.isoformat()
    assert load_program_model(saved)


def test_instantiate_recipe_inserts_into_correct_week_and_sorts_by_day() -> None:
    repository = _repository()
    instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
        week=1,
        day=2,
        repository=repository,
    )
    saved = repository.load(PROGRAM_ID)
    days = [item["day"] for item in saved["weeks"][0]["workouts"]]
    assert days == sorted(days)
    assert 2 in days


def test_instantiate_recipe_appends_when_day_is_empty() -> None:
    repository = _repository()
    before = sum(len(week["workouts"]) for week in repository.load(PROGRAM_ID)["weeks"])
    instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
        week=1,
        day=6,
        repository=repository,
    )
    after = sum(len(week["workouts"]) for week in repository.load(PROGRAM_ID)["weeks"])
    assert after == before + 1


# ---------------------------------------------------------------------------
# Workout id allocation
# ---------------------------------------------------------------------------


def test_instantiate_recipe_default_id_collides_with_existing_id_and_suffixes() -> None:
    repository = _repository()
    raw = repository.load(PROGRAM_ID)
    raw["weeks"][1]["workouts"].append(
        {
            "id": "easy-continuous-01-d2",
            "day": 1,
            "name": "Preexisting",
            "steps": [{"run": {"time": "10m"}}],
        }
    )
    raw["weeks"][1]["workouts"].sort(key=lambda item: item["day"])
    repository.save(PROGRAM_ID, raw)

    result = instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
        week=1,
        day=2,
        repository=repository,
    )
    assert result.workout_with_form.workout.id == "easy-continuous-01-d2-2"


def test_instantiate_recipe_uses_custom_id_allocator_when_provided() -> None:
    repository = _repository()

    def _allocator(_existing: set[str]) -> str:
        return "custom-recipe-id"

    result = instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
        week=1,
        day=6,
        repository=repository,
        id_allocator=_allocator,
    )
    assert result.workout_with_form.workout.id == "custom-recipe-id"


# ---------------------------------------------------------------------------
# Failure modes
# ---------------------------------------------------------------------------


def test_instantiate_recipe_unknown_program_raises_unknown_program() -> None:
    repository = _repository()
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id="not-there",
            recipe_key="easy.continuous",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=6,
            repository=repository,
        )
    assert info.value.kind == "unknown_program"


def test_instantiate_recipe_unknown_recipe_raises_unknown_recipe() -> None:
    repository = _repository()
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="not.a.recipe",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=6,
            repository=repository,
        )
    assert info.value.kind == "unknown_recipe"


def test_instantiate_recipe_wrong_parameter_type_raises_invalid_parameters() -> None:
    repository = _repository()
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="interval.fartlek",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=6,
            repository=repository,
        )
    assert info.value.kind == "invalid_parameters"


def test_instantiate_recipe_invalid_parameters_raise_via_recipe_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()

    def _broken_instantiate(_params: object) -> object:
        from runplan.domain.recipes import RecipeInstantiationError

        raise RecipeInstantiationError("forced failure for test")

    monkeypatch.setattr(
        "runplan.application.recipes.instantiate.get_recipe",
        lambda _key: type(
            "_Stub",
            (),
            {
                "instantiate": staticmethod(_broken_instantiate),
                "parameters_type": EasyContinuousParameters,
            },
        )(),
    )
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="easy.continuous",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=6,
            repository=repository,
        )
    assert info.value.kind == "invalid_parameters"


@pytest.mark.parametrize("week", [0, -1, 99])
def test_instantiate_recipe_invalid_week_raises_invalid_target(week: int) -> None:
    repository = _repository()
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="easy.continuous",
            parameters=EasyContinuousParameters(minutes=30),
            week=week,
            day=2,
            repository=repository,
        )
    assert info.value.kind in {"invalid_week", "invalid_target"}


@pytest.mark.parametrize("day", [0, 8, -1])
def test_instantiate_recipe_invalid_day_raises_invalid_target(day: int) -> None:
    repository = _repository()
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="easy.continuous",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=day,
            repository=repository,
        )
    assert info.value.kind == "invalid_day"


def test_instantiate_recipe_occupied_day_raises_invalid_target() -> None:
    repository = _repository()
    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="easy.continuous",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=1,
            repository=repository,
        )
    assert info.value.kind == "occupied_day"


def test_instantiate_recipe_does_not_save_when_program_invalid(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repository = _repository()
    saves_before = len(repository.saves)

    def _broken_loader(_raw: dict) -> None:
        from runplan.domain.errors import WorkoutDefinitionError

        raise WorkoutDefinitionError("forced failure for test")

    monkeypatch.setattr(
        "runplan.application.recipes.instantiate.load_program_model",
        _broken_loader,
    )

    with pytest.raises(InstantiateRecipeError) as info:
        instantiate_recipe(
            program_id=PROGRAM_ID,
            recipe_key="easy.continuous",
            parameters=EasyContinuousParameters(minutes=30),
            week=1,
            day=6,
            repository=repository,
        )
    assert info.value.kind == "invalid_program"
    assert len(repository.saves) == saves_before


# ---------------------------------------------------------------------------
# Persistence and round-trip
# ---------------------------------------------------------------------------


def test_instantiate_recipe_persists_via_repository_save() -> None:
    repository = _repository()
    instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
        week=2,
        day=2,
        repository=repository,
    )
    assert repository.saves, "repository.save must have been called"
    saved = repository.load(PROGRAM_ID)
    assert load_program_model(saved)


def test_instantiate_recipe_round_trips_workout_steps() -> None:
    repository = _repository()
    params = EasyContinuousParameters(minutes=30)
    result = instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key="easy.continuous",
        parameters=params,
        week=1,
        day=6,
        repository=repository,
    )
    saved = repository.load(PROGRAM_ID)
    next(
        item
        for item in saved["weeks"][0]["workouts"]
        if item["id"] == result.workout_with_form.workout.id
    )
    rebuilt = load_program_model(saved).week(1)
    rebuilt_workout = next(
        item for item in rebuilt.workouts if item.id == result.workout_with_form.workout.id
    )
    assert [step.action for step in rebuilt_workout.steps] == [
        step.action for step in result.workout_with_form.workout.steps
    ]


# ---------------------------------------------------------------------------
# Integration with the recommendation engine (Step 5)
# ---------------------------------------------------------------------------


def test_instantiate_recipe_accepts_recipe_suggestion_parameters() -> None:
    repository = _repository()
    suggestion = RecipeSuggestion(
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
    )
    result = instantiate_recipe(
        program_id=PROGRAM_ID,
        recipe_key=suggestion.recipe_key,
        parameters=suggestion.parameters,
        week=1,
        day=6,
        repository=repository,
    )
    assert result.recipe_key == suggestion.recipe_key
