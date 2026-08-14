"""Pure rolling everyday horizon generator (Step 10 ``generation/everyday``).

The tests cover the five named scenarios from the Step 10 plan:
``new_runner``, ``winter_goal``, ``post_holiday``, ``travel_week``, and
``injury_return``. Plus the boundary cases: the key-workout rule across
the horizon boundary and the goal-driven key-workout budget.
"""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from runplan.domain.everyday import EverydayProfile, EverydayRequest
from runplan.domain.recommendations import CompletedWorkout
from runplan.domain.workout_form import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    RUN_WALK,
    TEMPO_RUN,
)
from runplan.generation.everyday import propose_everyday_horizon

_PROFILE = EverydayProfile(
    five_k_seconds=22 * 60,
    weekly_km_target=40.0,
    training_days=(1, 3, 5, 7),
    preferred_long_run_day=7,
)


def _easy(date_: date, km: float = 5.0, minutes: int = 25) -> CompletedWorkout:
    return CompletedWorkout(
        date=date_,
        form=EASY_RUN,
        distance_meters=km * 1000,
        duration_seconds=minutes * 60,
    )


def _key(date_: date, form, km: float = 10.0, minutes: int = 55) -> CompletedWorkout:
    return CompletedWorkout(
        date=date_,
        form=form,
        distance_meters=km * 1000,
        duration_seconds=minutes * 60,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _solid_baseline(anchor: date, weeks: int = 4) -> tuple[CompletedWorkout, ...]:
    """A solid baseline spread across ``weeks`` weeks ending 8 days before ``anchor``."""
    history: list[CompletedWorkout] = []
    for week in range(weeks):
        for offset in (1, 4, 7):
            history.append(
                _easy(
                    anchor - timedelta(days=week * 7 + (7 - offset)),
                    km=8.0,
                    minutes=40,
                )
            )
    return tuple(sorted(history, key=lambda w: w.date))


# ---------------------------------------------------------------------------
# New runner scenario
# ---------------------------------------------------------------------------


def test_new_runner_with_no_history_every_day_is_easy_or_recovery() -> None:
    request = EverydayRequest(
        profile=_PROFILE,
        goal="maintain",
        start_date=date(2026, 1, 12),
        horizon_days=14,
    )
    horizon = propose_everyday_horizon(request)

    assert len(horizon.days) > 0
    for day in horizon.days:
        assert day.form in {EASY_RUN, RECOVERY_RUN, RUN_WALK}
        assert day.recipe_key != ""
        assert "key" not in day.recipe_key  # no key workouts without history


def test_new_runner_respects_training_days() -> None:
    request = EverydayRequest(
        profile=_PROFILE,
        goal="maintain",
        start_date=date(2026, 1, 12),
        horizon_days=14,
    )
    horizon = propose_everyday_horizon(request)
    for day in horizon.days:
        assert day.date.isoweekday() in _PROFILE.training_days


# ---------------------------------------------------------------------------
# Winter goal (peak) scenario
# ---------------------------------------------------------------------------


def test_peak_goal_with_solid_baseline_produces_at_least_one_key_workout() -> None:
    request = EverydayRequest(
        profile=_PROFILE,
        goal="peak",
        start_date=date(2026, 1, 12),
        horizon_days=14,
        history=_solid_baseline(date(2026, 1, 12)),
    )
    horizon = propose_everyday_horizon(request)

    key_count = sum(
        1 for day in horizon.days if day.form in {LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT}
    )
    assert key_count >= 1


# ---------------------------------------------------------------------------
# Post-holiday (low recent load) scenario
# ---------------------------------------------------------------------------


def test_post_holiday_low_recent_load_remains_easy() -> None:
    """A sparse recent window should keep the runner on easy runs."""
    anchor = date(2026, 1, 12)
    history: list[CompletedWorkout] = []
    # Three sessions 10-14 days ago (baseline)
    for offset in (12, 14, 13):
        history.append(_easy(anchor - timedelta(days=offset), km=5, minutes=25))
    request = EverydayRequest(
        profile=_PROFILE,
        goal="build",
        start_date=anchor,
        horizon_days=14,
        history=tuple(sorted(history, key=lambda w: w.date)),
    )
    horizon = propose_everyday_horizon(request)
    for day in horizon.days:
        assert day.form in {EASY_RUN, RECOVERY_RUN, RUN_WALK}


# ---------------------------------------------------------------------------
# Travel week scenario
# ---------------------------------------------------------------------------


def test_travel_week_with_reduced_training_days() -> None:
    travel_profile = EverydayProfile(
        five_k_seconds=_PROFILE.five_k_seconds,
        weekly_km_target=_PROFILE.weekly_km_target,
        training_days=(2, 5),  # mid-week travel
        preferred_long_run_day=_PROFILE.preferred_long_run_day,
    )
    request = EverydayRequest(
        profile=travel_profile,
        goal="maintain",
        start_date=date(2026, 1, 12),
        horizon_days=14,
    )
    horizon = propose_everyday_horizon(request)
    for day in horizon.days:
        assert day.date.isoweekday() in travel_profile.training_days
    # Two training days per week × 2 weeks = up to 4 days
    assert 1 <= len(horizon.days) <= 4


# ---------------------------------------------------------------------------
# Injury return scenario (low readiness proxy: very low volume)
# ---------------------------------------------------------------------------


def test_injury_return_with_sparse_history_easy_default() -> None:
    anchor = date(2026, 1, 12)
    history = (_easy(anchor - timedelta(days=12), km=3, minutes=15),)
    request = EverydayRequest(
        profile=_PROFILE,
        goal="build",
        start_date=anchor,
        horizon_days=14,
        history=history,
    )
    horizon = propose_everyday_horizon(request)
    for day in horizon.days:
        assert day.form in {EASY_RUN, RECOVERY_RUN, RUN_WALK}


# ---------------------------------------------------------------------------
# Key-workout rule across the horizon boundary
# ---------------------------------------------------------------------------


def test_key_workout_rule_holds_across_horizon_boundary() -> None:
    """A long run on day 0 must not be followed by a key workout on day 1."""
    anchor = date(2026, 1, 12)
    history = _solid_baseline(anchor)
    request = EverydayRequest(
        profile=_PROFILE,
        goal="peak",
        start_date=anchor,
        horizon_days=14,
        history=history,
    )
    horizon = propose_everyday_horizon(request)
    for previous, current in zip(horizon.days, horizon.days[1:], strict=False):
        if previous.form not in {LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT}:
            continue
        if (current.date - previous.date).days != 1:
            continue
        assert current.form not in {LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT}


# ---------------------------------------------------------------------------
# Goal-driven key-workout budget
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("goal", "expected_max_in_horizon"),
    [("base", 0), ("maintain", 2), ("build", 4), ("peak", 4)],
)
def test_goal_key_workout_budget(goal: str, expected_max_in_horizon: int) -> None:
    """Each goal caps how many key workouts can appear in the 14-day horizon."""
    anchor = date(2026, 1, 12)
    request = EverydayRequest(
        profile=_PROFILE,
        goal=goal,  # type: ignore[arg-type]
        start_date=anchor,
        horizon_days=14,
        history=_solid_baseline(anchor),
    )
    horizon = propose_everyday_horizon(request)
    key_count = sum(
        1 for day in horizon.days if day.form in {LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT}
    )
    if goal == "base":
        assert key_count == 0
    elif goal == "maintain":
        assert key_count <= 1
    else:
        # build/peak: the recommender's own gates apply, so we only assert non-explosion
        assert key_count <= expected_max_in_horizon


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_propose_is_deterministic_for_same_inputs() -> None:
    anchor = date(2026, 1, 12)
    request_a = EverydayRequest(
        profile=_PROFILE,
        goal="peak",
        start_date=anchor,
        horizon_days=14,
        history=_solid_baseline(anchor),
    )
    request_b = EverydayRequest(
        profile=_PROFILE,
        goal="peak",
        start_date=anchor,
        horizon_days=14,
        history=_solid_baseline(anchor),
    )
    horizon_a = propose_everyday_horizon(request_a)
    horizon_b = propose_everyday_horizon(request_b)
    assert len(horizon_a.days) == len(horizon_b.days)
    for day_a, day_b in zip(horizon_a.days, horizon_b.days, strict=True):
        assert day_a.date == day_b.date
        assert day_a.recipe_key == day_b.recipe_key
        assert day_a.form == day_b.form
