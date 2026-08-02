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
    pick_long_run_kind,
    pick_quality_kind,
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
        kind, board = pick_quality_kind(board, week)
        kinds.append(kind)
    for previous, current in zip(kinds, kinds[1:], strict=False):
        assert previous != current


def test_variety_avoids_repeating_consecutive_long_run() -> None:
    board = VarietyBoard()
    kinds: list[str] = []
    for week in range(6):
        kind, board = pick_long_run_kind(board, week)
        kinds.append(kind)
    for previous, current in zip(kinds, kinds[1:], strict=False):
        assert previous != current


def test_variety_summary_reflects_history() -> None:
    board = VarietyBoard()
    for week in range(6):
        kind, board = pick_quality_kind(board, week)
    history = board.quality_used
    assert len(history) == 6
    assert len(set(history)) >= 3
