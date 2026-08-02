from dataclasses import FrozenInstanceError, replace
from datetime import date
from pathlib import Path

import pytest
import yaml

from runplan.application.generate_first_10k import (
    GenerateFirst10KProgram,
    InvalidGeneratedProgramError,
)
from runplan.domain.first_10k_loads import First10KPlanInfeasibleError
from runplan.domain.generation_inputs import (
    CurrentTraining,
    First10KGenerationInput,
    TrainingAmount,
    Weekday,
)
from runplan.parsing.yaml_loader import load_program_model

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)


def request(**changes: object) -> First10KGenerationInput:
    values = {
        "current_training": CurrentTraining(15, 3, TrainingAmount.distance_km(6)),
        "weekdays": (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        "long_run_day": Weekday.SUNDAY,
        "start_week": START,
        "duration_weeks": 4,
    }
    values.update(changes)
    return First10KGenerationInput(**values)  # type: ignore[arg-type]


def test_generation_is_deterministic_and_round_trips() -> None:
    use_case = GenerateFirst10KProgram()

    first = use_case.generate(request(), today=TODAY)
    second = use_case.generate(request(), today=TODAY)
    program = load_program_model(yaml.safe_load(first.content))

    assert first == second
    assert first.filename == "first-10k-2026-08-03.yaml"
    assert first.summary.weeks == 4
    assert first.summary.workouts == 12
    assert first.attempt_count == 1
    assert program.id == "first-10k-2026-08-03"
    assert "tracking:" not in first.content
    with pytest.raises(FrozenInstanceError):
        first.attempt_count = 2  # type: ignore[misc]


def test_generation_does_not_persist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_write(*args: object, **kwargs: object) -> int:
        raise AssertionError("generation must not persist")

    monkeypatch.setattr(Path, "write_text", reject_write)

    GenerateFirst10KProgram().generate(request(), today=TODAY)


def test_input_warnings_are_returned_with_the_draft() -> None:
    draft = GenerateFirst10KProgram().generate(
        request(
            weekdays=(Weekday.MONDAY, Weekday.TUESDAY),
            long_run_day=Weekday.TUESDAY,
        ),
        today=TODAY,
    )

    assert {warning.code for warning in draft.warnings} == {"input_warning"}
    assert any("Three or four" in warning.message for warning in draft.warnings)
    assert any("consecutive" in warning.message for warning in draft.warnings)


def test_infeasible_maximum_is_reported_before_a_draft() -> None:
    with pytest.raises(First10KPlanInfeasibleError, match="maximum weekly distance"):
        GenerateFirst10KProgram().generate(request(maximum_weekly_km=9), today=TODAY)


def test_conflicting_recent_and_minimum_long_run_is_reported_as_infeasible() -> None:
    training = CurrentTraining(15, 3, TrainingAmount.distance_km(0.1))

    with pytest.raises(First10KPlanInfeasibleError, match="minimum safe workout distance"):
        GenerateFirst10KProgram().generate(
            request(current_training=training),
            today=TODAY,
        )


def test_algorithm_validation_failure_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import runplan.application.generate_first_10k as generation

    original = generation.build_first_10k_program

    def wrong_program(inputs, outline):
        program = original(inputs, outline)
        return replace(program, start_date=date(2027, 1, 1))

    monkeypatch.setattr(generation, "build_first_10k_program", wrong_program)

    with pytest.raises(InvalidGeneratedProgramError) as caught:
        GenerateFirst10KProgram().generate(request(), today=TODAY)

    assert {item.code for item in caught.value.diagnostics} == {"program_start_mismatch"}
    assert caught.value.attempt_count == 1
