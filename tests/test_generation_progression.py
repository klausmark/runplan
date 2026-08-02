"""Tests for the volume progression module."""

from __future__ import annotations

from runplan.generation.progression import (
    LONG_RUN_SHARE_MAX,
    RECOVERY_REDUCTION,
    build_volume_plan,
    starting_long_run_km,
    starting_weekly_km,
)


def _plan(profile: str = "balanced", start_km: float = 0.0, **kwargs):
    return build_volume_plan(
        duration_weeks=12,
        current_weekly_km=start_km,
        current_longest_km=kwargs.get("current_longest_km"),
        sessions_per_week=kwargs.get("sessions_per_week", 3),
        profile=profile,  # type: ignore[arg-type]
        max_weekly_km=kwargs.get("max_weekly_km"),
        max_long_run_km=kwargs.get("max_long_run_km"),
    )


def test_zero_starting_volume_uses_safe_default() -> None:
    start = starting_weekly_km(0.0, sessions_per_week=3)
    assert start >= 6.0


def test_beginner_long_run_starts_short() -> None:
    long = starting_long_run_km(0.0, None)
    assert 3.0 <= long <= 6.0


def test_recovery_and_taper_weeks_partition_first_to_last() -> None:
    plan = _plan(start_km=25)
    reduced = set(plan.recovery_weeks) | set(plan.taper_weeks)
    expected = {4, 8, 11, 12}
    assert reduced == expected


def test_three_increasing_weeks_never_followed_by_increase() -> None:
    plan = _plan(start_km=25)
    weeks = list(plan.weekly_km)
    for index in range(3, len(weeks)):
        if (index + 1) % 4 == 0 and (index + 1) not in plan.taper_weeks:
            assert weeks[index] < weeks[index - 1]


def test_long_run_share_never_exceeds_forty_percent() -> None:
    plan = _plan(start_km=30)
    for week_km, long_km in zip(plan.weekly_km, plan.long_run_km, strict=True):
        if week_km > 0:
            assert long_km <= week_km * LONG_RUN_SHARE_MAX + 0.01


def test_max_weekly_km_is_respected() -> None:
    plan = _plan(start_km=40, max_weekly_km=45)
    assert all(week <= 45 for week in plan.weekly_km)


def test_max_long_run_km_is_respected() -> None:
    plan = _plan(start_km=40, max_long_run_km=8)
    assert all(long <= 8 for long in plan.long_run_km)


def test_recovery_week_reduces_volume_substantially() -> None:
    plan = _plan(start_km=30)
    for recovery_week in plan.recovery_weeks:
        idx = recovery_week - 1
        if idx >= 1:
            previous = plan.weekly_km[idx - 1]
            current = plan.weekly_km[idx]
            assert current <= previous * RECOVERY_REDUCTION + 0.5


def test_cautious_profile_grows_slower_than_ambitious() -> None:
    cautious = _plan(profile="cautious", start_km=25)
    ambitious = _plan(profile="ambitious", start_km=25)
    assert cautious.peak_km() <= ambitious.peak_km() + 0.5


def test_taper_weeks_reduce_volume() -> None:
    plan = _plan(start_km=30)
    if plan.taper_weeks:
        first_taper = plan.taper_weeks[0]
        idx = first_taper - 1
        if idx > 0:
            assert plan.weekly_km[idx] < plan.weekly_km[idx - 1]
