from dataclasses import dataclass
from datetime import date, timedelta

import pytest
import yaml

from runplan.application.generate_first_10k import GenerateFirst10KProgram
from runplan.domain.first_10k_loads import First10KPlanInfeasibleError
from runplan.domain.generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    DurationMinutes,
    First10KGenerationInput,
    Pace,
    ProgressionProfile,
    QualityPreference,
    RaceIntensity,
    TrainingAmount,
    TrainingStyle,
    Weekday,
)
from runplan.parsing.yaml_loader import load_program_model

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)


@dataclass(frozen=True, slots=True)
class Scenario:
    name: str
    weekly_km: float
    weekdays: tuple[Weekday, ...]
    weeks: int
    longest_km: float
    clubs: tuple[ClubSession, ...] = ()
    races: tuple[BRace, ...] = ()
    main_race: bool = False
    progression: ProgressionProfile = ProgressionProfile.BALANCED
    style: TrainingStyle = TrainingStyle.AUTO
    quality: QualityPreference = QualityPreference.AUTO
    recent_5k: float | None = None
    easy_pace: Pace | None = None
    maximum_weekly_km: float | None = None
    maximum_long_run_km: float | None = None
    feasible: bool = True

    def request(self) -> First10KGenerationInput:
        race_date = START + timedelta(weeks=self.weeks, days=-1)
        return First10KGenerationInput(
            current_training=CurrentTraining(
                self.weekly_km,
                min(len(self.weekdays), 5),
                TrainingAmount.distance_km(self.longest_km),
                recent_5k_duration=(
                    None if self.recent_5k is None else DurationMinutes(self.recent_5k)
                ),
                easy_pace=self.easy_pace,
            ),
            weekdays=self.weekdays,
            long_run_day=self.weekdays[-1],
            main_race_date=race_date if self.main_race else None,
            club_sessions=self.clubs,
            b_races=self.races,
            start_week=START,
            duration_weeks=self.weeks,
            maximum_weekly_km=self.maximum_weekly_km,
            maximum_long_run_km=self.maximum_long_run_km,
            progression=self.progression,
            training_style=self.style,
            quality_preference=self.quality,
        )


def club(day: Weekday, kind: ClubSessionKind, km: float) -> ClubSession:
    return ClubSession(day, kind, TrainingAmount.distance_km(km))


SCENARIOS = (
    Scenario(
        "zero-two-days-run-walk",
        0,
        (Weekday.MONDAY, Weekday.THURSDAY),
        4,
        2,
        style=TrainingStyle.RUN_WALK,
    ),
    Scenario(
        "low-three-days-easy-club-race",
        9,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        8,
        4,
        clubs=(club(Weekday.THURSDAY, ClubSessionKind.EASY, 3),),
        main_race=True,
    ),
    Scenario(
        "long-club-no-race",
        15,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        12,
        6,
        clubs=(club(Weekday.SUNDAY, ClubSessionKind.LONG, 6),),
    ),
    Scenario(
        "quality-club-known-pace",
        20,
        (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY, Weekday.SUNDAY),
        16,
        8,
        clubs=(club(Weekday.WEDNESDAY, ClubSessionKind.QUALITY, 5),),
        recent_5k=28,
        easy_pace=Pace(360, 390),
        main_race=True,
    ),
    Scenario(
        "unknown-club-five-days",
        25,
        (
            Weekday.MONDAY,
            Weekday.TUESDAY,
            Weekday.THURSDAY,
            Weekday.SATURDAY,
            Weekday.SUNDAY,
        ),
        20,
        9,
        clubs=(club(Weekday.THURSDAY, ClubSessionKind.UNKNOWN, 5),),
    ),
    Scenario(
        "controlled-b-race",
        16,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        8,
        6,
        races=(BRace(date(2026, 8, 16), 5, RaceIntensity.CONTROLLED),),
    ),
    Scenario(
        "training-b-race-cautious",
        18,
        (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY, Weekday.SUNDAY),
        12,
        7,
        races=(BRace(date(2026, 8, 22), 6, RaceIntensity.TRAINING_RUN),),
        progression=ProgressionProfile.CAUTIOUS,
    ),
    Scenario(
        "all-out-b-race-ambitious",
        18,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SATURDAY),
        16,
        7,
        races=(BRace(date(2026, 8, 23), 5, RaceIntensity.ALL_OUT),),
        progression=ProgressionProfile.AMBITIOUS,
    ),
    Scenario(
        "strict-impossible-final-maximum",
        10,
        (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        4,
        4,
        maximum_weekly_km=12,
        maximum_long_run_km=3.5,
        feasible=False,
    ),
)


@pytest.mark.parametrize("scenario", SCENARIOS, ids=lambda scenario: scenario.name)
def test_evaluation_matrix_produces_local_valid_programs(scenario: Scenario) -> None:
    if not scenario.feasible:
        with pytest.raises(First10KPlanInfeasibleError):
            GenerateFirst10KProgram().generate(scenario.request(), today=TODAY)
        return

    first = GenerateFirst10KProgram().generate(scenario.request(), today=TODAY)
    second = GenerateFirst10KProgram().generate(scenario.request(), today=TODAY)
    parsed = load_program_model(yaml.safe_load(first.content))

    assert first.content == second.content
    assert len(parsed.weeks) == scenario.weeks
    assert first.attempt_count == 1


def test_evaluation_matrix_covers_algorithm_dimensions() -> None:
    assert {scenario.weeks for scenario in SCENARIOS} >= {4, 8, 12, 16, 20}
    assert {len(scenario.weekdays) for scenario in SCENARIOS} >= {2, 3, 4, 5}
    assert {session.kind for scenario in SCENARIOS for session in scenario.clubs} == set(
        ClubSessionKind
    )
    assert {race.intensity for scenario in SCENARIOS for race in scenario.races} == set(
        RaceIntensity
    )
    assert {scenario.progression for scenario in SCENARIOS} == set(ProgressionProfile)
    assert any(scenario.weekly_km == 0 for scenario in SCENARIOS)
    assert any(not scenario.feasible for scenario in SCENARIOS)
