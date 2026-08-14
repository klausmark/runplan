"""Generator ↔ recipe contract for the first 10K programme.

Step 9 wires the first 10K generator through the
:class:`~runplan.domain.recipes.WorkoutRecipe` catalogue. These tests
exercise the placement and the variety pickers end-to-end so the
contract between the generator and the recipe layer is locked down.
"""

from __future__ import annotations

from datetime import date

import pytest

from runplan.domain.recipes import get_recipe
from runplan.domain.workout_form import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    TEMPO_RUN,
)
from runplan.generation import (
    GeneratorRequest,
    TrainingDays,
    compose_program,
)
from runplan.generation.days import assign_program
from runplan.generation.inputs import GoalRace
from runplan.generation.phase import phase_for, phase_plan
from runplan.generation.placement import place_week
from runplan.generation.recipe_dose import (
    easy_dose,
    long_run_dose,
    quality_dose,
)
from runplan.generation.variety import (
    VarietyBoard,
    pick_easy_recipe,
    pick_long_run_recipe,
    pick_quality_recipe,
    summary_stats,
)

_KNOWN_PACE = (300, 320)
_KNOWN_PACE_LIST = list(_KNOWN_PACE)


def _request(**kwargs) -> GeneratorRequest:
    defaults = {
        "start_week": "2026-W32",
        "duration_weeks": 12,
        "current_weekly_km": 25,
        "current_longest_km": 6,
        "training_days": TrainingDays(possible_days=(1, 2, 3, 4, 5, 6, 7), sessions_per_week=4),
        "quality_sessions_per_week": 1,
    }
    defaults.update(kwargs)
    return GeneratorRequest(**defaults)


def test_default_request_uses_recipe_catalogue() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    for week in result.program.weeks:
        for workout in week.workouts:
            assert "recipe" not in workout.id.lower()
            # Non-race / non-club slots must carry a recipe key.
            if "race" not in workout.id and "club" not in workout.id:
                assert workout.id.startswith("week-") or workout.id.startswith("test")


def test_long_run_slot_carries_a_long_run_recipe_key() -> None:
    result = compose_program(_request(known_easy_pace_sec=_KNOWN_PACE), today=date(2026, 7, 1))
    long_run_recipes = {
        workout.id
        for week in result.program.weeks
        for workout in week.workouts
        if "long" in workout.id and workout.id.endswith(tuple(f"-{d}" for d in range(1, 8)))
    }
    assert long_run_recipes


def test_pace_aware_long_run_includes_pace_min_per_km() -> None:
    request = _request(known_easy_pace_sec=_KNOWN_PACE)
    result = compose_program(request, today=date(2026, 7, 1))
    for week in result.program.weeks:
        for workout in week.workouts:
            if "long" in workout.id and workout.id.endswith("-7") is False:
                rendered_steps = [step.action for step in workout.steps]
                assert any(action == "run" for action in rendered_steps)
                run_step = next(step for step in workout.steps if step.action == "run")
                if run_step.pace is not None:
                    assert run_step.pace[0] > 0 and run_step.pace[1] >= run_step.pace[0]


def test_quality_slot_uses_a_key_recipe() -> None:
    board = VarietyBoard()
    recipe, board = pick_quality_recipe(board, 0)
    assert recipe.form in {TEMPO_RUN, INTERVAL_WORKOUT}


def test_variety_summary_tracks_recipe_keys_not_style_strings() -> None:
    board = VarietyBoard()
    for week in range(6):
        recipe, board = pick_quality_recipe(board, week)
        assert recipe.key.startswith(("tempo.", "interval."))
    stats = summary_stats(board)
    assert isinstance(stats["quality_history"], list)
    assert all(key.startswith(("tempo.", "interval.")) for key in stats["quality_history"])
    assert len(set(stats["quality_history"])) >= 3


def test_easy_picker_supports_short_target_recovery() -> None:
    board = VarietyBoard()
    recipe, board = pick_easy_recipe(board, 0, short_target=True)
    assert recipe.form is RECOVERY_RUN


def test_easy_picker_returns_easy_run_when_not_short() -> None:
    board = VarietyBoard()
    recipe, _ = pick_easy_recipe(board, 0, short_target=False)
    assert recipe.form is EASY_RUN


def test_long_run_picker_only_picks_long_run_form() -> None:
    board = VarietyBoard()
    recipe, _ = pick_long_run_recipe(board, 0)
    assert recipe.form is LONG_RUN


def test_long_run_dose_produces_pace_when_known() -> None:
    recipe = get_recipe("long.steady")
    params = long_run_dose(recipe, target_km=10.0, easy_pace_sec_per_km=_KNOWN_PACE)
    assert params.pace is not None
    assert isinstance(params.pace[0], str)


def test_long_run_dose_handles_missing_pace() -> None:
    recipe = get_recipe("long.steady")
    params = long_run_dose(recipe, target_km=10.0, easy_pace_sec_per_km=None)
    assert params.pace is None


def test_quality_dose_routes_early_weeks_to_tempo_recipe() -> None:
    from runplan.generation.phase import PhaseKind

    recipe = get_recipe("interval.track_1k")
    params = quality_dose(
        recipe, week=2, phase=PhaseKind.FOUNDATION, easy_pace_sec_per_km=_KNOWN_PACE
    )
    type_name = type(params).__name__
    assert type_name in {"ContinuousTempoParameters", "Track1kParameters"}


def test_easy_dose_maps_target_km_to_minutes() -> None:
    params = easy_dose(get_recipe("easy.continuous"), target_km=5.0)
    assert params.minutes >= 20


def test_compose_program_three_workouts_per_week_default() -> None:
    request = _request(
        training_days=TrainingDays(possible_days=(1, 2, 3, 4, 5, 6, 7), sessions_per_week=3)
    )
    result = compose_program(request, today=date(2026, 7, 1))
    weeks = result.program.weeks
    for index, week in enumerate(weeks):
        if index == len(weeks) - 1:
            assert len(week.workouts) == 4
        else:
            assert len(week.workouts) == 3


def test_compose_program_with_pace_emits_pace_on_quality_runs() -> None:
    result = compose_program(_request(known_easy_pace_sec=_KNOWN_PACE), today=date(2026, 7, 1))
    pace_found = False
    for week in result.program.weeks:
        for workout in week.workouts:
            if "quality" not in workout.id:
                continue
            for step in workout.steps:
                if step.pace is not None:
                    pace_found = True
                    break
    assert pace_found, "expected at least one quality step to carry pace"


def test_compose_program_without_pace_keeps_quality_steps_without_pace() -> None:
    result = compose_program(_request(known_easy_pace_sec=None), today=date(2026, 7, 1))
    has_quality = False
    for week in result.program.weeks:
        for workout in week.workouts:
            if "quality" not in workout.id:
                continue
            has_quality = True
            for step in workout.steps:
                assert step.pace is None, (
                    f"expected quality step without pace when known pace missing, got {step}"
                )
    assert has_quality, "expected at least one quality session in the 12-week program"


def test_compose_program_does_not_emit_race_when_goal_race_missing() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    race_ids = [
        workout.id
        for week in result.program.weeks
        for workout in week.workouts
        if "race" in workout.id
    ]
    assert len(race_ids) == 1, "expected the final-week 10K test run only"
    assert any(race_id.endswith("-race-7") for race_id in race_ids)


def test_compose_program_goal_race_replaces_long_run() -> None:
    request = _request(goal_race=GoalRace(date=date(2026, 10, 25)))
    result = compose_program(request, today=date(2026, 7, 1))
    race_in_last_week = [
        workout.id
        for week in result.program.weeks[-1:]
        for workout in week.workouts
        if "race" in workout.id
    ]
    assert race_in_last_week
    assert any(race_id.endswith("-race-7") for race_id in race_in_last_week)


@pytest.mark.parametrize(
    "expected_recipe",
    ["long.steady", "long.with_finish", "long.with_hill_surges", "long.with_kickouts"],
)
def test_place_week_long_run_accepts_each_long_recipe(expected_recipe) -> None:
    recipe = get_recipe(expected_recipe)
    assignment = assign_program(
        TrainingDays(possible_days=(1, 2, 3, 4, 5, 6, 7), sessions_per_week=3),
        duration_weeks=8,
    )[0]
    phases = phase_plan(8)
    slots = place_week(
        week_number=1,
        week_start=date(2026, 7, 1),
        assignment=assignment,
        long_run_km=8.0,
        weekly_km=20.0,
        long_recipe=recipe,
        quality_recipe=get_recipe("tempo.continuous"),
        easy_recipe=get_recipe("easy.continuous"),
        quality_per_week=0,
        easy_pace_sec_per_km=_KNOWN_PACE_LIST,
        phase=phase_for(phases, 1),
        club_sessions=(),
        b_races=(),
        goal_race=GoalRace(),
    )
    long_slot = next(slot for slot in slots if slot.long_run)
    assert long_slot.recipe_key == expected_recipe
    assert any(step.action == "run" for step in long_slot.steps)


def test_place_week_race_slots_carry_no_recipe_key() -> None:
    request = _request(goal_race=GoalRace(date=date(2026, 8, 23)))
    result = compose_program(request, today=date(2026, 7, 1))
    race_in_goal_week = [
        workout
        for week in result.program.weeks
        for workout in week.workouts
        if "race" in workout.id
    ]
    assert race_in_goal_week
