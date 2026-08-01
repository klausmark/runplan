from dataclasses import FrozenInstanceError
from datetime import date

import pytest

from runplan.domain.generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    DurationMinutes,
    First10KGenerationInput,
    GenerationInputError,
    Pace,
    ProgressionProfile,
    RaceIntensity,
    TrainingAmount,
    Weekday,
    normalize_first_10k_input,
    suggest_first_10k_period,
)


def training() -> CurrentTraining:
    return CurrentTraining(
        average_weekly_km=12,
        run_days_per_week=3,
        longest_recent_run=TrainingAmount.distance_km(6),
        recent_5k_duration=DurationMinutes(32),
        easy_pace=Pace(390, 420),
    )


def request(**changes: object) -> First10KGenerationInput:
    values = {
        "current_training": training(),
        "weekdays": (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY),
    }
    values.update(changes)
    return First10KGenerationInput(**values)  # type: ignore[arg-type]


def test_inputs_are_immutable_typed_values() -> None:
    amount = TrainingAmount.duration_minutes(45)

    with pytest.raises(FrozenInstanceError):
        amount.value = 50  # type: ignore[misc]


@pytest.mark.parametrize("value", [0, -1, float("inf"), True])
def test_training_amount_requires_a_finite_positive_value(value: float) -> None:
    with pytest.raises(GenerationInputError, match="training amount must be .*greater than 0"):
        TrainingAmount.distance_km(value)


def test_negative_average_weekly_distance_has_precise_error() -> None:
    with pytest.raises(GenerationInputError, match="average weekly distance must be at least 0 km"):
        CurrentTraining(-1, 3, TrainingAmount.distance_km(5))


def test_no_race_suggests_next_iso_week_for_twelve_weeks() -> None:
    suggestion = suggest_first_10k_period(None, today=date(2026, 12, 30))

    assert suggestion.start_week == date(2027, 1, 4)
    assert suggestion.duration_weeks == 12
    assert suggestion.end_date == date(2027, 3, 28)
    assert suggestion.warnings == ()


def test_race_with_natural_period_uses_all_available_weeks() -> None:
    suggestion = suggest_first_10k_period(date(2026, 10, 18), today=date(2026, 8, 1))

    assert suggestion.start_week == date(2026, 8, 3)
    assert suggestion.duration_weeks == 11
    assert suggestion.end_date == date(2026, 10, 18)


def test_distant_race_caps_period_at_sixteen_weeks_and_starts_later() -> None:
    suggestion = suggest_first_10k_period(date(2027, 1, 10), today=date(2026, 8, 1))

    assert suggestion.start_week == date(2026, 9, 21)
    assert suggestion.duration_weeks == 16
    assert suggestion.end_date == date(2027, 1, 10)


def test_short_race_period_remains_valid_with_warning() -> None:
    normalized = normalize_first_10k_input(
        request(main_race_date=date(2026, 8, 23)), today=date(2026, 8, 1)
    )

    assert normalized.period.duration_weeks == 3
    assert normalized.warnings[0] == (
        "Only 3 weeks are available before the main race; the recommended minimum is 8 weeks."
    )


def test_past_main_race_has_precise_error() -> None:
    with pytest.raises(GenerationInputError, match="main race date must not be in the past"):
        normalize_first_10k_input(request(main_race_date=date(2026, 7, 31)), today=date(2026, 8, 1))


def test_custom_duration_aligns_period_to_race_week() -> None:
    normalized = normalize_first_10k_input(
        request(main_race_date=date(2027, 1, 10), duration_weeks=20), today=date(2026, 8, 1)
    )

    assert normalized.period.start_week == date(2026, 8, 24)
    assert normalized.period.duration_weeks == 20


def test_custom_start_is_normalized_to_iso_week() -> None:
    normalized = normalize_first_10k_input(
        request(start_week=date(2026, 8, 5), duration_weeks=4), today=date(2026, 8, 1)
    )

    assert normalized.period.start_week == date(2026, 8, 3)


def test_custom_period_must_contain_main_race() -> None:
    with pytest.raises(
        GenerationInputError, match="main race date must fall inside the program period"
    ):
        normalize_first_10k_input(
            request(
                main_race_date=date(2026, 10, 18),
                start_week=date(2026, 8, 3),
                duration_weeks=4,
            ),
            today=date(2026, 8, 1),
        )


def test_custom_period_requires_main_race_in_final_iso_week() -> None:
    with pytest.raises(
        GenerationInputError,
        match="main race date must fall in the final ISO week of a custom program",
    ):
        normalize_first_10k_input(
            request(
                main_race_date=date(2026, 8, 23),
                start_week=date(2026, 8, 3),
                duration_weeks=8,
            ),
            today=date(2026, 8, 1),
        )


def test_custom_period_accepts_main_race_in_final_iso_week() -> None:
    normalized = normalize_first_10k_input(
        request(
            main_race_date=date(2026, 9, 27),
            start_week=date(2026, 8, 3),
            duration_weeks=8,
        ),
        today=date(2026, 8, 1),
    )

    assert normalized.period.end_date == date(2026, 9, 27)


@pytest.mark.parametrize("duration", [3, 53, True, 4.5])
def test_invalid_custom_duration_has_precise_error(duration: object) -> None:
    with pytest.raises(
        GenerationInputError, match="custom duration must be an integer from 4 to 52 weeks"
    ):
        normalize_first_10k_input(request(duration_weeks=duration), today=date(2026, 8, 1))


def test_schedule_is_sorted_and_long_run_day_is_proposed() -> None:
    normalized = normalize_first_10k_input(
        request(weekdays=(Weekday.SUNDAY, Weekday.TUESDAY, Weekday.THURSDAY)),
        today=date(2026, 8, 1),
    )

    assert normalized.weekdays == (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY)
    assert normalized.long_run_day == Weekday.SUNDAY
    assert normalized.long_run_day_was_proposed is True


def test_explicit_long_run_day_must_be_selected() -> None:
    with pytest.raises(
        GenerationInputError, match="long-run day must be one of the selected training weekdays"
    ):
        normalize_first_10k_input(request(long_run_day=Weekday.SATURDAY), today=date(2026, 8, 1))


def test_long_run_day_must_be_a_weekday_value() -> None:
    with pytest.raises(GenerationInputError, match="long-run day must be a weekday"):
        normalize_first_10k_input(request(long_run_day=7), today=date(2026, 8, 1))


def test_two_consecutive_days_produce_standard_warnings() -> None:
    normalized = normalize_first_10k_input(
        request(weekdays=(Weekday.MONDAY, Weekday.TUESDAY)), today=date(2026, 8, 1)
    )

    assert normalized.warnings == (
        "Three or four training days per week are recommended for this program.",
        "The selected schedule contains consecutive training days.",
    )


def test_club_sessions_are_normalized_and_must_use_unique_selected_days() -> None:
    session = ClubSession(
        Weekday.THURSDAY,
        ClubSessionKind.QUALITY,
        TrainingAmount.duration_minutes(60),
        "  Group intervals  ",
    )
    normalized = normalize_first_10k_input(
        request(club_sessions=(session,)), today=date(2026, 8, 1)
    )

    assert normalized.club_sessions[0].note == "Group intervals"

    with pytest.raises(GenerationInputError, match="club sessions must use unique weekdays"):
        normalize_first_10k_input(request(club_sessions=(session, session)), today=date(2026, 8, 1))


def test_unselected_club_day_has_precise_error() -> None:
    session = ClubSession(Weekday.FRIDAY, ClubSessionKind.EASY, TrainingAmount.distance_km(5))

    with pytest.raises(
        GenerationInputError,
        match="club session weekdays must be selected training days: Friday",
    ):
        normalize_first_10k_input(request(club_sessions=(session,)), today=date(2026, 8, 1))


@pytest.mark.parametrize(
    "kind",
    [ClubSessionKind.EASY, ClubSessionKind.QUALITY, ClubSessionKind.UNKNOWN],
)
def test_club_session_on_long_run_day_must_be_long(kind: ClubSessionKind) -> None:
    session = ClubSession(Weekday.SUNDAY, kind, TrainingAmount.distance_km(8))

    with pytest.raises(
        GenerationInputError, match="club session on the long-run day must have kind long"
    ):
        normalize_first_10k_input(request(club_sessions=(session,)), today=date(2026, 8, 1))


def test_long_club_session_is_valid_on_long_run_day() -> None:
    session = ClubSession(Weekday.SUNDAY, ClubSessionKind.LONG, TrainingAmount.distance_km(8))

    normalized = normalize_first_10k_input(
        request(club_sessions=(session,)), today=date(2026, 8, 1)
    )

    assert normalized.club_sessions == (session,)


def test_races_are_sorted_and_main_race_precedence_is_explicit() -> None:
    main_date = date(2026, 10, 18)
    races = (
        BRace(date(2026, 9, 13), 5, RaceIntensity.CONTROLLED),
        BRace(main_date, 10, RaceIntensity.TRAINING_RUN),
    )
    session = ClubSession(Weekday.SUNDAY, ClubSessionKind.LONG, TrainingAmount.distance_km(8))

    normalized = normalize_first_10k_input(
        request(main_race_date=main_date, b_races=races, club_sessions=(session,)),
        today=date(2026, 8, 1),
    )

    assert normalized.b_races == races
    assert "The main race takes precedence over the B race on 2026-10-18." in normalized.warnings
    assert "The B race on 2026-09-13 replaces that day's club session." in normalized.warnings
    assert "The main race on 2026-10-18 replaces that day's club session." in normalized.warnings


def test_b_race_outside_period_has_precise_error() -> None:
    race = BRace(date(2026, 7, 26), 5, RaceIntensity.ALL_OUT)

    with pytest.raises(
        GenerationInputError,
        match="B race on 2026-07-26 must fall inside the program period",
    ):
        normalize_first_10k_input(request(b_races=(race,)), today=date(2026, 8, 1))


def test_b_races_must_use_unique_dates() -> None:
    race = BRace(date(2026, 9, 13), 5, RaceIntensity.ALL_OUT)

    with pytest.raises(GenerationInputError, match="B races must use unique dates"):
        normalize_first_10k_input(request(b_races=(race, race)), today=date(2026, 8, 1))


def test_race_week_must_fit_selected_training_day_count() -> None:
    main_race = date(2026, 8, 30)
    races = (
        BRace(date(2026, 8, 25), 5, RaceIntensity.CONTROLLED),
        BRace(date(2026, 8, 27), 5, RaceIntensity.TRAINING_RUN),
    )

    with pytest.raises(
        GenerationInputError,
        match=(
            "race week 2026-W35 has 3 distinct race dates but only 2 selected training weekdays"
        ),
    ):
        normalize_first_10k_input(
            request(
                weekdays=(Weekday.TUESDAY, Weekday.SUNDAY),
                main_race_date=main_race,
                b_races=races,
                start_week=date(2026, 8, 3),
                duration_weeks=4,
            ),
            today=date(2026, 8, 1),
        )


def test_b_race_on_main_race_date_does_not_oversubscribe_week() -> None:
    main_race = date(2026, 8, 30)
    normalized = normalize_first_10k_input(
        request(
            weekdays=(Weekday.TUESDAY, Weekday.SUNDAY),
            main_race_date=main_race,
            b_races=(BRace(main_race, 5, RaceIntensity.CONTROLLED),),
            start_week=date(2026, 8, 3),
            duration_weeks=4,
        ),
        today=date(2026, 8, 1),
    )

    assert normalized.main_race_date == main_race


@pytest.mark.parametrize("average", [300, 300.1])
def test_average_weekly_distance_has_browser_aligned_maximum(average: float) -> None:
    if average == 300:
        assert CurrentTraining(average, 3, TrainingAmount.distance_km(5)).average_weekly_km == 300
        return

    with pytest.raises(GenerationInputError, match="at most 300 km"):
        CurrentTraining(average, 3, TrainingAmount.distance_km(5))


@pytest.mark.parametrize("minutes", [9.9, 10, 180, 180.1])
def test_recent_5k_duration_has_browser_aligned_bounds(minutes: float) -> None:
    if 10 <= minutes <= 180:
        current = CurrentTraining(
            12, 3, TrainingAmount.distance_km(5), recent_5k_duration=DurationMinutes(minutes)
        )
        assert current.recent_5k_duration is not None
        return

    with pytest.raises(GenerationInputError, match="from 10 to 180 minutes"):
        CurrentTraining(
            12, 3, TrainingAmount.distance_km(5), recent_5k_duration=DurationMinutes(minutes)
        )


def test_malformed_nested_values_have_domain_errors() -> None:
    with pytest.raises(GenerationInputError, match="club sessions must be club session values"):
        normalize_first_10k_input(request(club_sessions=("Thursday",)), today=date(2026, 8, 1))

    with pytest.raises(GenerationInputError, match="B races must be B race values"):
        normalize_first_10k_input(request(b_races=("2026-09-13",)), today=date(2026, 8, 1))


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"weekdays": (Weekday.MONDAY,)}, "select between 2 and 7 training weekdays"),
        ({"quality_sessions_per_week": 2}, "quality sessions per week must be 0 or 1"),
        ({"maximum_weekly_km": 0}, "maximum weekly distance must be greater than 0"),
        ({"progression": "fast"}, "progression profile is invalid"),
    ],
)
def test_invalid_request_values_have_precise_errors(
    changes: dict[str, object], message: str
) -> None:
    with pytest.raises(GenerationInputError, match=message):
        normalize_first_10k_input(request(**changes), today=date(2026, 8, 1))


def test_zero_current_distance_and_advanced_values_are_valid() -> None:
    current = CurrentTraining(0, 0, TrainingAmount.duration_minutes(20))

    normalized = normalize_first_10k_input(
        request(
            current_training=current,
            maximum_weekly_km=30,
            maximum_long_run_km=12,
            progression=ProgressionProfile.CAUTIOUS,
            quality_sessions_per_week=1,
            additional_instructions="  Prefer run/walk intervals.  ",
        ),
        today=date(2026, 8, 1),
    )

    assert normalized.current_training.average_weekly_km == 0
    assert normalized.additional_instructions == "Prefer run/walk intervals."


def test_additional_instructions_are_bounded() -> None:
    with pytest.raises(
        GenerationInputError, match="additional instructions must be at most 1000 characters"
    ):
        normalize_first_10k_input(
            request(additional_instructions="x" * 1001), today=date(2026, 8, 1)
        )
