"""Web-facing boundary for first 10K program generation."""

from __future__ import annotations

import math
from collections.abc import Callable
from datetime import date
from typing import Any

from .application.generate_first_10k import First10KProgramDraft, GenerateFirst10KProgram
from .domain.errors import WorkoutDefinitionError
from .domain.generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    CurrentTraining,
    DurationMinutes,
    First10KGenerationInput,
    GenerationInputError,
    Pace,
    ProgressionProfile,
    QualityPreference,
    RaceIntensity,
    TrainingAmount,
    TrainingStyle,
    Weekday,
)
from .parsing.values import parse_pace
from .users import UserRegistry


def _object(value: object, field: str, allowed: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise GenerationInputError(f"{field} must be an object")
    unknown = set(value) - allowed
    if unknown:
        raise GenerationInputError(f"{field} contains unknown field {sorted(unknown)[0]!r}")
    return value


def _number(value: object, field: str, *, optional: bool = False) -> float | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise GenerationInputError(f"{field} must be a number")
    return float(value)


def _integer(value: object, field: str, *, optional: bool = False) -> int | None:
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise GenerationInputError(f"{field} must be an integer")
    return value


def _date(value: object, field: str, *, optional: bool = False) -> date | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise GenerationInputError(f"{field} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise GenerationInputError(f"{field} must be an ISO date") from None


def _enum(value: object, enum_type: type[Any], field: str) -> Any:
    if not isinstance(value, str):
        raise GenerationInputError(f"{field} is invalid")
    try:
        return enum_type(value)
    except ValueError:
        raise GenerationInputError(f"{field} is invalid") from None


def _weekday(value: object, field: str, *, optional: bool = False) -> Weekday | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise GenerationInputError(f"{field} must be a weekday name")
    try:
        return Weekday[value.upper()]
    except KeyError:
        raise GenerationInputError(f"{field} must be a weekday name") from None


def _text(value: object, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str):
        raise GenerationInputError(f"{field} must be text")
    return value


def _amount(value: object, field: str) -> TrainingAmount:
    raw = _object(value, field, {"distanceKm", "durationMinutes"})
    present = [name for name in ("distanceKm", "durationMinutes") if name in raw]
    if len(present) != 1:
        raise GenerationInputError(
            f"{field} must contain exactly one of distanceKm or durationMinutes"
        )
    amount = _number(raw[present[0]], f"{field}.{present[0]}")
    assert amount is not None
    if present[0] == "distanceKm":
        return TrainingAmount.distance_km(amount)
    return TrainingAmount.duration_minutes(amount)


def _easy_pace(value: object) -> Pace | None:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            fast, slow = parse_pace(text, "currentTraining.easyPace")
        except WorkoutDefinitionError:
            try:
                fast, slow = parse_pace(f"{text} min/km", "currentTraining.easyPace")
            except WorkoutDefinitionError:
                raise GenerationInputError(
                    "currentTraining.easyPace must use M:SS or M:SS-M:SS per km"
                ) from None
        return Pace(fast, slow)
    raw = _object(
        value,
        "currentTraining.easyPace",
        {"fastSecondsPerKm", "slowSecondsPerKm"},
    )
    if set(raw) != {"fastSecondsPerKm", "slowSecondsPerKm"}:
        raise GenerationInputError(
            "currentTraining.easyPace must contain fastSecondsPerKm and slowSecondsPerKm"
        )
    fast = _number(raw["fastSecondsPerKm"], "currentTraining.easyPace.fastSecondsPerKm")
    slow = _number(raw["slowSecondsPerKm"], "currentTraining.easyPace.slowSecondsPerKm")
    assert fast is not None and slow is not None
    return Pace(fast, slow)


def _current_training(value: object) -> CurrentTraining:
    raw = _object(
        value,
        "currentTraining",
        {
            "averageWeeklyKm",
            "runDaysPerWeek",
            "longestRecentRun",
            "recent5KDurationMinutes",
            "easyPace",
        },
    )
    average = _number(raw.get("averageWeeklyKm"), "currentTraining.averageWeeklyKm")
    run_days = _integer(raw.get("runDaysPerWeek"), "currentTraining.runDaysPerWeek")
    recent_5k = _number(
        raw.get("recent5KDurationMinutes"),
        "currentTraining.recent5KDurationMinutes",
        optional=True,
    )
    assert average is not None and run_days is not None
    return CurrentTraining(
        average_weekly_km=average,
        run_days_per_week=run_days,
        longest_recent_run=_amount(raw.get("longestRecentRun"), "currentTraining.longestRecentRun"),
        recent_5k_duration=None if recent_5k is None else DurationMinutes(recent_5k),
        easy_pace=_easy_pace(raw.get("easyPace")),
    )


def _club_sessions(value: object) -> tuple[ClubSession, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise GenerationInputError("clubSessions must be an array")
    sessions = []
    for index, value_item in enumerate(value):
        field = f"clubSessions[{index}]"
        item = _object(value_item, field, {"weekday", "kind", "amount", "note"})
        sessions.append(
            ClubSession(
                weekday=_weekday(item.get("weekday"), f"{field}.weekday"),
                kind=_enum(item.get("kind"), ClubSessionKind, f"{field}.kind"),
                amount=_amount(item.get("amount"), f"{field}.amount"),
                note=_text(item.get("note"), f"{field}.note", optional=True),
            )
        )
    return tuple(sessions)


def _b_races(value: object) -> tuple[BRace, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise GenerationInputError("bRaces must be an array")
    races = []
    for index, value_item in enumerate(value):
        field = f"bRaces[{index}]"
        item = _object(value_item, field, {"date", "distanceKm", "intensity", "note"})
        distance = _number(item.get("distanceKm"), f"{field}.distanceKm")
        assert distance is not None
        races.append(
            BRace(
                date=_date(item.get("date"), f"{field}.date"),
                distance_km=distance,
                intensity=_enum(item.get("intensity"), RaceIntensity, f"{field}.intensity"),
                note=_text(item.get("note"), f"{field}.note", optional=True),
            )
        )
    return tuple(races)


def parse_first_10k_generation_request(payload: dict[str, Any]) -> First10KGenerationInput:
    """Convert the stable camelCase HTTP contract to typed domain input."""
    raw = _object(
        payload,
        "request",
        {
            "userId",
            "currentTraining",
            "mainRaceDate",
            "startWeek",
            "durationWeeks",
            "weekdays",
            "longRunDay",
            "clubSessions",
            "bRaces",
            "maximumWeeklyKm",
            "maximumLongRunKm",
            "progression",
            "trainingStyle",
            "qualityPreference",
            "qualitySessionsPerWeek",
            "additionalInstructions",
        },
    )
    raw_weekdays = raw.get("weekdays")
    if not isinstance(raw_weekdays, list):
        raise GenerationInputError("weekdays must be an array")
    progression = raw.get("progression", ProgressionProfile.BALANCED.value)
    legacy_quality = _integer(
        raw.get("qualitySessionsPerWeek"), "qualitySessionsPerWeek", optional=True
    )
    return First10KGenerationInput(
        current_training=_current_training(raw.get("currentTraining")),
        weekdays=tuple(
            _weekday(value, f"weekdays[{index}]") for index, value in enumerate(raw_weekdays)
        ),
        long_run_day=_weekday(raw.get("longRunDay"), "longRunDay", optional=True),
        main_race_date=_date(raw.get("mainRaceDate"), "mainRaceDate", optional=True),
        club_sessions=_club_sessions(raw.get("clubSessions")),
        b_races=_b_races(raw.get("bRaces")),
        start_week=_date(raw.get("startWeek"), "startWeek", optional=True),
        duration_weeks=_integer(raw.get("durationWeeks"), "durationWeeks", optional=True),
        maximum_weekly_km=_number(raw.get("maximumWeeklyKm"), "maximumWeeklyKm", optional=True),
        maximum_long_run_km=_number(raw.get("maximumLongRunKm"), "maximumLongRunKm", optional=True),
        progression=_enum(progression, ProgressionProfile, "progression"),
        training_style=_enum(
            raw.get("trainingStyle", TrainingStyle.AUTO.value), TrainingStyle, "trainingStyle"
        ),
        quality_preference=_enum(
            raw.get("qualityPreference", QualityPreference.AUTO.value),
            QualityPreference,
            "qualityPreference",
        ),
        quality_sessions_per_week=legacy_quality,
        additional_instructions=_text(
            raw.get("additionalInstructions"), "additionalInstructions", optional=True
        ),
    )


class WebProgramGenerationService:
    """Generate local drafts without persistence."""

    def __init__(
        self,
        users: UserRegistry,
        *,
        today: Callable[[], date] = date.today,
    ) -> None:
        self.users = users
        self.today = today
        self._use_case = GenerateFirst10KProgram()

    def generate(self, payload: dict[str, Any]) -> First10KProgramDraft:
        self.users.get(payload.get("userId"))
        request = parse_first_10k_generation_request(payload)
        return self._use_case.generate(request, today=self.today())


__all__ = [
    "WebProgramGenerationService",
    "parse_first_10k_generation_request",
]
