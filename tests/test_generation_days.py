"""Tests for the day assignment and variety module."""

from __future__ import annotations

from runplan.generation import (
    TrainingDays,
)
from runplan.generation.days import (
    assign_program,
    assign_week,
    pick_long_run_day,
    pick_quality_day,
)
from runplan.generation.variety import (
    VarietyBoard,
    pick_long_run_recipe,
    pick_quality_recipe,
)


def test_long_run_day_respects_preference() -> None:
    assert pick_long_run_day((1, 3, 5, 7), 7) == 7
    assert pick_long_run_day((1, 3, 5, 7), 2) == 7  # falls back to latest in pool


def test_quality_day_avoids_consecutive_to_long_run() -> None:
    pool = (1, 3, 5, 7)
    chosen = pick_quality_day(pool, 7, prev_quality_day=None)
    assert chosen in pool
    assert chosen != 7
    assert abs(chosen - 7) >= 2


def test_quality_day_avoids_repeating_previous_week() -> None:
    pool = (1, 2, 3, 4, 5, 6, 7)
    chosen = pick_quality_day(pool, 7, prev_quality_day=3)
    assert chosen != 3


def test_assign_week_produces_disjoint_days() -> None:
    pool = (1, 3, 5, 7)
    assignment = assign_week(
        pool, sessions_per_week=3, long_run_day=7, prev_quality_day=None, week_index=0
    )
    days = {assignment.long_run_day, *assignment.easy_days}
    if assignment.quality_day is not None:
        days.add(assignment.quality_day)
    assert len(days) == len([*days])


def test_assign_program_rotates_long_run_when_pool_is_large() -> None:
    days = TrainingDays(possible_days=(1, 2, 3, 4, 5, 6, 7), sessions_per_week=3)
    assignments = assign_program(days, duration_weeks=8, preferred_long_run_day=7)
    long_days = {a.long_run_day for a in assignments}
    assert len(long_days) >= 2


def test_variety_avoids_repeating_consecutive_quality() -> None:
    board = VarietyBoard()
    kinds: list[str] = []
    for week in range(6):
        recipe, board = pick_quality_recipe(board, week)
        kinds.append(recipe.key)
    for previous, current in zip(kinds, kinds[1:], strict=False):
        assert previous != current


def test_variety_avoids_repeating_consecutive_long_run() -> None:
    board = VarietyBoard()
    kinds: list[str] = []
    for week in range(6):
        recipe, board = pick_long_run_recipe(board, week)
        kinds.append(recipe.key)
    for previous, current in zip(kinds, kinds[1:], strict=False):
        assert previous != current


def test_variety_summary_reflects_history() -> None:
    board = VarietyBoard()
    for week in range(6):
        recipe, board = pick_quality_recipe(board, week)
    history = board.quality_history
    assert len(history) == 6
    assert len(set(history)) >= 3


def test_pick_long_run_day_prefers_sunday_in_full_week() -> None:
    assert pick_long_run_day((1, 2, 3, 4, 5, 6, 7), None) == 7


def test_pick_long_run_day_prefers_saturday_when_sunday_missing() -> None:
    assert pick_long_run_day((1, 2, 3, 4, 5, 6), None) == 6


def test_pick_long_run_day_falls_back_when_pool_has_no_weekend() -> None:
    assert pick_long_run_day((1, 3, 5), None) == 5


def test_pick_long_run_day_respects_explicit_preference() -> None:
    assert pick_long_run_day((1, 2, 3, 4, 5, 6, 7), 3) == 3


def test_three_sessions_with_zero_quality_produces_three_workouts() -> None:
    """Regression test: off-by-one bug dropped the quality slot silently."""
    assignment = assign_week(
        pool=(1, 2, 3, 4, 5, 6, 7),
        sessions_per_week=3,
        long_run_day=7,
        prev_quality_day=None,
        week_index=0,
        quality_per_week=0,
    )
    assert assignment.quality_day is None
    assert len(assignment.easy_days) == 2
    assert len(assignment.all_days()) == 3


def test_three_sessions_with_quality_produces_three_workouts() -> None:
    assignment = assign_week(
        pool=(1, 2, 3, 4, 5, 6, 7),
        sessions_per_week=3,
        long_run_day=7,
        prev_quality_day=None,
        week_index=0,
        quality_per_week=1,
    )
    assert assignment.quality_day is not None
    assert len(assignment.easy_days) == 1
    assert len(assignment.all_days()) == 3


def test_four_sessions_with_quality_produces_four_workouts() -> None:
    assignment = assign_week(
        pool=(1, 2, 3, 4, 5, 6, 7),
        sessions_per_week=4,
        long_run_day=7,
        prev_quality_day=None,
        week_index=0,
        quality_per_week=1,
    )
    assert assignment.quality_day is not None
    assert len(assignment.easy_days) == 2
    assert len(assignment.all_days()) == 4


def test_two_sessions_with_no_quality_produces_two_workouts() -> None:
    assignment = assign_week(
        pool=(1, 2, 3, 4, 5, 6, 7),
        sessions_per_week=2,
        long_run_day=7,
        prev_quality_day=None,
        week_index=0,
        quality_per_week=0,
    )
    assert assignment.quality_day is None
    assert len(assignment.easy_days) == 1
    assert len(assignment.all_days()) == 2
