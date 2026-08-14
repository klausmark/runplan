"""``accept_horizon`` use case (Step 10 ``application/everyday/acceptance``).

The use case writes the proposed days into the program YAML, creates
missing weeks, validates the complete program, and returns a summary.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date, timedelta

import pytest

from runplan.application.everyday import (
    DAY_CONFLICT,
    DUPLICATE_WORKOUT_ID,
    UNKNOWN_PROGRAM,
    EverydayError,
    accept_horizon,
    horizon_from_payload,
    horizon_to_payload,
    propose_horizon,
)
from runplan.domain.everyday import EverydayProfile
from runplan.parsing.yaml_loader import load_program_model
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


def _propose_and_payload(start: date) -> tuple[InMemoryProgramRepository, dict]:
    repository = _repository()
    horizon = propose_horizon(
        program_id=PROGRAM_ID,
        profile=_profile(),
        goal="maintain",
        start_date=start,
        repository=repository,
    )
    return repository, horizon_to_payload(horizon)


# ---------------------------------------------------------------------------
# accept_horizon happy path
# ---------------------------------------------------------------------------


def test_accept_horizon_appends_weeks_to_program() -> None:
    start = date(2027, 1, 11)  # Monday after program week 2
    repository, payload = _propose_and_payload(start)
    horizon = horizon_from_payload(payload)

    result = accept_horizon(
        horizon,
        program_id=PROGRAM_ID,
        repository=repository,
    )

    raw = repository.load(PROGRAM_ID)
    week_numbers = sorted(week["week"] for week in raw["weeks"] if isinstance(week, dict))
    assert week_numbers == [1, 2, 3, 4]
    new_workouts = [workout for week in raw["weeks"][2:] for workout in week.get("workouts", [])]
    assert len(new_workouts) == len(horizon.days)
    assert {day.date for day in horizon.days} == {
        date.fromisoformat(workout["schedule_date"]) for workout in new_workouts
    }
    assert len(result.days) == len(horizon.days)


def test_accept_horizon_produces_valid_program() -> None:
    start = date(2027, 1, 11)
    repository, payload = _propose_and_payload(start)
    horizon = horizon_from_payload(payload)

    accept_horizon(
        horizon,
        program_id=PROGRAM_ID,
        repository=repository,
    )

    raw = repository.load(PROGRAM_ID)
    load_program_model(raw)  # raises if invalid


def test_accept_horizon_rejects_unknown_program() -> None:
    start = date(2027, 1, 11)
    repository, payload = _propose_and_payload(start)
    horizon = horizon_from_payload(payload)

    with pytest.raises(EverydayError) as exc:
        accept_horizon(
            horizon,
            program_id="missing",
            repository=repository,
        )
    assert exc.value.kind == UNKNOWN_PROGRAM


def test_accept_horizon_rejects_day_conflict() -> None:
    """Accepting twice into the same week+day must raise DAY_CONFLICT."""
    start = date(2027, 1, 11)
    repository, payload = _propose_and_payload(start)
    horizon = horizon_from_payload(payload)

    accept_horizon(
        horizon,
        program_id=PROGRAM_ID,
        repository=repository,
    )

    # Second acceptance of the same horizon collides with the first one
    with pytest.raises(EverydayError) as exc:
        accept_horizon(
            horizon,
            program_id=PROGRAM_ID,
            repository=repository,
        )
    assert exc.value.kind in {DAY_CONFLICT, DUPLICATE_WORKOUT_ID}


def test_accept_horizon_rejects_date_before_program_start() -> None:
    """A proposed date earlier than the program's start_week must raise INVALID_REQUEST."""
    start = date(2026, 12, 28)  # Monday of the existing program's week 1
    repository, payload = _propose_and_payload(start)
    horizon = horizon_from_payload(payload)

    # Mutate the horizon's first day to be before program start
    first_day = horizon.days[0]
    mutated = type(first_day)(
        date=first_day.date - timedelta(days=14),
        form=first_day.form,
        recipe_key=first_day.recipe_key,
        parameters=first_day.parameters,
        reasoning=first_day.reasoning,
        warnings=first_day.warnings,
    )
    bad_horizon = type(horizon)(
        profile=horizon.profile,
        goal=horizon.goal,
        start_date=horizon.start_date,
        horizon_days=horizon.horizon_days,
        days=(mutated, *horizon.days[1:]),
    )

    with pytest.raises(EverydayError) as exc:
        accept_horizon(
            bad_horizon,
            program_id=PROGRAM_ID,
            repository=repository,
        )
    assert exc.value.kind == "invalid_request"
