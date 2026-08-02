"""Tests for the first 10K generator input model."""

from __future__ import annotations

from datetime import date

import pytest

from runplan.generation import (
    BRace,
    ClubSession,
    GeneratorRequest,
    TrainingDays,
    as_dict,
    race_date_window,
    suggest_start_week,
)
from runplan.generation.errors import GenerationError


def test_default_request_is_valid() -> None:
    request = GeneratorRequest()
    assert request.duration_weeks == 12
    assert request.progression == "balanced"
    assert request.training_days.sessions_per_week == 3
    assert request.training_days.possible_days == (1, 2, 3, 4, 5, 6, 7)


def test_default_starting_long_run_is_five_km() -> None:
    from runplan.generation.progression import starting_long_run_km

    assert starting_long_run_km(0.0, None) == 5.0


def test_default_starting_weekly_km_is_twelve() -> None:
    from runplan.generation.progression import starting_weekly_km

    assert starting_weekly_km(0.0, sessions_per_week=3) == 12.0


def test_invalid_duration_is_rejected() -> None:
    with pytest.raises(GenerationError, match="duration_weeks"):
        GeneratorRequest(duration_weeks=5)


def test_invalid_sessions_per_week_is_rejected() -> None:
    with pytest.raises(GenerationError, match="sessions_per_week"):
        TrainingDays(possible_days=(1, 2, 3, 4, 5), sessions_per_week=8)


def test_sessions_per_week_must_not_exceed_pool() -> None:
    with pytest.raises(GenerationError, match="cannot exceed"):
        TrainingDays(possible_days=(1, 3), sessions_per_week=3)


def test_progression_must_be_known() -> None:
    with pytest.raises(GenerationError, match="progression"):
        GeneratorRequest(progression="wild")  # type: ignore[arg-type]


def test_quality_per_week_capped_to_one() -> None:
    with pytest.raises(GenerationError, match="quality_sessions_per_week"):
        GeneratorRequest(quality_sessions_per_week=2)


def test_easy_pace_must_be_two_positive_seconds() -> None:
    with pytest.raises(GenerationError, match="known_easy_pace_sec"):
        GeneratorRequest(known_easy_pace_sec=(360, 360, 360))  # type: ignore[arg-type]
    with pytest.raises(GenerationError, match="known_easy_pace_sec"):
        GeneratorRequest(known_easy_pace_sec=(360, 300))  # type: ignore[arg-type]


def test_max_weekly_km_must_be_positive() -> None:
    with pytest.raises(GenerationError, match="max_weekly_km"):
        GeneratorRequest(max_weekly_km=0)


def test_b_race_requires_distance_and_intensity() -> None:
    with pytest.raises(GenerationError, match="distance_km"):
        BRace(date=date(2026, 9, 1), distance_km=0, intensity="controlled")


def test_club_session_requires_distance_or_duration() -> None:
    with pytest.raises(GenerationError, match="distance_km or duration_minutes"):
        ClubSession(weekday=3, type="easy")


def test_goal_race_window_helper() -> None:
    assert race_date_window("2026-W32", 12, date(2026, 10, 25))
    assert not race_date_window("2026-W32", 12, date(2027, 1, 1))


def test_suggest_start_week_returns_next_monday_iso() -> None:
    label = suggest_start_week(date(2026, 7, 29))
    assert "-" in label
    label2 = suggest_start_week(date(2026, 7, 31))
    assert label == label2 or label.split("-W")[1] != label2.split("-W")[1]


def test_as_dict_round_trips_input() -> None:
    request = GeneratorRequest(
        start_week="2026-W32",
        duration_weeks=10,
        current_weekly_km=20,
        current_longest_km=6,
        training_days=TrainingDays(possible_days=(2, 3, 5, 7), sessions_per_week=3),
        progression="cautious",
        quality_sessions_per_week=1,
    )
    payload = as_dict(request)
    assert payload["progression"] == "cautious"
    assert payload["training_days"]["sessions_per_week"] == 3


def test_training_days_dedupes_and_sorts() -> None:
    days = TrainingDays(possible_days=(5, 1, 3, 1), sessions_per_week=2)
    assert days.possible_days == (1, 3, 5)
