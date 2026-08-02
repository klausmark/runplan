from datetime import date

from runplan.domain.estimates import estimate_steps
from runplan.domain.first_10k_blueprint import WorkoutIntent, build_first_10k_outline
from runplan.domain.first_10k_program import build_first_10k_program
from runplan.domain.first_10k_validation import validate_first_10k_candidate
from runplan.domain.generation_inputs import (
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    DurationMinutes,
    First10KGenerationInput,
    QualityPreference,
    TrainingAmount,
    TrainingStyle,
    Weekday,
    normalize_first_10k_input,
)

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)


def context(**changes: object):
    values = {
        "current_training": CurrentTraining(15, 3, TrainingAmount.distance_km(6)),
        "weekdays": (Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY),
        "long_run_day": Weekday.WEDNESDAY,
        "start_week": START,
        "duration_weeks": 12,
    }
    values.update(changes)
    inputs = normalize_first_10k_input(
        First10KGenerationInput(**values),  # type: ignore[arg-type]
        today=TODAY,
    )
    outline = build_first_10k_outline(inputs)
    return inputs, outline, build_first_10k_program(inputs, outline)


def test_mirielle_like_program_has_varied_build_workouts_and_valid_load() -> None:
    inputs, outline, program = context()

    issues = validate_first_10k_candidate(program, inputs, outline)
    quality = [
        workout
        for week, outline_week in zip(program.weeks, outline.weeks, strict=True)
        for workout, slot in zip(week.workouts, outline_week.workouts, strict=True)
        if slot.intent is WorkoutIntent.QUALITY
    ]

    assert not [issue for issue in issues if issue.severity == "error"]
    assert {workout.name for workout in quality} >= {
        "Controlled pickups",
        "Cruise intervals",
    }
    assert all(any(step.action == "repeat" for step in workout.steps) for workout in quality)
    assert program.weeks[-1].workouts[1].name == "10K completion run"


def test_zero_load_auto_style_starts_with_explicit_run_walk() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(0, 0, TrainingAmount.duration_minutes(20)),
        training_style=TrainingStyle.AUTO,
        quality_preference=QualityPreference.AUTO,
    )

    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]
    assert any(
        step.action == "repeat" and any(child.action == "recovery" for child in step.steps)
        for workout in program.weeks[0].workouts
        for step in workout.steps
    )


def test_recent_5k_adds_pace_only_to_quality_work_steps() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(
            18,
            3,
            TrainingAmount.distance_km(7),
            recent_5k_duration=DurationMinutes(28),
        )
    )

    paced = [
        child
        for week in program.weeks
        for workout in week.workouts
        for step in workout.steps
        for child in ((step,) if step.action != "repeat" else step.steps)
        if child.pace is not None
    ]

    assert paced
    assert all(step.action == "run" for step in paced)
    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_quality_can_be_disabled_explicitly() -> None:
    _, outline, _ = context(quality_preference=QualityPreference.NONE)

    assert not any(
        slot.intent is WorkoutIntent.QUALITY for week in outline.weeks for slot in week.workouts
    )


def test_first_long_run_respects_recent_long_run_progression() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(15, 3, TrainingAmount.distance_km(1))
    )
    long_index = next(
        index
        for index, slot in enumerate(outline.weeks[0].workouts)
        if slot.intent is WorkoutIntent.LONG
    )
    distance = estimate_steps(program.weeks[0].workouts[long_index].steps).distance_meters

    assert distance <= 2_001
    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_low_volume_runner_can_select_four_training_days() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(2, 2, TrainingAmount.distance_km(1)),
        weekdays=(Weekday.MONDAY, Weekday.WEDNESDAY, Weekday.FRIDAY, Weekday.SUNDAY),
        long_run_day=Weekday.SUNDAY,
    )

    assert len(program.weeks[0].workouts) == 4
    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_seven_day_plan_is_feasible_at_decimal_boundaries() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(30, 7, TrainingAmount.distance_km(10)),
        weekdays=tuple(Weekday),
        long_run_day=Weekday.SUNDAY,
    )

    assert len(program.weeks[-1].workouts) == 7
    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_duration_club_commitment_preserves_its_fractional_load_floor() -> None:
    club = ClubSession(
        Weekday.FRIDAY,
        ClubSessionKind.EASY,
        TrainingAmount.duration_minutes(61),
    )

    inputs, outline, program = context(
        current_training=CurrentTraining(13, 3, TrainingAmount.distance_km(5)),
        club_sessions=(club,),
    )

    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_zero_load_two_day_start_does_not_overload_one_workout() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(0, 0, TrainingAmount.distance_km(0.1)),
        weekdays=(Weekday.WEDNESDAY, Weekday.SUNDAY),
        long_run_day=Weekday.SUNDAY,
    )
    first_week_distances = [
        estimate_steps(workout.steps).distance_meters for workout in program.weeks[0].workouts
    ]

    assert max(first_week_distances) <= 5_001
    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_long_run_rounding_stays_below_progression_cap() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(30, 7, TrainingAmount.distance_km(5)),
        weekdays=tuple(Weekday),
        long_run_day=Weekday.SUNDAY,
        duration_weeks=16,
    )

    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]


def test_consolidation_can_retain_minimum_long_run_distance() -> None:
    inputs, outline, program = context(
        current_training=CurrentTraining(15, 3, TrainingAmount.distance_km(2)),
        maximum_long_run_km=2,
    )

    assert not [
        issue
        for issue in validate_first_10k_candidate(program, inputs, outline)
        if issue.severity == "error"
    ]
