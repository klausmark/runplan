from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import pytest
import yaml

from runplan.application.generate_first_10k import (
    GenerateFirst10KProgram,
    InvalidGeneratedProgramError,
)
from runplan.domain.first_10k_blueprint import (
    First10KOutline,
    TrainingPhase,
    WorkoutIntent,
    build_first_10k_outline,
)
from runplan.domain.first_10k_validation import validate_first_10k_candidate
from runplan.domain.generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    DurationMinutes,
    First10KGenerationInput,
    Pace,
    ProgressionProfile,
    RaceIntensity,
    TrainingAmount,
    Weekday,
    normalize_first_10k_input,
)
from runplan.parsing.yaml_loader import load_program_model

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)
SENSITIVE_GUIDANCE = "Accommodate sensitive health constraint marker MEDICAL-NOTE-739."
API_LIKE_SECRET = "sk-minimax-evaluation-secret-4821"


@dataclass(frozen=True, slots=True)
class EvaluationScenario:
    name: str
    weekly_km: float
    weekdays: tuple[Weekday, ...]
    duration_weeks: int
    longest_run: TrainingAmount
    clubs: tuple[ClubSession, ...] = ()
    main_race: bool = False
    b_races: tuple[BRace, ...] = ()
    pace: Pace | None = None
    recent_5k_minutes: float | None = None
    maximum_weekly_km: float | None = None
    maximum_long_run_km: float | None = None
    progression: ProgressionProfile = ProgressionProfile.BALANCED
    quality_sessions: int = 0
    guidance: str | None = None
    output: str = "valid"

    def request(self) -> First10KGenerationInput:
        race_date = START + timedelta(weeks=self.duration_weeks, days=-1)
        return First10KGenerationInput(
            current_training=CurrentTraining(
                self.weekly_km,
                min(len(self.weekdays), 5),
                self.longest_run,
                recent_5k_duration=(
                    None
                    if self.recent_5k_minutes is None
                    else DurationMinutes(self.recent_5k_minutes)
                ),
                easy_pace=self.pace,
            ),
            weekdays=self.weekdays,
            long_run_day=self.weekdays[-1],
            main_race_date=race_date if self.main_race else None,
            club_sessions=self.clubs,
            b_races=self.b_races,
            start_week=START,
            duration_weeks=self.duration_weeks,
            maximum_weekly_km=self.maximum_weekly_km,
            maximum_long_run_km=self.maximum_long_run_km,
            progression=self.progression,
            quality_sessions_per_week=self.quality_sessions,
            additional_instructions=self.guidance,
        )


def club(day: Weekday, kind: ClubSessionKind, km: float) -> ClubSession:
    return ClubSession(day, kind, TrainingAmount.distance_km(km), f"Usual {kind.value} group")


SCENARIOS = (
    EvaluationScenario(
        "zero-two-days-four-weeks-consecutive",
        0,
        (Weekday.MONDAY, Weekday.TUESDAY),
        4,
        TrainingAmount.duration_minutes(20),
        output="warning",
    ),
    EvaluationScenario(
        "low-easy-club-eight-week-race",
        9,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        8,
        TrainingAmount.distance_km(4),
        clubs=(club(Weekday.THURSDAY, ClubSessionKind.EASY, 3),),
        main_race=True,
        output="repair",
    ),
    EvaluationScenario(
        "low-long-club-twelve-weeks-no-race",
        12,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        12,
        TrainingAmount.distance_km(5),
        clubs=(club(Weekday.SUNDAY, ClubSessionKind.LONG, 4),),
    ),
    EvaluationScenario(
        "moderate-quality-club-sixteen-week-race-known-pace",
        18,
        (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY, Weekday.SUNDAY),
        16,
        TrainingAmount.duration_minutes(65),
        clubs=(club(Weekday.WEDNESDAY, ClubSessionKind.QUALITY, 4),),
        main_race=True,
        pace=Pace(350, 380),
        recent_5k_minutes=28,
        quality_sessions=1,
    ),
    EvaluationScenario(
        "moderate-unknown-club-twenty-weeks-no-race",
        22,
        (
            Weekday.MONDAY,
            Weekday.TUESDAY,
            Weekday.THURSDAY,
            Weekday.SATURDAY,
            Weekday.SUNDAY,
        ),
        20,
        TrainingAmount.distance_km(8),
        clubs=(club(Weekday.THURSDAY, ClubSessionKind.UNKNOWN, 4),),
        quality_sessions=1,
    ),
    EvaluationScenario(
        "strict-maxima-four-weeks",
        10,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        4,
        TrainingAmount.distance_km(4),
        maximum_weekly_km=12,
        maximum_long_run_km=3.5,
        progression=ProgressionProfile.CAUTIOUS,
    ),
    EvaluationScenario(
        "controlled-b-race-eight-weeks",
        15,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        8,
        TrainingAmount.distance_km(6),
        b_races=(BRace(date(2026, 8, 16), 5, RaceIntensity.CONTROLLED, "Tune-up event"),),
        quality_sessions=1,
    ),
    EvaluationScenario(
        "training-b-race-twelve-weeks-known-result",
        16,
        (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY, Weekday.SUNDAY),
        12,
        TrainingAmount.distance_km(6),
        b_races=(BRace(date(2026, 8, 22), 6, RaceIntensity.TRAINING_RUN),),
        recent_5k_minutes=30,
    ),
    EvaluationScenario(
        "all-out-b-race-sixteen-weeks",
        17,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SATURDAY),
        16,
        TrainingAmount.distance_km(7),
        b_races=(BRace(date(2026, 8, 23), 5, RaceIntensity.ALL_OUT),),
        quality_sessions=1,
    ),
    EvaluationScenario(
        "duration-club-eight-weeks",
        15,
        (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.SUNDAY),
        8,
        TrainingAmount.duration_minutes(55),
        clubs=(
            ClubSession(
                Weekday.WEDNESDAY,
                ClubSessionKind.EASY,
                TrainingAmount.duration_minutes(30),
                "Social group",
            ),
        ),
    ),
    EvaluationScenario(
        "private-guidance-twelve-weeks",
        14,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        12,
        TrainingAmount.distance_km(5),
        guidance=SENSITIVE_GUIDANCE,
        output="repair",
    ),
    EvaluationScenario(
        "terminal-invalid-sixteen-weeks",
        20,
        (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY, Weekday.SUNDAY),
        16,
        TrainingAmount.distance_km(8),
        main_race=True,
        guidance=SENSITIVE_GUIDANCE,
        output="error",
    ),
)


class FakeGenerator:
    configured = True

    def __init__(self, *responses: str) -> None:
        self.responses = list(responses)
        self.prompts: list[str] = []

    def generate(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return self.responses.pop(0)


def _estimated_club_km(slot, pace_seconds_per_km: float) -> float:
    amount = slot.club_session.amount
    if amount.kind.value == "distance_km":
        return amount.value
    return amount.value * 60 / pace_seconds_per_km


def candidate_yaml(inputs, outline: First10KOutline) -> str:
    pace = inputs.current_training.easy_pace
    pace_seconds = (
        360 if pace is None else (pace.fast_seconds_per_km + pace.slow_seconds_per_km) / 2
    )
    previous_total = (
        6.0
        if inputs.current_training.average_weekly_km == 0
        else inputs.current_training.average_weekly_km
    )
    weeks = []
    for outline_week in outline.weeks:
        target = (
            previous_total * 0.85
            if outline_week.phase is TrainingPhase.CONSOLIDATION
            else previous_total
        )
        fixed: dict[str, float] = {}
        flexible = []
        long_slot = None
        for slot in outline_week.workouts:
            if slot.intent == WorkoutIntent.B_RACE:
                fixed[slot.stable_id] = slot.b_race.distance_km
            elif slot.intent in (WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN):
                fixed[slot.stable_id] = 10
            elif slot.club_session is not None:
                fixed[slot.stable_id] = _estimated_club_km(slot, pace_seconds)
                if slot.club_session.kind is ClubSessionKind.LONG:
                    long_slot = slot
            elif slot.intent is WorkoutIntent.LONG:
                long_slot = slot
            else:
                flexible.append(slot)

        minimum = sum(fixed.values()) + 0.5 * len(flexible)
        if long_slot is not None and long_slot.stable_id not in fixed:
            long_km = min(
                target * 0.4,
                inputs.maximum_long_run_km or target * 0.4,
            )
            fixed[long_slot.stable_id] = long_km
            minimum += long_km
        elif long_slot is not None:
            minimum = max(minimum, fixed[long_slot.stable_id] / 0.59)
        target = max(target, minimum)
        remaining = target - sum(fixed.values())
        each = remaining / len(flexible) if flexible else 0
        fixed.update((slot.stable_id, each) for slot in flexible)

        workouts = []
        for slot in outline_week.workouts:
            if (
                slot.club_session is not None
                and slot.club_session.amount.kind.value == "duration_minutes"
            ):
                steps = [{"run": {"time": f"{slot.club_session.amount.value:g}m"}}]
            else:
                distance = fixed[slot.stable_id]
                if inputs.current_training.average_weekly_km == 0 and outline_week.number == 1:
                    steps = [
                        {"run": {"distance": f"{distance - 0.1:g}km"}},
                        {"recovery": {"distance": "0.1km"}},
                    ]
                else:
                    steps = [{"run": {"distance": f"{distance:g}km"}}]
            workouts.append(
                {
                    "id": slot.stable_id,
                    "day": int(slot.weekday),
                    "name": slot.intent.value.title(),
                    "steps": steps,
                }
            )
        weeks.append(
            {"week": outline_week.number, "focus": outline_week.phase.value, "workouts": workouts}
        )
        previous_total = target

    iso_year, iso_week, _ = inputs.period.start_week.isocalendar()
    return yaml.safe_dump(
        {
            "program": {
                "id": "evaluation-first-10k",
                "name": "First 10K evaluation",
                "short_name": "Eval-10K",
                "start_week": f"{iso_year}-W{iso_week:02d}",
            },
            "weeks": weeks,
        },
        sort_keys=False,
    )


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_evaluation_scenarios_cover_pipeline_without_persistence(
    scenario: EvaluationScenario, monkeypatch: pytest.MonkeyPatch
) -> None:
    request = scenario.request()
    inputs = normalize_first_10k_input(request, today=TODAY)
    outline = build_first_10k_outline(inputs)
    valid = candidate_yaml(inputs, outline)
    parsed = load_program_model(yaml.safe_load(valid))

    assert len(outline.weeks) == scenario.duration_weeks
    assert not [
        issue
        for issue in validate_first_10k_candidate(parsed, inputs, outline)
        if issue.severity == "error"
    ]

    def reject_write(*args: object, **kwargs: object) -> int:
        raise AssertionError("evaluation generation must not persist")

    monkeypatch.setattr(Path, "write_text", reject_write)
    invalid = "program: [private malformed candidate"
    responses = {
        "valid": (valid,),
        "warning": (valid,),
        "repair": (invalid, valid),
        "error": (invalid, invalid),
    }[scenario.output]
    generator = FakeGenerator(*responses)

    if scenario.output == "error":
        with pytest.raises(InvalidGeneratedProgramError) as caught:
            GenerateFirst10KProgram(generator).generate(request, today=TODAY)
        assert caught.value.attempt_count == 2
        assert SENSITIVE_GUIDANCE not in str(caught.value)
        assert API_LIKE_SECRET not in str(caught.value)
        assert all(SENSITIVE_GUIDANCE not in item.message for item in caught.value.diagnostics)
    else:
        draft = GenerateFirst10KProgram(generator).generate(request, today=TODAY)
        assert draft.summary.weeks == scenario.duration_weeks
        assert draft.attempt_count == (2 if scenario.output == "repair" else 1)
        if scenario.output == "warning":
            assert draft.warnings

    first_prompt = generator.prompts[0]
    assert API_LIKE_SECRET not in first_prompt
    if scenario.guidance is not None:
        assert scenario.guidance in first_prompt
    if len(generator.prompts) == 2:
        assert API_LIKE_SECRET not in generator.prompts[1]


def test_evaluation_matrix_covers_roadmap_dimensions() -> None:
    assert len(SCENARIOS) == 12
    assert {scenario.duration_weeks for scenario in SCENARIOS} >= {4, 8, 12, 16, 20}
    assert {len(scenario.weekdays) for scenario in SCENARIOS} >= {2, 3, 4, 5}
    assert {club.kind for scenario in SCENARIOS for club in scenario.clubs} == set(ClubSessionKind)
    assert {race.intensity for scenario in SCENARIOS for race in scenario.b_races} == set(
        RaceIntensity
    )
    assert {scenario.output for scenario in SCENARIOS} == {"valid", "warning", "repair", "error"}
    assert any(scenario.weekly_km == 0 for scenario in SCENARIOS)
    assert any(0 < scenario.weekly_km < 10 for scenario in SCENARIOS)
    assert any(scenario.weekly_km >= 15 for scenario in SCENARIOS)
    assert any(scenario.main_race for scenario in SCENARIOS)
    assert any(not scenario.main_race for scenario in SCENARIOS)
    assert any(scenario.pace is not None for scenario in SCENARIOS)
    assert any(scenario.pace is None for scenario in SCENARIOS)
    assert any(
        scenario.maximum_weekly_km is not None and scenario.maximum_long_run_km is not None
        for scenario in SCENARIOS
    )
