from __future__ import annotations

from datetime import date

import pytest

from runplan import Program, Step, Workout, build_workout, load_program_model
from tests.helpers import normalized_program, program_data


def test_complete_program_loads_as_typed_recursive_models() -> None:
    program = load_program_model(program_data())

    assert isinstance(program, Program)
    assert program.short_name == "CHAR"
    assert program.start_date == date(2026, 12, 28)
    assert program.start_week == "2026-W53"
    assert tuple(week.number for week in program.weeks) == (1, 2)
    workout = program.week(1).workouts[0]
    assert isinstance(workout, Workout)
    repeat = workout.steps[1]
    assert isinstance(repeat, Step)
    assert repeat.action == "repeat"
    assert repeat.count == 2
    assert tuple(step.action for step in repeat.steps) == ("run", "recovery")
    assert repeat.steps[0].pace == (270, 285)


def test_typed_workout_produces_same_payload_as_normalized_workout() -> None:
    typed = load_program_model(program_data()).week(1).workouts[0]
    normalized = normalized_program(1)["workouts"][0]

    assert build_workout(typed).to_dict() == build_workout(normalized).to_dict()


def test_repeat_with_non_positive_count_is_rejected() -> None:
    with pytest.raises(ValueError, match="positive count"):
        Step(action="repeat", count=0, steps=())


def test_unknown_program_week_is_rejected_explicitly() -> None:
    program = load_program_model(program_data())

    with pytest.raises(KeyError, match="does not contain week 9"):
        program.week(9)


def test_workout_lifecycle_enrichment_returns_updated_copy() -> None:
    workout = load_program_model(program_data()).week(1).workouts[0]

    enriched = workout.with_lifecycle(
        {
            "status": "completed",
            "workout_id": 10,
            "schedule_id": 20,
            "activity_id": 30,
            "completed_at": "2026-12-28T12:00:00",
        }
    )

    assert workout.status == "planned"
    assert enriched.status == "completed"
    assert enriched.garmin_workout_id == 10
    assert enriched.garmin_schedule_id == 20
    assert enriched.activity_id == 30
