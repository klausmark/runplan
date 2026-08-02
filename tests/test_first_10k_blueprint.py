from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from runplan.domain.first_10k_blueprint import (
    FIRST_10K_BLUEPRINT,
    TrainingPhase,
    WorkoutIntent,
    WorkoutSource,
    build_first_10k_outline,
)
from runplan.domain.generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    First10KGenerationInput,
    RaceIntensity,
    TrainingAmount,
    Weekday,
    normalize_first_10k_input,
)

TODAY = date(2026, 8, 1)
START = date(2026, 8, 3)


def outline(**changes: object):
    values = {
        "current_training": CurrentTraining(12, 3, TrainingAmount.distance_km(6)),
        "weekdays": (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
        "long_run_day": Weekday.SUNDAY,
        "start_week": START,
        "duration_weeks": 4,
    }
    values.update(changes)
    normalized = normalize_first_10k_input(
        First10KGenerationInput(**values),  # type: ignore[arg-type]
        today=TODAY,
    )
    return build_first_10k_outline(normalized)


def slot_on(program_outline, scheduled_date: date):
    return next(
        slot
        for week in program_outline.weeks
        for slot in week.workouts
        if slot.date == scheduled_date
    )


def test_blueprint_and_outline_values_are_versioned_and_immutable() -> None:
    program_outline = outline()

    assert program_outline.blueprint is FIRST_10K_BLUEPRINT
    assert program_outline.blueprint.blueprint_id == "complete-first-10k"
    assert program_outline.blueprint.version == 2
    with pytest.raises(FrozenInstanceError):
        program_outline.weeks[0].number = 2  # type: ignore[misc]


@pytest.mark.parametrize("day_count", range(2, 8))
def test_outline_contains_every_selected_weekday_for_two_to_seven_days(day_count: int) -> None:
    weekdays = tuple(Weekday(day) for day in range(1, day_count + 1))
    program_outline = outline(weekdays=weekdays, long_run_day=weekdays[-1])

    assert len(program_outline.weeks[0].workouts) == day_count
    assert {slot.weekday for slot in program_outline.weeks[0].workouts} == set(weekdays)


@pytest.mark.parametrize(
    ("kind", "consumes_quality"),
    [
        (ClubSessionKind.EASY, False),
        (ClubSessionKind.LONG, False),
        (ClubSessionKind.QUALITY, True),
        (ClubSessionKind.UNKNOWN, True),
    ],
)
def test_club_classification_is_explicit_and_repeats_each_week(
    kind: ClubSessionKind, consumes_quality: bool
) -> None:
    club = ClubSession(Weekday.THURSDAY, kind, TrainingAmount.duration_minutes(60))
    program_outline = outline(club_sessions=(club,))

    club_slots = [
        slot
        for week in program_outline.weeks
        for slot in week.workouts
        if slot.club_session is club
    ]
    expected_repetitions = 3 if consumes_quality else 4
    assert len(club_slots) == expected_repetitions
    assert all(slot.intent == WorkoutIntent.CLUB for slot in club_slots)
    assert all(slot.source == WorkoutSource.CLUB for slot in club_slots)
    assert all(slot.club_session is club for slot in club_slots)
    assert all(slot.consumes_quality_capacity is consumes_quality for slot in club_slots)


def test_main_race_uses_exact_unselected_date_and_wins_b_race_conflict() -> None:
    race_date = date(2026, 8, 29)
    b_race = BRace(race_date, 5, RaceIntensity.ALL_OUT)
    program_outline = outline(main_race_date=race_date, b_races=(b_race,))

    race_slot = slot_on(program_outline, race_date)
    assert race_slot.intent == WorkoutIntent.GOAL_RACE
    assert race_slot.source == WorkoutSource.MAIN_RACE
    assert race_slot.b_race is None
    assert race_slot.weekday == Weekday.SATURDAY
    assert len(program_outline.weeks[-1].workouts) == 3
    assert not any(slot.intent == WorkoutIntent.LONG for slot in program_outline.weeks[-1].workouts)


def test_main_race_on_selected_easy_day_also_replaces_goal_week_long_run() -> None:
    race_date = date(2026, 8, 25)

    program_outline = outline(main_race_date=race_date)

    final_week = program_outline.weeks[-1]
    assert slot_on(program_outline, race_date).intent == WorkoutIntent.GOAL_RACE
    assert not any(slot.intent == WorkoutIntent.LONG for slot in final_week.workouts)
    assert len(final_week.workouts) == 2


@pytest.mark.parametrize(
    ("intensity", "consumes_quality"),
    [
        (RaceIntensity.ALL_OUT, True),
        (RaceIntensity.CONTROLLED, True),
        (RaceIntensity.TRAINING_RUN, False),
    ],
)
def test_b_race_replaces_same_date_slot_with_intensity_semantics(
    intensity: RaceIntensity, consumes_quality: bool
) -> None:
    race_date = date(2026, 8, 6)
    race = BRace(race_date, 5, intensity)
    club = ClubSession(Weekday.THURSDAY, ClubSessionKind.EASY, TrainingAmount.distance_km(6))
    program_outline = outline(b_races=(race,), club_sessions=(club,))

    race_slot = slot_on(program_outline, race_date)
    assert race_slot.intent == WorkoutIntent.B_RACE
    assert race_slot.source == WorkoutSource.B_RACE
    assert race_slot.b_race is race
    assert race_slot.club_session is None
    assert race_slot.consumes_quality_capacity is consumes_quality


def test_b_race_on_unselected_day_replaces_an_easy_blueprint_slot() -> None:
    race_date = date(2026, 8, 8)
    race = BRace(race_date, 5, RaceIntensity.CONTROLLED)

    program_outline = outline(b_races=(race,))

    first_week = program_outline.weeks[0]
    assert len(first_week.workouts) == 3
    assert slot_on(program_outline, race_date).intent == WorkoutIntent.B_RACE
    assert {slot.intent for slot in first_week.workouts} == {
        WorkoutIntent.EASY,
        WorkoutIntent.LONG,
        WorkoutIntent.B_RACE,
    }


def test_quality_is_not_added_when_club_or_race_consumes_weekly_capacity() -> None:
    club = ClubSession(
        Weekday.THURSDAY, ClubSessionKind.UNKNOWN, TrainingAmount.duration_minutes(60)
    )
    race = BRace(date(2026, 8, 11), 5, RaceIntensity.CONTROLLED)
    program_outline = outline(
        quality_sessions_per_week=1,
        club_sessions=(club,),
        b_races=(race,),
    )

    assert all(
        not any(slot.intent == WorkoutIntent.QUALITY for slot in week.workouts)
        for week in program_outline.weeks[:2]
    )


@pytest.mark.parametrize("kind", [ClubSessionKind.QUALITY, ClubSessionKind.UNKNOWN])
def test_quality_b_race_replaces_different_day_quality_club(
    kind: ClubSessionKind,
) -> None:
    club = ClubSession(Weekday.THURSDAY, kind, TrainingAmount.distance_km(5))
    race = BRace(date(2026, 8, 8), 5, RaceIntensity.CONTROLLED)

    program_outline = outline(club_sessions=(club,), b_races=(race,))
    first_week = program_outline.weeks[0]

    assert len(first_week.workouts) == 3
    assert not any(slot.club_session is club for slot in first_week.workouts)
    assert slot_on(program_outline, race.date).intent == WorkoutIntent.B_RACE
    assert sum(slot.consumes_quality_capacity for slot in first_week.workouts) == 1


@pytest.mark.parametrize("kind", [ClubSessionKind.QUALITY, ClubSessionKind.UNKNOWN])
def test_goal_event_replaces_conflicting_club_quality_in_final_week(
    kind: ClubSessionKind,
) -> None:
    club = ClubSession(Weekday.THURSDAY, kind, TrainingAmount.distance_km(5))
    program_outline = outline(club_sessions=(club,))

    final_week = program_outline.weeks[-1]

    assert not any(slot.club_session is club for slot in final_week.workouts)
    assert sum(slot.consumes_quality_capacity for slot in final_week.workouts) == 1


def test_optional_quality_avoids_adjacent_intentions_across_week_boundary() -> None:
    race = BRace(date(2026, 8, 9), 5, RaceIntensity.ALL_OUT)
    program_outline = outline(
        weekdays=(Weekday.MONDAY, Weekday.WEDNESDAY),
        long_run_day=Weekday.WEDNESDAY,
        b_races=(race,),
        quality_sessions_per_week=1,
    )

    second_week = program_outline.weeks[1]
    assert not any(slot.intent == WorkoutIntent.QUALITY for slot in second_week.workouts)


def test_optional_quality_has_stable_semantic_ids_and_dates() -> None:
    program_outline = outline(quality_sessions_per_week=1)

    first_week = program_outline.weeks[0]
    assert [(slot.stable_id, slot.date, slot.intent) for slot in first_week.workouts] == [
        ("w01-tue-easy", date(2026, 8, 4), WorkoutIntent.EASY),
        ("w01-thu-easy", date(2026, 8, 6), WorkoutIntent.EASY),
        ("w01-sun-long", date(2026, 8, 9), WorkoutIntent.LONG),
    ]
    assert program_outline.weeks[1].workouts[0].stable_id == "w02-tue-quality"
    assert program_outline.weeks[1].workouts[0].intent is WorkoutIntent.QUALITY
    assert len({slot.stable_id for slot in first_week.workouts}) == len(first_week.workouts)
    assert all(slot.week_number == 1 for slot in first_week.workouts)
    assert first_week.start_date == START
    assert first_week.end_date == date(2026, 8, 9)


@pytest.mark.parametrize(
    ("duration", "expected"),
    [
        (1, (TrainingPhase.TAPER,)),
        (2, (TrainingPhase.CONSOLIDATION, TrainingPhase.TAPER)),
        (
            4,
            (
                TrainingPhase.FOUNDATION,
                TrainingPhase.BUILD,
                TrainingPhase.CONSOLIDATION,
                TrainingPhase.TAPER,
            ),
        ),
    ],
)
def test_short_period_phase_assignment_is_natural(
    duration: int, expected: tuple[TrainingPhase, ...]
) -> None:
    if duration < 4:
        race_date = START.replace(day=START.day + (duration - 1) * 7 + 6)
        program_outline = outline(
            main_race_date=race_date,
            start_week=None,
            duration_weeks=None,
        )
    else:
        program_outline = outline(duration_weeks=duration)

    assert tuple(week.phase for week in program_outline.weeks) == expected


def test_long_custom_period_places_recovery_and_taper_deterministically() -> None:
    program_outline = outline(duration_weeks=52)

    assert program_outline.weeks[3].phase == TrainingPhase.CONSOLIDATION
    assert program_outline.weeks[7].phase == TrainingPhase.CONSOLIDATION
    assert program_outline.weeks[-2].phase == TrainingPhase.CONSOLIDATION
    assert program_outline.weeks[-1].phase == TrainingPhase.TAPER
    assert {week.phase for week in program_outline.weeks} == set(TrainingPhase)


def test_consolidation_does_not_repeat_immediately_before_taper() -> None:
    program_outline = outline(duration_weeks=6)

    assert tuple(week.phase for week in program_outline.weeks[-3:]) == (
        TrainingPhase.BUILD,
        TrainingPhase.CONSOLIDATION,
        TrainingPhase.TAPER,
    )


def test_no_race_final_long_run_day_becomes_10k_test_run() -> None:
    b_race = BRace(date(2026, 8, 30), 5, RaceIntensity.ALL_OUT)
    program_outline = outline(b_races=(b_race,))

    final_slot = slot_on(program_outline, date(2026, 8, 30))
    assert final_slot.intent == WorkoutIntent.TEST_RUN
    assert final_slot.source == WorkoutSource.TEST_RUN
    assert final_slot.consumes_quality_capacity is True
    assert final_slot.stable_id == "w04-sun-test-run"
