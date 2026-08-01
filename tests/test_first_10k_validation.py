from dataclasses import FrozenInstanceError, replace
from datetime import date, timedelta

import pytest

from runplan.domain.first_10k_blueprint import (
    WorkoutIntent,
    build_first_10k_outline,
)
from runplan.domain.first_10k_validation import validate_first_10k_candidate
from runplan.domain.generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    First10KGenerationInput,
    Pace,
    ProgressionProfile,
    RaceIntensity,
    TrainingAmount,
    Weekday,
    normalize_first_10k_input,
)
from runplan.domain.models import Program, Step
from runplan.parsing.yaml_loader import load_program_model

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)
BASE_TOTALS = (15.0, 16.5, 14.0, 13.0)


def generation_context(**changes: object):
    values = {
        "current_training": CurrentTraining(15, 3, TrainingAmount.distance_km(6)),
        "weekdays": (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        "long_run_day": Weekday.SUNDAY,
        "start_week": START,
        "duration_weeks": 4,
    }
    values.update(changes)
    inputs = normalize_first_10k_input(
        First10KGenerationInput(**values),  # type: ignore[arg-type]
        today=TODAY,
    )
    return inputs, build_first_10k_outline(inputs)


def _distances_for_week(outline_week, total_km: float) -> dict[str, float]:
    fixed: dict[str, float] = {}
    flexible = []
    long_slot = None
    for slot in outline_week.workouts:
        if slot.intent == WorkoutIntent.B_RACE:
            fixed[slot.stable_id] = slot.b_race.distance_km
        elif slot.intent in (WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN):
            fixed[slot.stable_id] = 10.0
        elif slot.intent == WorkoutIntent.LONG or (
            slot.club_session is not None and slot.club_session.kind == ClubSessionKind.LONG
        ):
            long_slot = slot
        else:
            flexible.append(slot)
    remaining = total_km - sum(fixed.values())
    if long_slot is not None:
        long_distance = min(total_km * 0.40, remaining)
        fixed[long_slot.stable_id] = long_distance
        remaining -= long_distance
    each = remaining / len(flexible) if flexible else 0
    fixed.update((slot.stable_id, each) for slot in flexible)
    return fixed


def candidate(outline, totals: tuple[float, ...] = BASE_TOTALS) -> Program:
    weeks = []
    for outline_week, total in zip(outline.weeks, totals, strict=True):
        distances = _distances_for_week(outline_week, total)
        workouts = [
            {
                "id": slot.stable_id,
                "day": int(slot.weekday),
                "name": slot.intent.value.title(),
                "steps": [{"run": {"distance": f"{distances[slot.stable_id]:g}km"}}],
            }
            for slot in outline_week.workouts
        ]
        weeks.append(
            {
                "week": outline_week.number,
                "focus": outline_week.phase.value,
                "workouts": workouts,
            }
        )
    return load_program_model(
        {
            "program": {
                "id": "generated-first-10k",
                "name": "Generated first 10K",
                "short_name": "First-10K",
                "start_week": "2026-W32",
            },
            "weeks": weeks,
        }
    )


def issue_codes(program, inputs, outline, **kwargs: object) -> set[str]:
    return {
        issue.code for issue in validate_first_10k_candidate(program, inputs, outline, **kwargs)
    }


def replace_workout(program: Program, workout_id: str, **changes: object) -> Program:
    weeks = []
    for week in program.weeks:
        workouts = tuple(
            replace(workout, **changes) if workout.id == workout_id else workout
            for workout in week.workouts
        )
        weeks.append(replace(week, workouts=workouts))
    return replace(program, weeks=tuple(weeks))


def set_distance(program: Program, workout_id: str, km: float) -> Program:
    return replace_workout(
        program,
        workout_id,
        steps=(Step(action="run", end_kind="distance", end_value=km * 1000),),
    )


def set_week_totals(program: Program, outline, totals: tuple[float, ...]) -> Program:
    result = program
    for outline_week, total in zip(outline.weeks, totals, strict=True):
        for workout_id, distance in _distances_for_week(outline_week, total).items():
            result = set_distance(result, workout_id, distance)
    return result


def test_valid_parsed_candidate_has_no_issues() -> None:
    inputs, outline = generation_context()

    issues = validate_first_10k_candidate(candidate(outline), inputs, outline)

    assert issues == ()


def test_issues_and_occurrences_are_immutable_and_machine_addressable() -> None:
    inputs, outline = generation_context()
    program = set_distance(candidate(outline), "w01-tue-easy", 1)

    issue = next(
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.code == "first_week_load_too_low"
    )

    assert issue.severity == "error"
    assert issue.occurrence.week_number == 1
    with pytest.raises(FrozenInstanceError):
        issue.code = "changed"  # type: ignore[misc]


def test_missing_and_extra_outline_occurrences_are_rejected() -> None:
    inputs, outline = generation_context()
    program = candidate(outline)
    first = program.weeks[0]
    missing = first.workouts[0]
    extra = replace(first.workouts[1], id="invented-workout")
    changed_week = replace(first, workouts=(extra, *first.workouts[2:]))
    program = replace(program, weeks=(changed_week, *program.weeks[1:]))

    issues = validate_first_10k_candidate(program, inputs, outline)

    assert {"outline_occurrence_missing", "outline_occurrence_extra"} <= {
        issue.code for issue in issues
    }
    missing_issue = next(issue for issue in issues if issue.code == "outline_occurrence_missing")
    assert missing_issue.occurrence.workout_id == missing.id
    assert missing_issue.occurrence.date == date(2026, 8, 4)


def test_altered_outline_day_and_date_are_rejected() -> None:
    inputs, outline = generation_context()
    program = replace_workout(
        candidate(outline),
        "w01-tue-easy",
        day=3,
        schedule_date=date(2026, 8, 5),
    )

    issues = validate_first_10k_candidate(program, inputs, outline)

    altered = next(issue for issue in issues if issue.code == "outline_occurrence_altered")
    assert altered.occurrence.day == 3
    assert altered.occurrence.date == date(2026, 8, 5)


def test_program_period_must_match_outline() -> None:
    inputs, outline = generation_context()
    program = candidate(outline)
    program = replace(program, start_date=START + timedelta(days=7), weeks=program.weeks[:-1])

    codes = issue_codes(program, inputs, outline)

    assert {"program_start_mismatch", "program_week_count_mismatch"} <= codes


@pytest.mark.parametrize(
    ("total", "code"),
    [(11.9, "first_week_load_too_low"), (16.6, "first_week_load_too_high")],
)
def test_first_week_must_be_80_to_110_percent_of_current_load(total: float, code: str) -> None:
    inputs, outline = generation_context()
    program = set_week_totals(candidate(outline), outline, (total, 16.5, 14, 13))

    assert code in issue_codes(program, inputs, outline)


def test_zero_volume_run_walk_start_uses_cautious_rules() -> None:
    inputs, outline = generation_context(
        current_training=CurrentTraining(0, 0, TrainingAmount.duration_minutes(20))
    )
    program = set_week_totals(candidate(outline), outline, (8, 9, 7.5, 12))
    first_id = outline.weeks[0].workouts[0].stable_id
    program = replace_workout(
        program,
        first_id,
        steps=(
            Step(action="run", end_kind="distance", end_value=2000),
            Step(action="recovery", end_kind="time", end_value=120),
        ),
    )

    issues = validate_first_10k_candidate(program, inputs, outline)

    assert "zero_current_load_cautious_start" in {issue.code for issue in issues}
    assert "zero_load_first_week_too_high" not in {issue.code for issue in issues}
    assert "zero_load_run_walk_not_explicit" not in {issue.code for issue in issues}


def test_zero_volume_start_rejects_excessive_week_and_workout_and_warns_without_walk() -> None:
    inputs, outline = generation_context(
        current_training=CurrentTraining(0, 0, TrainingAmount.distance_km(1))
    )
    program = set_week_totals(candidate(outline), outline, (12, 13, 11, 12))
    program = set_distance(program, "w01-sun-long", 6)

    codes = issue_codes(program, inputs, outline)

    assert {
        "zero_load_first_week_too_high",
        "zero_load_workout_too_long",
        "zero_load_run_walk_not_explicit",
    } <= codes


@pytest.mark.parametrize(
    ("profile", "second_total"),
    [
        (ProgressionProfile.CAUTIOUS, 16.1),
        (ProgressionProfile.BALANCED, 16.6),
        (ProgressionProfile.AMBITIOUS, 17.1),
    ],
)
def test_progression_profile_uses_larger_percentage_or_absolute_limit(
    profile: ProgressionProfile, second_total: float
) -> None:
    inputs, outline = generation_context(progression=profile)
    program = set_week_totals(candidate(outline), outline, (15, second_total, 14, 13))

    assert "weekly_progression_exceeded" in issue_codes(program, inputs, outline)


def test_four_consecutive_rising_weeks_are_rejected() -> None:
    inputs, outline = generation_context(duration_weeks=6)
    totals = (15.0, 15.5, 16.0, 16.5, 17.0, 13.0)
    program = candidate(outline, totals)

    assert "too_many_rising_weeks" in issue_codes(program, inputs, outline)


@pytest.mark.parametrize(
    ("consolidation_total", "code", "severity"),
    [
        (16.6, "consolidation_not_reduced", "error"),
        (15.5, "consolidation_reduction_outside_range", "warning"),
        (12.0, "consolidation_reduction_outside_range", "warning"),
    ],
)
def test_consolidation_reduction_policy_is_enforced(
    consolidation_total: float, code: str, severity: str
) -> None:
    inputs, outline = generation_context()
    program = set_week_totals(candidate(outline), outline, (15, 16.5, consolidation_total, 13))

    issue = next(
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.code == code
    )

    assert issue.severity == severity


def test_recovery_rebound_must_not_materially_exceed_prior_peak() -> None:
    inputs, outline = generation_context(duration_weeks=8)
    totals = (15.0, 16.0, 17.0, 14.5, 19.0, 19.5, 17.0, 13.0)
    program = candidate(outline, totals)

    assert "recovery_rebound_too_high" in issue_codes(program, inputs, outline)


def test_requested_weekly_and_long_run_maxima_are_hard_limits() -> None:
    inputs, outline = generation_context(maximum_weekly_km=14.5, maximum_long_run_km=5.5)

    codes = issue_codes(candidate(outline), inputs, outline)

    assert {"maximum_weekly_load_exceeded", "maximum_long_run_exceeded"} <= codes


def test_long_run_progression_uses_larger_of_10_percent_and_1km() -> None:
    inputs, outline = generation_context()
    program = set_distance(candidate(outline), "w02-sun-long", 7.1)

    assert "long_run_progression_exceeded" in issue_codes(program, inputs, outline)


@pytest.mark.parametrize(
    ("long_km", "severity"),
    [(8.0, "warning"), (14.0, "error")],
)
def test_long_run_share_has_advisory_and_extreme_policies(long_km: float, severity: str) -> None:
    inputs, outline = generation_context()
    program = set_distance(candidate(outline), "w01-sun-long", long_km)

    issue = next(
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.code == "long_run_share_high" and issue.occurrence.week_number == 1
    )

    assert issue.severity == severity


def test_multiple_quality_consumers_in_one_week_are_rejected_via_outline() -> None:
    races = (
        BRace(date(2026, 8, 4), 3, RaceIntensity.CONTROLLED),
        BRace(date(2026, 8, 6), 3, RaceIntensity.ALL_OUT),
    )
    inputs, outline = generation_context(b_races=races)
    program = candidate(outline)

    assert "quality_capacity_exceeded" in issue_codes(program, inputs, outline)


def test_optional_quality_must_not_exceed_requested_capacity() -> None:
    inputs, outline = generation_context()
    first_week = outline.weeks[0]
    quality_slot = replace(
        first_week.workouts[0],
        intent=WorkoutIntent.QUALITY,
        consumes_quality_capacity=True,
    )
    outline = replace(
        outline,
        weeks=(
            replace(first_week, workouts=(quality_slot, *first_week.workouts[1:])),
            *outline.weeks[1:],
        ),
    )
    program = candidate(outline)

    assert "quality_sessions_exceeded" in issue_codes(program, inputs, outline)


def test_adjacent_quality_consumers_are_rejected_via_outline() -> None:
    races = (
        BRace(date(2026, 8, 5), 3, RaceIntensity.CONTROLLED),
        BRace(date(2026, 8, 6), 3, RaceIntensity.ALL_OUT),
    )
    inputs, outline = generation_context(b_races=races)
    program = candidate(outline)

    assert "quality_workouts_adjacent" in issue_codes(program, inputs, outline)


def test_distance_based_club_amount_uses_ten_percent_with_half_km_floor() -> None:
    club = ClubSession(Weekday.THURSDAY, ClubSessionKind.EASY, TrainingAmount.distance_km(5))
    inputs, outline = generation_context(club_sessions=(club,))
    program = set_distance(candidate(outline), "w01-thu-club", 5.6)

    assert "club_amount_outside_tolerance" in issue_codes(program, inputs, outline)


def test_time_based_club_amount_compares_estimated_duration() -> None:
    club = ClubSession(
        Weekday.THURSDAY,
        ClubSessionKind.EASY,
        TrainingAmount.duration_minutes(30),
    )
    inputs, outline = generation_context(club_sessions=(club,))
    program = replace_workout(
        candidate(outline),
        "w01-thu-club",
        steps=(Step(action="run", end_kind="time", end_value=36 * 60),),
    )

    assert "club_amount_outside_tolerance" in issue_codes(program, inputs, outline)


def test_easy_pace_midpoint_overrides_fallback_for_time_based_distance_estimate() -> None:
    training = CurrentTraining(
        15,
        3,
        TrainingAmount.distance_km(6),
        easy_pace=Pace(290, 310),
    )
    inputs, outline = generation_context(current_training=training, maximum_weekly_km=15.5)
    program = replace_workout(
        candidate(outline),
        "w01-tue-easy",
        steps=(Step(action="run", end_kind="time", end_value=30 * 60),),
    )

    codes = issue_codes(
        program,
        inputs,
        outline,
        fallback_pace_seconds_per_km=600,
    )

    assert "maximum_weekly_load_exceeded" in codes


def test_fallback_pace_is_used_when_easy_pace_is_unknown() -> None:
    inputs, outline = generation_context(maximum_weekly_km=15.5)
    program = replace_workout(
        candidate(outline),
        "w01-tue-easy",
        steps=(Step(action="run", end_kind="time", end_value=30 * 60),),
    )

    codes = issue_codes(
        program,
        inputs,
        outline,
        fallback_pace_seconds_per_km=300,
    )

    assert "maximum_weekly_load_exceeded" in codes


def test_b_race_distance_must_match_input_exactly() -> None:
    race = BRace(date(2026, 8, 6), 5, RaceIntensity.TRAINING_RUN)
    inputs, outline = generation_context(b_races=(race,))
    program = set_distance(candidate(outline), "w01-thu-b-race", 5.01)

    assert "race_distance_mismatch" in issue_codes(program, inputs, outline)


def test_estimated_race_distance_is_not_treated_as_exact() -> None:
    race = BRace(date(2026, 8, 6), 5, RaceIntensity.TRAINING_RUN)
    inputs, outline = generation_context(b_races=(race,))
    program = replace_workout(
        candidate(outline),
        "w01-thu-b-race",
        steps=(Step(action="run", end_kind="time", end_value=30 * 60),),
    )

    assert "race_distance_approximate" in issue_codes(program, inputs, outline)


@pytest.mark.parametrize("main_race", [False, True])
def test_goal_race_and_test_run_must_be_exactly_10km(main_race: bool) -> None:
    changes = {"main_race_date": date(2026, 8, 30)} if main_race else {}
    inputs, outline = generation_context(**changes)
    race_slot = next(
        slot
        for slot in outline.weeks[-1].workouts
        if slot.intent in (WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN)
    )
    program = set_distance(candidate(outline), race_slot.stable_id, 9.9)

    assert "race_distance_mismatch" in issue_codes(program, inputs, outline)


def test_race_date_must_match_outline_date() -> None:
    inputs, outline = generation_context(main_race_date=date(2026, 8, 30))
    program = replace_workout(
        candidate(outline),
        "w04-sun-goal-race",
        day=6,
        schedule_date=date(2026, 8, 29),
    )

    codes = issue_codes(program, inputs, outline)

    assert {"outline_occurrence_altered", "race_date_mismatch"} <= codes


def test_goal_race_must_not_receive_structured_pace_target() -> None:
    inputs, outline = generation_context(main_race_date=date(2026, 8, 30))
    program = replace_workout(
        candidate(outline),
        "w04-sun-goal-race",
        steps=(
            Step(
                action="run",
                end_kind="distance",
                end_value=10_000,
                pace=(360, 390),
            ),
        ),
    )

    assert "goal_race_pace_target" in issue_codes(program, inputs, outline)


def test_invalid_fallback_pace_is_rejected_at_api_boundary() -> None:
    inputs, outline = generation_context()

    with pytest.raises(ValueError, match="fallback pace"):
        validate_first_10k_candidate(
            candidate(outline), inputs, outline, fallback_pace_seconds_per_km=0
        )
