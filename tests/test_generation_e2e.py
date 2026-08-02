"""End-to-end tests for the first 10K generator."""

from __future__ import annotations

from datetime import date

import pytest

from runplan.generation import (
    BRace,
    ClubSession,
    GeneratorRequest,
    GoalRace,
    TrainingDays,
    compose_program,
    plan_to_yaml,
)
from runplan.generation.errors import GenerationError
from runplan.generation.serialize import validate_yaml


def _request(**kwargs) -> GeneratorRequest:
    defaults = {
        "start_week": "2026-W32",
        "duration_weeks": 12,
        "current_weekly_km": 25,
        "current_longest_km": 6,
        "training_days": TrainingDays(possible_days=(1, 2, 3, 4, 5, 6, 7), sessions_per_week=4),
    }
    defaults.update(kwargs)
    return GeneratorRequest(**defaults)


def test_begins_with_zero_history_starts_with_run_walk() -> None:
    result = compose_program(
        _request(current_weekly_km=0, current_longest_km=None), today=date(2026, 7, 1)
    )
    assert len(result.program.weeks) == 12
    first_week = result.program.weeks[0]
    assert any(w.id.startswith("week-01") for w in first_week.workouts)


def test_goal_race_outside_window_is_rejected() -> None:
    request = _request(goal_race=GoalRace(date=date(2027, 1, 1)))
    with pytest.raises(GenerationError, match="outside the program window"):
        compose_program(request, today=date(2026, 7, 1))


def test_all_weeks_have_at_least_one_workout() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    for week in result.program.weeks:
        assert week.workouts


def test_generated_yaml_round_trips_through_parser() -> None:
    result = compose_program(_request(known_easy_pace_sec=(340, 360)), today=date(2026, 7, 1))
    yaml = plan_to_yaml(result)
    program = validate_yaml(yaml)
    assert program.id == result.program.id
    assert len(program.weeks) == len(result.program.weeks)


def test_b_race_replaces_planned_workout_in_that_week() -> None:
    b_race = BRace(date=date(2026, 9, 16), distance_km=5.0, intensity="controlled")
    request = _request(b_races=(b_race,))
    result = compose_program(request, today=date(2026, 7, 1))
    race_workouts = [
        workout
        for week in result.program.weeks
        for workout in week.workouts
        if "b-race" in workout.id
    ]
    assert race_workouts


def test_club_session_overrides_planned_workout() -> None:
    club = ClubSession(weekday=3, type="easy", distance_km=8.0, note="Club easy")
    request = _request(club_sessions=(club,))
    result = compose_program(request, today=date(2026, 7, 1))
    club_workouts = [
        workout
        for week in result.program.weeks
        for workout in week.workouts
        if "club" in workout.id
    ]
    assert club_workouts


def test_quality_day_never_touches_long_run_day() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    for week in result.program.weeks:
        long_days = {
            w.day
            for w in week.workouts
            if w.id.endswith(tuple(f"-day-{day}-long" for day in range(1, 8)))
        }
        quality_days = {w.day for w in week.workouts if "quality" in w.id}
        assert long_days.isdisjoint(quality_days)


def test_quality_days_rotate_week_to_week() -> None:
    result = compose_program(_request(quality_sessions_per_week=1), today=date(2026, 7, 1))
    quality_days = []
    for week in result.program.weeks:
        for workout in week.workouts:
            if "quality" in workout.id:
                quality_days.append((week.number, workout.day))
    assert len(set(day for _, day in quality_days)) >= 3


def test_long_run_share_never_exceeds_40_percent() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    for week, week_km in zip(result.program.weeks, result.volume_plan.weekly_km, strict=False):
        long_runs = [w for w in week.workouts if w.id.endswith("-long")]
        if long_runs and week_km > 0:
            assert len(long_runs) == 1


def test_recovery_weeks_have_lower_volume() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    for recovery_week in result.volume_plan.recovery_weeks:
        idx = recovery_week - 1
        if idx > 0:
            assert result.volume_plan.weekly_km[idx] < result.volume_plan.weekly_km[idx - 1]


def test_variety_summary_lists_used_templates() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    assert result.variety_summary["quality_types_used"] >= 3
    assert result.variety_summary["long_run_types_used"] >= 2


def test_intensity_distribution_is_pyramidal() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    avg = result.intensity_targets_summary()
    low = avg["zone1"] + avg["zone2"]
    assert low >= 0.65


def test_quality_sessions_per_week_one_when_enabled() -> None:
    result = compose_program(_request(quality_sessions_per_week=1), today=date(2026, 7, 1))
    weeks_with_quality = sum(
        1 for week in result.program.weeks for workout in week.workouts if "quality" in workout.id
    )
    assert weeks_with_quality >= 10


def test_no_quality_sessions_when_zero() -> None:
    result = compose_program(_request(quality_sessions_per_week=0), today=date(2026, 7, 1))
    weeks_with_quality = sum(
        1 for week in result.program.weeks for workout in week.workouts if "quality" in workout.id
    )
    assert weeks_with_quality == 0


def test_taper_reduces_last_two_weeks() -> None:
    result = compose_program(_request(), today=date(2026, 7, 1))
    weeks = result.volume_plan.weekly_km
    peak = max(weeks[:-2])
    assert weeks[-1] < peak
    assert weeks[-2] < peak


def test_default_request_with_no_history_warns() -> None:
    request = _request(current_weekly_km=0, current_longest_km=None)
    result = compose_program(request, today=date(2026, 7, 1))
    codes = [w.code for w in result.warnings]
    assert "no-history" in codes


def test_no_pace_warning_when_known_easy_pace_missing() -> None:
    result = compose_program(_request(known_easy_pace_sec=None), today=date(2026, 7, 1))
    codes = [w.code for w in result.warnings]
    assert "no-pace" in codes


def test_two_days_per_week_is_smaller_schedule() -> None:
    two_days = TrainingDays(possible_days=(2, 5), sessions_per_week=2)
    result = compose_program(_request(training_days=two_days), today=date(2026, 7, 1))
    for week in result.program.weeks:
        assert len(week.workouts) == 2


def test_five_days_per_week_is_larger_schedule() -> None:
    five_days = TrainingDays(possible_days=(1, 2, 3, 4, 5, 6, 7), sessions_per_week=5)
    result = compose_program(_request(training_days=five_days), today=date(2026, 7, 1))
    for week in result.program.weeks:
        assert len(week.workouts) >= 3


def test_eight_week_program_succeeds() -> None:
    result = compose_program(_request(duration_weeks=8), today=date(2026, 7, 1))
    assert len(result.program.weeks) == 8


def test_sixteen_week_program_succeeds() -> None:
    result = compose_program(_request(duration_weeks=16), today=date(2026, 7, 1))
    assert len(result.program.weeks) == 16


def test_known_pace_emits_pace_targets() -> None:
    result = compose_program(_request(known_easy_pace_sec=(330, 350)), today=date(2026, 7, 1))
    yaml = plan_to_yaml(result)
    assert "min/km" in yaml


def test_goal_race_in_final_week_replaces_long_run() -> None:
    request = _request(goal_race=GoalRace(date=date(2026, 10, 25)))
    result = compose_program(request, today=date(2026, 7, 1))
    last_week = result.program.weeks[-1]
    assert any(w.id.endswith("-race-7") for w in last_week.workouts)


def test_full_yaml_has_english_only_keys() -> None:
    import re

    result = compose_program(_request(), today=date(2026, 7, 1))
    yaml = plan_to_yaml(result)
    danish_key = re.compile(
        r"(?:^\s*|[{,]\s*)(?:navn|beskrivelse|startdato|uger|uge|fokus|dag|"
        r"trin|opvarmning|løb|gå|afslutning|gentag|antal|tid|tempo):",
        re.MULTILINE,
    )
    assert danish_key.search(yaml) is None
