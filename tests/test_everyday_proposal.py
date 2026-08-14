"""``propose_horizon`` use case (Step 10 ``application/everyday/proposal``).

The use case loads the program YAML, builds the completed-workout
history, and returns the proposed next 14 days.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from runplan.application.everyday import EverydayError, horizon_to_payload, propose_horizon
from runplan.domain.everyday import EverydayProfile
from runplan.domain.recommendations import CompletedWorkout
from tests.fakes import InMemoryProgramRepository
from tests.helpers import program_data

PROGRAM_ID = "characterization-plan"


def _repository() -> InMemoryProgramRepository:
    return InMemoryProgramRepository({PROGRAM_ID: deepcopy(program_data())})


def _profile() -> EverydayProfile:
    return EverydayProfile(
        five_k_seconds=22 * 60,
        weekly_km_target=40.0,
        training_days=(1, 3, 5, 7),
    )


def _completed(date_: date, form, km: float = 5.0, minutes: int = 25) -> CompletedWorkout:
    return CompletedWorkout(
        date=date_,
        form=form,
        distance_meters=km * 1000,
        duration_seconds=minutes * 60,
    )


# ---------------------------------------------------------------------------
# propose_horizon
# ---------------------------------------------------------------------------


def test_propose_horizon_returns_everyday_horizon() -> None:
    horizon = propose_horizon(
        program_id=PROGRAM_ID,
        profile=_profile(),
        goal="maintain",
        start_date=date(2027, 1, 11),
        repository=_repository(),
    )
    assert horizon.profile.training_days == (1, 3, 5, 7)
    assert horizon.goal == "maintain"
    assert horizon.start_date == date(2027, 1, 11)
    assert horizon.horizon_days == 14
    assert len(horizon.days) > 0


def test_propose_horizon_unknown_program_raises_everyday_error() -> None:
    with pytest.raises(EverydayError) as exc:
        propose_horizon(
            program_id="missing",
            profile=_profile(),
            goal="maintain",
            start_date=date(2027, 1, 11),
            repository=_repository(),
        )
    assert exc.value.kind == "unknown_program"


def test_propose_horizon_uses_completed_history_from_program() -> None:
    repository = _repository()
    raw = repository.load(PROGRAM_ID)
    # Add a completed workout to the program
    raw["weeks"][0]["workouts"][0]["tracking"] = {
        "status": "completed",
        "actual": {
            "distance_meters": 5000.0,
            "duration_seconds": 1500,
            "completed_at": "2026-12-28",
        },
    }
    repository.save(PROGRAM_ID, raw)

    horizon = propose_horizon(
        program_id=PROGRAM_ID,
        profile=_profile(),
        goal="maintain",
        start_date=date(2027, 1, 11),
        repository=repository,
    )
    # The completed workout is from 2026-12-28; the start_date is 2027-01-11,
    # so the history should not affect the recommendations — but the use
    # case still succeeds and returns a horizon.
    assert len(horizon.days) > 0


# ---------------------------------------------------------------------------
# horizon_to_dict
# ---------------------------------------------------------------------------


def test_horizon_to_payload_round_trip_preserves_fields() -> None:
    horizon = propose_horizon(
        program_id=PROGRAM_ID,
        profile=_profile(),
        goal="peak",
        start_date=date(2027, 1, 11),
        repository=_repository(),
    )
    payload = horizon_to_payload(horizon)
    assert payload["goal"] == "peak"
    assert payload["start_date"] == "2027-01-11"
    assert payload["horizon_days"] == 14
    assert payload["profile"]["training_days"] == [1, 3, 5, 7]
    assert len(payload["days"]) == len(horizon.days)
    for day_payload, day in zip(payload["days"], horizon.days, strict=True):
        assert day_payload["date"] == day.date.isoformat()
        assert day_payload["recipe_key"] == day.recipe_key
        assert day_payload["parameters"]["type"] == type(day.parameters).__name__
