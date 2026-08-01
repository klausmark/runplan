from dataclasses import FrozenInstanceError
from datetime import date
from pathlib import Path

import pytest
import yaml

from runplan.application.generate_first_10k import (
    MAX_GENERATED_YAML_BYTES,
    GenerateFirst10KProgram,
    InvalidGeneratedProgramError,
)
from runplan.domain.first_10k_blueprint import WorkoutIntent, build_first_10k_outline
from runplan.domain.generation_inputs import (
    CurrentTraining,
    First10KGenerationInput,
    TrainingAmount,
    Weekday,
    normalize_first_10k_input,
)

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)
TOTALS = (15.0, 16.5, 14.0, 13.0)


class FakeGenerator:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        assert isinstance(response, str)
        return response


def request() -> First10KGenerationInput:
    return First10KGenerationInput(
        current_training=CurrentTraining(15, 3, TrainingAmount.distance_km(6)),
        weekdays=(Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        long_run_day=Weekday.SUNDAY,
        start_week=START,
        duration_weeks=4,
    )


def candidate_yaml(
    *,
    totals: tuple[float, ...] = TOTALS,
    remove_first_workout: bool = False,
    tracking: bool = False,
) -> str:
    inputs = normalize_first_10k_input(request(), today=TODAY)
    outline = build_first_10k_outline(inputs)
    weeks = []
    for outline_week, total in zip(outline.weeks, totals, strict=True):
        fixed = {
            slot.stable_id: 10.0
            for slot in outline_week.workouts
            if slot.intent in (WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN)
        }
        long_slot = next(
            (slot for slot in outline_week.workouts if slot.intent == WorkoutIntent.LONG), None
        )
        remaining = total - sum(fixed.values())
        if long_slot is not None:
            fixed[long_slot.stable_id] = total * 0.40
            remaining -= total * 0.40
        flexible = [slot for slot in outline_week.workouts if slot.stable_id not in fixed]
        fixed.update((slot.stable_id, remaining / len(flexible)) for slot in flexible)
        workouts = [
            {
                "id": slot.stable_id,
                "day": int(slot.weekday),
                "name": slot.intent.value.title(),
                "steps": [{"run": {"distance": f"{fixed[slot.stable_id]:g}km"}}],
            }
            for slot in outline_week.workouts
        ]
        weeks.append(
            {"week": outline_week.number, "focus": outline_week.phase.value, "workouts": workouts}
        )
    if remove_first_workout:
        weeks[0]["workouts"].pop(0)
    if tracking:
        weeks[0]["workouts"][0]["tracking"] = {"status": "planned"}
    raw = {
        "program": {
            "id": "first-10k-2026-08-03",
            "name": "Complete Your First 10K",
            "short_name": "First-10K",
            "description": "A progressive first 10K program.",
            "start_week": "2026-W32",
        },
        "weeks": weeks,
    }
    return yaml.safe_dump(raw, sort_keys=False)


def test_first_candidate_success_has_deterministic_metadata_and_complete_prompt() -> None:
    generator = FakeGenerator(candidate_yaml())

    draft = GenerateFirst10KProgram(generator).generate(request(), today=TODAY)

    assert draft.filename == "first-10k-2026-08-03.yaml"
    assert draft.summary.weeks == 4
    assert draft.summary.workouts == 12
    assert draft.attempt_count == 1
    assert draft.warnings == ()
    assert draft.content.startswith("program:")
    assert len(generator.prompts) == 1
    prompt = generator.prompts[0]
    assert "Blueprint: id=complete-first-10k; version=1" in prompt
    assert "Root has exactly program and weeks" in prompt
    assert "never add tracking or workout-type fields" in prompt
    assert "short_name is 2-10 ASCII" in prompt
    assert "Never invent concrete pace" in prompt
    assert "Never put pace on warmup, cooldown, recovery, easy runs" in prompt
    assert "Do not repeat medical, health, or other private details" in prompt
    assert "date=2026-08-04; day=2; id=w01-tue-easy; intent=easy; source=blueprint" in prompt
    with pytest.raises(FrozenInstanceError):
        draft.attempt_count = 3  # type: ignore[misc]


def test_one_surrounding_yaml_fence_is_removed() -> None:
    content = candidate_yaml()
    generator = FakeGenerator(f"```yaml\n{content}```")

    draft = GenerateFirst10KProgram(generator).generate(request(), today=TODAY)

    assert draft.content == content
    assert "```" not in draft.content


def test_warning_only_candidate_does_not_trigger_repair() -> None:
    generator = FakeGenerator(candidate_yaml(totals=(15.0, 16.5, 14.0, 13.0)))
    content = candidate_yaml()
    # Long-run share above 45%, but below the 60% error threshold.
    raw = yaml.safe_load(content)
    for week in raw["weeks"][:3]:
        long_run = week["workouts"][-1]
        total = TOTALS[week["week"] - 1]
        old_long = float(long_run["steps"][0]["run"]["distance"][:-2])
        increase = total * 0.10
        long_run["steps"][0]["run"]["distance"] = f"{old_long + increase:g}km"
        week["workouts"][0]["steps"][0]["run"]["distance"] = (
            f"{float(week['workouts'][0]['steps'][0]['run']['distance'][:-2]) - increase:g}km"
        )
    generator.responses[0] = yaml.safe_dump(raw, sort_keys=False)

    draft = GenerateFirst10KProgram(generator).generate(request(), today=TODAY)

    assert draft.attempt_count == 1
    assert len(generator.prompts) == 1
    assert {warning.code for warning in draft.warnings} == {"long_run_share_high"}


def test_invalid_candidate_is_repaired_exactly_once() -> None:
    invalid = candidate_yaml(remove_first_workout=True)
    generator = FakeGenerator(invalid, candidate_yaml())

    draft = GenerateFirst10KProgram(generator).generate(request(), today=TODAY)

    assert draft.attempt_count == 2
    assert len(generator.prompts) == 2
    repair = generator.prompts[1]
    assert "ORIGINAL REQUIREMENTS" in repair
    assert "Normalized runner constraints" in repair
    assert "outline_occurrence_missing" in repair
    assert invalid in repair


def test_generation_reports_real_progress_phases_in_order() -> None:
    invalid = candidate_yaml(remove_first_workout=True)
    phases: list[str] = []

    GenerateFirst10KProgram(FakeGenerator(invalid, candidate_yaml())).generate(
        request(), today=TODAY, progress=phases.append
    )

    assert phases == ["preparing", "generating", "validating", "repairing", "validating"]


def test_repeated_invalid_candidate_raises_editable_bounded_error() -> None:
    invalid = candidate_yaml(remove_first_workout=True)
    generator = FakeGenerator(invalid, invalid)

    with pytest.raises(InvalidGeneratedProgramError) as caught:
        GenerateFirst10KProgram(generator).generate(request(), today=TODAY)

    error = caught.value
    assert error.candidate == invalid
    assert error.attempt_count == 2
    assert {item.code for item in error.diagnostics} >= {"outline_occurrence_missing"}
    assert any(item.severity == "error" for item in error.diagnostics)
    assert len(generator.prompts) == 2


@pytest.mark.parametrize(
    ("response", "code"),
    [
        ("program: [", "candidate_parse_error"),
        ("Here is your program.", "candidate_contract_error"),
        ("```yaml\nprogram: {}\n```\n```yaml\nweeks: []\n```", "candidate_contract_error"),
        (candidate_yaml(tracking=True), "candidate_contract_error"),
        ("", "candidate_empty"),
        ("x" * (MAX_GENERATED_YAML_BYTES + 1), "candidate_too_large"),
    ],
    ids=["malformed", "prose", "multiple-fences", "tracking", "empty", "oversized"],
)
def test_invalid_output_forms_are_rejected_and_repaired_once(response: str, code: str) -> None:
    generator = FakeGenerator(response, response)

    with pytest.raises(InvalidGeneratedProgramError) as caught:
        GenerateFirst10KProgram(generator).generate(request(), today=TODAY)

    assert caught.value.diagnostics[0].code == code
    assert len(caught.value.candidate.encode("utf-8")) <= MAX_GENERATED_YAML_BYTES
    assert len(generator.prompts) == 2


def test_generation_does_not_write_to_the_filesystem(monkeypatch: pytest.MonkeyPatch) -> None:
    def reject_write(*args: object, **kwargs: object) -> int:
        raise AssertionError("generation must not write files")

    monkeypatch.setattr(Path, "write_text", reject_write)
    GenerateFirst10KProgram(FakeGenerator(candidate_yaml())).generate(request(), today=TODAY)


class ProviderFailure(RuntimeError):
    pass


def test_first_provider_error_propagates_unchanged() -> None:
    failure = ProviderFailure("provider unavailable")

    with pytest.raises(ProviderFailure) as caught:
        GenerateFirst10KProgram(FakeGenerator(failure)).generate(request(), today=TODAY)

    assert caught.value is failure


def test_repair_provider_error_propagates_unchanged() -> None:
    failure = ProviderFailure("provider unavailable during repair")

    with pytest.raises(ProviderFailure) as caught:
        GenerateFirst10KProgram(
            FakeGenerator(candidate_yaml(remove_first_workout=True), failure)
        ).generate(request(), today=TODAY)

    assert caught.value is failure
