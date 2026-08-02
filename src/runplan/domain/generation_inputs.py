"""Provider-independent inputs for first 10K program generation."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum, IntEnum


class GenerationInputError(ValueError):
    """A precise error in first 10K generation input."""


class Weekday(IntEnum):
    MONDAY = 1
    TUESDAY = 2
    WEDNESDAY = 3
    THURSDAY = 4
    FRIDAY = 5
    SATURDAY = 6
    SUNDAY = 7


class AmountKind(Enum):
    DISTANCE_KM = "distance_km"
    DURATION_MINUTES = "duration_minutes"


class ClubSessionKind(Enum):
    EASY = "easy"
    LONG = "long"
    QUALITY = "quality"
    UNKNOWN = "unknown"


class RaceIntensity(Enum):
    ALL_OUT = "all-out"
    CONTROLLED = "controlled"
    TRAINING_RUN = "training-run"


class ProgressionProfile(Enum):
    CAUTIOUS = "cautious"
    BALANCED = "balanced"
    AMBITIOUS = "ambitious"


class TrainingStyle(Enum):
    AUTO = "auto"
    RUN_WALK = "run-walk"
    CONTINUOUS = "continuous"


class QualityPreference(Enum):
    AUTO = "auto"
    NONE = "none"
    BUILD = "build"


def _require_finite_positive(value: float, field: str) -> None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GenerationInputError(f"{field} must be a number greater than 0")
    if not math.isfinite(value) or value <= 0:
        raise GenerationInputError(f"{field} must be greater than 0")


@dataclass(frozen=True, slots=True)
class TrainingAmount:
    """An amount expressed in exactly one supported training unit."""

    kind: AmountKind
    value: float

    def __post_init__(self) -> None:
        if not isinstance(self.kind, AmountKind):
            raise GenerationInputError(
                "training amount kind must be distance_km or duration_minutes"
            )
        _require_finite_positive(self.value, "training amount")

    @classmethod
    def distance_km(cls, value: float) -> TrainingAmount:
        return cls(AmountKind.DISTANCE_KM, value)

    @classmethod
    def duration_minutes(cls, value: float) -> TrainingAmount:
        return cls(AmountKind.DURATION_MINUTES, value)


@dataclass(frozen=True, slots=True)
class DurationMinutes:
    value: float

    def __post_init__(self) -> None:
        _require_finite_positive(self.value, "duration")


@dataclass(frozen=True, slots=True)
class Pace:
    """A min/km pace range, represented as seconds per kilometer."""

    fast_seconds_per_km: float
    slow_seconds_per_km: float

    def __post_init__(self) -> None:
        _require_finite_positive(self.fast_seconds_per_km, "pace")
        _require_finite_positive(self.slow_seconds_per_km, "pace")
        if self.fast_seconds_per_km > self.slow_seconds_per_km:
            raise GenerationInputError("pace fast bound must not exceed the slow bound")


def _normalize_text(note: str | None, field: str, maximum_length: int) -> str | None:
    if note is None:
        return None
    if not isinstance(note, str):
        raise GenerationInputError(f"{field} must be text")
    normalized = note.strip()
    if len(normalized) > maximum_length:
        raise GenerationInputError(f"{field} must be at most {maximum_length} characters")
    return normalized or None


@dataclass(frozen=True, slots=True)
class CurrentTraining:
    average_weekly_km: float
    run_days_per_week: int
    longest_recent_run: TrainingAmount
    recent_5k_duration: DurationMinutes | None = None
    easy_pace: Pace | None = None

    def __post_init__(self) -> None:
        value = self.average_weekly_km
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise GenerationInputError("average weekly distance must be a number")
        if not math.isfinite(value) or value < 0:
            raise GenerationInputError("average weekly distance must be at least 0 km")
        if value > 300:
            raise GenerationInputError("average weekly distance must be at most 300 km")
        if (
            isinstance(self.run_days_per_week, bool)
            or not isinstance(self.run_days_per_week, int)
            or not 0 <= self.run_days_per_week <= 7
        ):
            raise GenerationInputError("current running days must be an integer from 0 to 7")
        if not isinstance(self.longest_recent_run, TrainingAmount):
            raise GenerationInputError("longest recent run must be a training amount")
        if self.recent_5k_duration is not None and not isinstance(
            self.recent_5k_duration, DurationMinutes
        ):
            raise GenerationInputError("recent 5K duration must be a duration")
        if self.recent_5k_duration is not None and not 10 <= self.recent_5k_duration.value <= 180:
            raise GenerationInputError("recent 5K duration must be from 10 to 180 minutes")
        if self.easy_pace is not None and not isinstance(self.easy_pace, Pace):
            raise GenerationInputError("easy pace must be a pace")


@dataclass(frozen=True, slots=True)
class ClubSession:
    weekday: Weekday
    kind: ClubSessionKind
    amount: TrainingAmount
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.weekday, Weekday):
            raise GenerationInputError("club session weekday must be a weekday")
        if not isinstance(self.kind, ClubSessionKind):
            raise GenerationInputError("club session kind is invalid")
        if not isinstance(self.amount, TrainingAmount):
            raise GenerationInputError("club session amount must be a training amount")
        object.__setattr__(self, "note", _normalize_text(self.note, "club session note", 500))


@dataclass(frozen=True, slots=True)
class BRace:
    date: date
    distance_km: float
    intensity: RaceIntensity
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.date, date):
            raise GenerationInputError("B race date must be a date")
        _require_finite_positive(self.distance_km, "B race distance")
        if not isinstance(self.intensity, RaceIntensity):
            raise GenerationInputError("B race intensity is invalid")
        object.__setattr__(self, "note", _normalize_text(self.note, "B race note", 500))


@dataclass(frozen=True, slots=True)
class First10KGenerationInput:
    current_training: CurrentTraining
    weekdays: tuple[Weekday, ...]
    long_run_day: Weekday | None = None
    main_race_date: date | None = None
    club_sessions: tuple[ClubSession, ...] = ()
    b_races: tuple[BRace, ...] = ()
    start_week: date | None = None
    duration_weeks: int | None = None
    maximum_weekly_km: float | None = None
    maximum_long_run_km: float | None = None
    progression: ProgressionProfile = ProgressionProfile.BALANCED
    training_style: TrainingStyle = TrainingStyle.AUTO
    quality_preference: QualityPreference = QualityPreference.AUTO
    quality_sessions_per_week: int | None = None
    additional_instructions: str | None = None


@dataclass(frozen=True, slots=True)
class PeriodSuggestion:
    start_week: date
    duration_weeks: int
    warnings: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.start_week, date) or self.start_week.isoweekday() != 1:
            raise GenerationInputError("program start week must be an ISO Monday")
        if (
            isinstance(self.duration_weeks, bool)
            or not isinstance(self.duration_weeks, int)
            or self.duration_weeks <= 0
        ):
            raise GenerationInputError("program duration must be a positive number of weeks")

    @property
    def end_date(self) -> date:
        return self.start_week + timedelta(weeks=self.duration_weeks, days=-1)


@dataclass(frozen=True, slots=True)
class NormalizedFirst10KGenerationInput:
    current_training: CurrentTraining
    weekdays: tuple[Weekday, ...]
    long_run_day: Weekday
    long_run_day_was_proposed: bool
    main_race_date: date | None
    club_sessions: tuple[ClubSession, ...]
    b_races: tuple[BRace, ...]
    period: PeriodSuggestion
    maximum_weekly_km: float | None
    maximum_long_run_km: float | None
    progression: ProgressionProfile
    training_style: TrainingStyle
    quality_preference: QualityPreference
    quality_sessions_per_week: int
    additional_instructions: str | None
    warnings: tuple[str, ...]


def _iso_monday(value: date) -> date:
    return value - timedelta(days=value.isoweekday() - 1)


def suggest_first_10k_period(main_race_date: date | None, *, today: date) -> PeriodSuggestion:
    """Suggest an ISO-week-aligned period, including the main race week."""
    if not isinstance(today, date):
        raise GenerationInputError("today must be a date")
    next_week = _iso_monday(today) + timedelta(weeks=1)
    if main_race_date is None:
        return PeriodSuggestion(next_week, 12)
    if not isinstance(main_race_date, date):
        raise GenerationInputError("main race date must be a date")
    if main_race_date < today:
        raise GenerationInputError("main race date must not be in the past")

    race_week = _iso_monday(main_race_date)
    if race_week < next_week:
        available_weeks = 1
        start_week = race_week
    else:
        available_weeks = (race_week - next_week).days // 7 + 1
        start_week = next_week
    if available_weeks > 16:
        return PeriodSuggestion(race_week - timedelta(weeks=15), 16)
    warnings = ()
    if available_weeks < 8:
        warnings = (
            f"Only {available_weeks} weeks are available before the main race; "
            "the recommended minimum is 8 weeks.",
        )
    return PeriodSuggestion(start_week, available_weeks, warnings)


def _resolve_period(request: First10KGenerationInput, today: date) -> PeriodSuggestion:
    suggested = suggest_first_10k_period(request.main_race_date, today=today)
    if request.start_week is not None and not isinstance(request.start_week, date):
        raise GenerationInputError("custom start week must be a date")
    custom_start = _iso_monday(request.start_week) if request.start_week is not None else None
    custom_duration = request.duration_weeks
    if custom_duration is not None and (
        isinstance(custom_duration, bool)
        or not isinstance(custom_duration, int)
        or not 4 <= custom_duration <= 52
    ):
        raise GenerationInputError("custom duration must be an integer from 4 to 52 weeks")

    if request.main_race_date is not None and custom_duration is not None and custom_start is None:
        custom_start = _iso_monday(request.main_race_date) - timedelta(weeks=custom_duration - 1)
    start = custom_start or suggested.start_week
    if custom_duration is not None:
        duration = custom_duration
    elif custom_start is not None and request.main_race_date is not None:
        race_week = _iso_monday(request.main_race_date)
        duration = (race_week - custom_start).days // 7 + 1
        if not 4 <= duration <= 52:
            raise GenerationInputError(
                "custom start week must produce a program of 4 to 52 weeks through the main race"
            )
    else:
        duration = suggested.duration_weeks

    period = PeriodSuggestion(start, duration, suggested.warnings)
    if (
        request.main_race_date is not None
        and not start <= request.main_race_date <= period.end_date
    ):
        raise GenerationInputError("main race date must fall inside the program period")
    if (
        request.main_race_date is not None
        and (request.start_week is not None or request.duration_weeks is not None)
        and _iso_monday(request.main_race_date) != start + timedelta(weeks=duration - 1)
    ):
        raise GenerationInputError(
            "main race date must fall in the final ISO week of a custom program"
        )
    return period


def _has_consecutive_days(weekdays: tuple[Weekday, ...]) -> bool:
    values = {int(day) for day in weekdays}
    return any(day % 7 + 1 in values for day in values)


def normalize_first_10k_input(
    request: First10KGenerationInput, *, today: date
) -> NormalizedFirst10KGenerationInput:
    """Normalize and validate a complete first 10K generation request."""
    if not isinstance(request, First10KGenerationInput):
        raise GenerationInputError("generation request must be a first 10K generation input")
    if not isinstance(request.current_training, CurrentTraining):
        raise GenerationInputError("current training must be provided")
    try:
        weekdays = tuple(sorted(set(request.weekdays)))
    except TypeError as exc:
        raise GenerationInputError("training weekdays must be weekdays") from exc
    if any(not isinstance(day, Weekday) for day in weekdays):
        raise GenerationInputError("training weekdays must be weekdays")
    if not 2 <= len(weekdays) <= 7:
        raise GenerationInputError("select between 2 and 7 training weekdays")

    proposed = request.long_run_day is None
    if request.long_run_day is not None and not isinstance(request.long_run_day, Weekday):
        raise GenerationInputError("long-run day must be a weekday")
    long_run_day = request.long_run_day or next(
        (day for day in (Weekday.SUNDAY, Weekday.SATURDAY) if day in weekdays), weekdays[-1]
    )
    if long_run_day not in weekdays:
        raise GenerationInputError("long-run day must be one of the selected training weekdays")

    if any(not isinstance(session, ClubSession) for session in request.club_sessions):
        raise GenerationInputError("club sessions must be club session values")
    club_days = [session.weekday for session in request.club_sessions]
    if len(set(club_days)) != len(club_days):
        raise GenerationInputError("club sessions must use unique weekdays")
    if unselected := sorted(day for day in club_days if day not in weekdays):
        names = ", ".join(day.name.title() for day in unselected)
        raise GenerationInputError(f"club session weekdays must be selected training days: {names}")
    long_day_club = next(
        (session for session in request.club_sessions if session.weekday == long_run_day), None
    )
    if long_day_club is not None and long_day_club.kind != ClubSessionKind.LONG:
        raise GenerationInputError("club session on the long-run day must have kind long")

    period = _resolve_period(request, today)
    if any(not isinstance(race, BRace) for race in request.b_races):
        raise GenerationInputError("B races must be B race values")
    races = tuple(sorted(request.b_races, key=lambda race: race.date))
    race_dates = [race.date for race in races]
    if len(set(race_dates)) != len(race_dates):
        raise GenerationInputError("B races must use unique dates")
    for race in races:
        if not period.start_week <= race.date <= period.end_date:
            raise GenerationInputError(
                f"B race on {race.date.isoformat()} must fall inside the program period"
            )

    race_dates_by_week: dict[date, set[date]] = {}
    for race in races:
        if race.date != request.main_race_date:
            race_dates_by_week.setdefault(_iso_monday(race.date), set()).add(race.date)
    if request.main_race_date is not None:
        race_dates_by_week.setdefault(_iso_monday(request.main_race_date), set()).add(
            request.main_race_date
        )
    for week_start, week_race_dates in sorted(race_dates_by_week.items()):
        if len(week_race_dates) > len(weekdays):
            year, week, _ = week_start.isocalendar()
            raise GenerationInputError(
                f"race week {year}-W{week:02d} has {len(week_race_dates)} distinct race dates "
                f"but only {len(weekdays)} selected training weekdays"
            )

    quality_race_dates_by_week: dict[date, set[date]] = {}
    for race in races:
        if race.date == request.main_race_date:
            continue
        if race.intensity in (RaceIntensity.ALL_OUT, RaceIntensity.CONTROLLED):
            quality_race_dates_by_week.setdefault(_iso_monday(race.date), set()).add(race.date)
    if request.main_race_date is not None:
        quality_race_dates_by_week.setdefault(_iso_monday(request.main_race_date), set()).add(
            request.main_race_date
        )
    for week_start, quality_dates in sorted(quality_race_dates_by_week.items()):
        if len(quality_dates) > 1:
            year, week, _ = week_start.isocalendar()
            raise GenerationInputError(
                f"race week {year}-W{week:02d} contains more than one quality race"
            )

    for value, field in (
        (request.maximum_weekly_km, "maximum weekly distance"),
        (request.maximum_long_run_km, "maximum long-run distance"),
    ):
        if value is not None:
            _require_finite_positive(value, field)
    if not isinstance(request.progression, ProgressionProfile):
        raise GenerationInputError("progression profile is invalid")
    if not isinstance(request.training_style, TrainingStyle):
        raise GenerationInputError("training style is invalid")
    if not isinstance(request.quality_preference, QualityPreference):
        raise GenerationInputError("quality preference is invalid")
    quality_preference = request.quality_preference
    if request.quality_sessions_per_week is not None:
        if request.quality_sessions_per_week not in (0, 1) or isinstance(
            request.quality_sessions_per_week, bool
        ):
            raise GenerationInputError("quality sessions per week must be 0 or 1")
        quality_preference = (
            QualityPreference.BUILD
            if request.quality_sessions_per_week == 1
            else QualityPreference.NONE
        )
    instructions = _normalize_text(request.additional_instructions, "additional instructions", 1000)
    if instructions is not None:
        raise GenerationInputError(
            "additional instructions are no longer supported; use the structured controls"
        )

    warnings = list(period.warnings)
    if len(weekdays) not in (3, 4):
        warnings.append("Three or four training days per week are recommended for this program.")
    if _has_consecutive_days(weekdays):
        warnings.append("The selected schedule contains consecutive training days.")
    club_weekdays = set(club_days)
    quality_club_days = {
        session.weekday
        for session in request.club_sessions
        if session.kind in (ClubSessionKind.QUALITY, ClubSessionKind.UNKNOWN)
    }
    for race in races:
        if request.main_race_date == race.date:
            warnings.append(
                f"The main race takes precedence over the B race on {race.date.isoformat()}."
            )
            continue
        if Weekday(race.date.isoweekday()) in club_weekdays:
            warnings.append(
                f"The B race on {race.date.isoformat()} replaces that day's club session."
            )
        if race.intensity in (
            RaceIntensity.ALL_OUT,
            RaceIntensity.CONTROLLED,
        ) and quality_club_days - {Weekday(race.date.isoweekday())}:
            warnings.append(
                f"The B race on {race.date.isoformat()} replaces other quality club sessions "
                "that week."
            )
    if (
        request.main_race_date is not None
        and Weekday(request.main_race_date.isoweekday()) in club_weekdays
    ):
        warnings.append(
            f"The main race on {request.main_race_date.isoformat()} replaces that day's club session."
        )
    if request.main_race_date is not None and quality_club_days - {
        Weekday(request.main_race_date.isoweekday())
    }:
        warnings.append("The main race replaces other quality club sessions that week.")

    return NormalizedFirst10KGenerationInput(
        current_training=request.current_training,
        weekdays=weekdays,
        long_run_day=long_run_day,
        long_run_day_was_proposed=proposed,
        main_race_date=request.main_race_date,
        club_sessions=tuple(sorted(request.club_sessions, key=lambda session: session.weekday)),
        b_races=races,
        period=period,
        maximum_weekly_km=request.maximum_weekly_km,
        maximum_long_run_km=request.maximum_long_run_km,
        progression=request.progression,
        training_style=request.training_style,
        quality_preference=quality_preference,
        quality_sessions_per_week=0 if quality_preference is QualityPreference.NONE else 1,
        additional_instructions=None,
        warnings=tuple(warnings),
    )


__all__ = [
    "AmountKind",
    "BRace",
    "ClubSession",
    "ClubSessionKind",
    "CurrentTraining",
    "DurationMinutes",
    "First10KGenerationInput",
    "GenerationInputError",
    "NormalizedFirst10KGenerationInput",
    "Pace",
    "PeriodSuggestion",
    "ProgressionProfile",
    "QualityPreference",
    "RaceIntensity",
    "TrainingAmount",
    "TrainingStyle",
    "Weekday",
    "normalize_first_10k_input",
    "suggest_first_10k_period",
]
