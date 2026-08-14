"""Domain types for the rolling everyday plan (Step 10 ``domain/everyday``).

The tests cover the validation behaviour of ``EverydayProfile``,
``EverydayRequest``, and the JSON-friendly ``EverydayHorizon`` round-trip.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from runplan.domain.everyday import (
    EverydayGoal,
    EverydayHorizon,
    EverydayProfile,
    EverydayRequest,
    ProposedDay,
)
from runplan.domain.recipes import EasyContinuousParameters
from runplan.domain.workout_form import EASY_RUN


def _profile(**overrides) -> EverydayProfile:
    defaults = {
        "five_k_seconds": 30 * 60,
        "weekly_km_target": 30.0,
        "training_days": (1, 3, 5),
        "preferred_long_run_day": None,
    }
    defaults.update(overrides)
    return EverydayProfile(**defaults)


# ---------------------------------------------------------------------------
# EverydayProfile
# ---------------------------------------------------------------------------


def test_everyday_profile_is_frozen() -> None:
    profile = _profile()
    with pytest.raises(FrozenInstanceError):
        profile.five_k_seconds = 60 * 60  # type: ignore[misc]


def test_everyday_profile_rejects_negative_five_k_seconds() -> None:
    with pytest.raises(ValueError, match="five_k_seconds"):
        _profile(five_k_seconds=-1.0)


def test_everyday_profile_rejects_negative_weekly_km() -> None:
    with pytest.raises(ValueError, match="weekly_km_target"):
        _profile(weekly_km_target=-1.0)


def test_everyday_profile_requires_at_least_one_training_day() -> None:
    with pytest.raises(ValueError, match="training_days"):
        _profile(training_days=())


def test_everyday_profile_rejects_out_of_range_training_days() -> None:
    with pytest.raises(ValueError, match="training_days entries"):
        _profile(training_days=(0, 1, 3))
    with pytest.raises(ValueError, match="training_days entries"):
        _profile(training_days=(8, 1, 3))


def test_everyday_profile_normalises_training_days() -> None:
    profile = _profile(training_days=(5, 1, 3, 5, 3))
    assert profile.training_days == (1, 3, 5)


def test_everyday_profile_rejects_out_of_range_long_run_day() -> None:
    with pytest.raises(ValueError, match="preferred_long_run_day"):
        _profile(preferred_long_run_day=8)


def test_everyday_profile_has_pace_when_seconds_positive() -> None:
    assert _profile(five_k_seconds=1.0).has_pace() is True
    assert _profile(five_k_seconds=0.0).has_pace() is False


# ---------------------------------------------------------------------------
# EverydayRequest
# ---------------------------------------------------------------------------


def test_everyday_request_defaults_horizon_days() -> None:
    request = EverydayRequest(
        profile=_profile(),
        goal="maintain",
        start_date=date(2026, 1, 12),
    )
    assert request.horizon_days == 14
    assert request.history == ()


def test_everyday_request_rejects_invalid_goal() -> None:
    with pytest.raises(ValueError, match="goal must be one of"):
        EverydayRequest(
            profile=_profile(),
            goal="not-a-goal",  # type: ignore[arg-type]
            start_date=date(2026, 1, 12),
        )


def test_everyday_request_rejects_zero_or_negative_horizon() -> None:
    with pytest.raises(ValueError, match="horizon_days"):
        EverydayRequest(
            profile=_profile(),
            goal="maintain",
            start_date=date(2026, 1, 12),
            horizon_days=0,
        )


def test_everyday_request_accepts_history_tuple() -> None:
    request = EverydayRequest(
        profile=_profile(),
        goal="build",
        start_date=date(2026, 1, 12),
        history=(),
    )
    assert request.history == ()


# ---------------------------------------------------------------------------
# ProposedDay and EverydayHorizon
# ---------------------------------------------------------------------------


def _proposed_day(target: date) -> ProposedDay:
    return ProposedDay(
        date=target,
        form=EASY_RUN,
        recipe_key="easy.continuous",
        parameters=EasyContinuousParameters(minutes=30),
        reasoning=("reason",),
        warnings=("warning",),
    )


def test_proposed_day_is_frozen() -> None:
    day = _proposed_day(date(2026, 1, 12))
    with pytest.raises(FrozenInstanceError):
        day.date = date(2027, 1, 1)  # type: ignore[misc]


def test_everyday_horizon_as_request_drops_history() -> None:
    profile = _profile()
    horizon = EverydayHorizon(
        profile=profile,
        goal="maintain",
        start_date=date(2026, 1, 12),
        horizon_days=14,
        days=(_proposed_day(date(2026, 1, 12)),),
    )
    request = horizon.as_request()
    assert request.profile == profile
    assert request.goal == "maintain"
    assert request.start_date == date(2026, 1, 12)
    assert request.horizon_days == 14
    assert request.history == ()


def test_everyday_horizon_is_frozen() -> None:
    horizon = EverydayHorizon(
        profile=_profile(),
        goal="maintain",
        start_date=date(2026, 1, 12),
        horizon_days=14,
        days=(),
    )
    with pytest.raises(FrozenInstanceError):
        horizon.goal = "peak"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# EverydayGoal literal
# ---------------------------------------------------------------------------


def test_everyday_goal_contains_expected_values() -> None:
    import typing

    args = typing.get_args(EverydayGoal)
    assert set(args) == {"maintain", "base", "build", "peak"}
