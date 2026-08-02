"""Typed input model for the first 10K generator.

The datatypes are immutable so the pure composition functions never mutate
caller state. Validation happens through ``__post_init__`` and raises
``GenerationError`` instead of generic ``ValueError`` so callers can
distinguish generator errors from domain errors.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any, Literal

from .errors import GenerationError

ProgressionProfile = Literal["cautious", "balanced", "ambitious"]
ClubSessionType = Literal["easy", "long", "quality", "unknown"]
BRaceIntensity = Literal["all-out", "controlled", "training-run"]

DEFAULT_PROGRESSION: ProgressionProfile = "balanced"
DEFAULT_SESSIONS_PER_WEEK = 3
DEFAULT_DURATION_WEEKS = 12
DEFAULT_START_WEEK = "next"
MIN_DURATION_WEEKS = 8
MAX_DURATION_WEEKS = 16
MIN_SESSIONS_PER_WEEK = 2
MAX_SESSIONS_PER_WEEK = 7
MIN_REST_DAYS = 1
MAX_REST_DAYS = 5
MIN_WEEK_KM = 0.0
MIN_LONG_RUN_KM = 4.0
MIN_QUALITY_SESSIONS = 0
MAX_QUALITY_SESSIONS = 1
DAY_NUMBERS: tuple[int, ...] = (1, 2, 3, 4, 5, 6, 7)


@dataclass(frozen=True, slots=True)
class TrainingDays:
    """The pool of weekdays the generator can choose from.

    ``possible_days`` lists the weekdays the user CAN run on. The generator
    picks ``sessions_per_week`` days from the pool each week and varies the
    choice so the program feels fresh. The user can hand-edit the result in
    the existing Runplan editor if they want to lock a specific day.
    """

    possible_days: tuple[int, ...]
    sessions_per_week: int

    def __post_init__(self) -> None:
        cleaned = tuple(sorted(set(self.possible_days)))
        if not cleaned:
            raise GenerationError("possible_days must contain at least one weekday")
        for day in cleaned:
            if not isinstance(day, int) or not 1 <= day <= 7:
                raise GenerationError(f"possible_days: {day!r} is not a weekday 1-7")
        if not MIN_SESSIONS_PER_WEEK <= self.sessions_per_week <= MAX_SESSIONS_PER_WEEK:
            raise GenerationError(
                f"sessions_per_week must be {MIN_SESSIONS_PER_WEEK}-"
                f"{MAX_SESSIONS_PER_WEEK}, got {self.sessions_per_week}"
            )
        if self.sessions_per_week > len(cleaned):
            raise GenerationError(
                f"sessions_per_week ({self.sessions_per_week}) cannot exceed the "
                f"number of possible_days ({len(cleaned)})"
            )
        object.__setattr__(self, "possible_days", cleaned)


@dataclass(frozen=True, slots=True)
class GoalRace:
    """The goal race the program is built around.

    A ``None`` date means the program finishes with a 10K test run instead of
    a registered race. The race is always placed on its declared date and
    replaces whatever workout the generator would otherwise schedule there.
    """

    date: date | None = None

    def __post_init__(self) -> None:
        if self.date is not None and not isinstance(self.date, date):
            raise GenerationError(f"goal_race.date: {self.date!r} is not a date")


@dataclass(frozen=True, slots=True)
class BRace:
    """An intermediate race fed into the program."""

    date: date
    distance_km: float
    intensity: BRaceIntensity
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.date, date):
            raise GenerationError(f"b_race.date: {self.date!r} is not a date")
        if not isinstance(self.distance_km, (int, float)) or self.distance_km <= 0:
            raise GenerationError(f"b_race.distance_km must be positive, got {self.distance_km!r}")
        if self.intensity not in ("all-out", "controlled", "training-run"):
            raise GenerationError(
                f"b_race.intensity: {self.intensity!r} must be one of "
                "'all-out', 'controlled', 'training-run'"
            )
        if self.note is not None and not isinstance(self.note, str):
            raise GenerationError("b_race.note: must be text or None")


@dataclass(frozen=True, slots=True)
class ClubSession:
    """A recurring club session that occupies one weekday."""

    weekday: int
    type: ClubSessionType
    distance_km: float | None = None
    duration_minutes: float | None = None
    note: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.weekday, int) or not 1 <= self.weekday <= 7:
            raise GenerationError(f"club_session.weekday: {self.weekday!r} is not 1-7")
        if self.type not in ("easy", "long", "quality", "unknown"):
            raise GenerationError(
                f"club_session.type: {self.type!r} must be one of "
                "'easy', 'long', 'quality', 'unknown'"
            )
        if self.distance_km is not None and (
            not isinstance(self.distance_km, (int, float)) or self.distance_km <= 0
        ):
            raise GenerationError("club_session.distance_km must be positive or None")
        if self.duration_minutes is not None and (
            not isinstance(self.duration_minutes, (int, float)) or self.duration_minutes <= 0
        ):
            raise GenerationError("club_session.duration_minutes must be positive or None")
        if self.distance_km is None and self.duration_minutes is None:
            raise GenerationError(
                "club_session: specify at least one of distance_km or duration_minutes"
            )
        if self.note is not None and not isinstance(self.note, str):
            raise GenerationError("club_session.note: must be text or None")


@dataclass(frozen=True, slots=True)
class GeneratorRequest:
    """The complete input to the first 10K generator.

    The defaults produce a 12-week, three-day program for a runner with no
    declared history. Callers can override any field. The generator never
    invents pace data; callers must pass ``known_easy_pace_sec`` if they want
    pace targets on quality sessions.
    """

    start_week: str | None = None
    duration_weeks: int = DEFAULT_DURATION_WEEKS
    goal_race: GoalRace = field(default_factory=GoalRace)
    current_weekly_km: float = 0.0
    current_longest_km: float | None = None
    training_days: TrainingDays = field(
        default_factory=lambda: TrainingDays(
            possible_days=(1, 2, 3, 4, 5, 6, 7),
            sessions_per_week=DEFAULT_SESSIONS_PER_WEEK,
        )
    )
    preferred_long_run_day: int | None = None
    progression: ProgressionProfile = DEFAULT_PROGRESSION
    quality_sessions_per_week: int = MIN_QUALITY_SESSIONS
    club_sessions: tuple[ClubSession, ...] = ()
    b_races: tuple[BRace, ...] = ()
    known_easy_pace_sec: tuple[int, int] | None = None
    max_weekly_km: float | None = None
    max_long_run_km: float | None = None

    def __post_init__(self) -> None:
        if self.start_week is not None and not isinstance(self.start_week, str):
            raise GenerationError("start_week must be a string in YYYY-Www format or None")
        if not MIN_DURATION_WEEKS <= self.duration_weeks <= MAX_DURATION_WEEKS:
            raise GenerationError(
                f"duration_weeks must be {MIN_DURATION_WEEKS}-"
                f"{MAX_DURATION_WEEKS}, got {self.duration_weeks}"
            )
        if not isinstance(self.current_weekly_km, (int, float)) or self.current_weekly_km < 0:
            raise GenerationError("current_weekly_km must be >= 0")
        if self.current_longest_km is not None and (
            not isinstance(self.current_longest_km, (int, float)) or self.current_longest_km <= 0
        ):
            raise GenerationError("current_longest_km must be positive or None")
        if self.preferred_long_run_day is not None and not (
            isinstance(self.preferred_long_run_day, int) and 1 <= self.preferred_long_run_day <= 7
        ):
            raise GenerationError("preferred_long_run_day must be 1-7 or None")
        if self.progression not in ("cautious", "balanced", "ambitious"):
            raise GenerationError(
                f"progression: {self.progression!r} must be cautious, balanced, or ambitious"
            )
        if not MIN_QUALITY_SESSIONS <= self.quality_sessions_per_week <= MAX_QUALITY_SESSIONS:
            raise GenerationError(
                f"quality_sessions_per_week must be {MIN_QUALITY_SESSIONS}-"
                f"{MAX_QUALITY_SESSIONS}, got {self.quality_sessions_per_week}"
            )
        if self.known_easy_pace_sec is not None:
            pace = self.known_easy_pace_sec
            if (
                not isinstance(pace, tuple)
                or len(pace) != 2
                or not all(isinstance(p, int) and p > 0 for p in pace)
                or pace[0] > pace[1]
            ):
                raise GenerationError(
                    "known_easy_pace_sec must be a (fast, slow) tuple of positive seconds"
                )
        if self.max_weekly_km is not None and (
            not isinstance(self.max_weekly_km, (int, float)) or self.max_weekly_km <= 0
        ):
            raise GenerationError("max_weekly_km must be positive or None")
        if self.max_long_run_km is not None and (
            not isinstance(self.max_long_run_km, (int, float)) or self.max_long_run_km <= 0
        ):
            raise GenerationError("max_long_run_km must be positive or None")
        if self.goal_race.date is not None and self.start_week is None:
            # Runplan needs a concrete start. The compose step normalises this.
            object.__setattr__(self, "start_week", "next")
        if not isinstance(self.club_sessions, tuple):
            raise GenerationError("club_sessions must be a tuple")
        if not isinstance(self.b_races, tuple):
            raise GenerationError("b_races must be a tuple")
        for club in self.club_sessions:
            if not isinstance(club, ClubSession):
                raise GenerationError("club_sessions must contain ClubSession instances")
        for race in self.b_races:
            if not isinstance(race, BRace):
                raise GenerationError("b_races must contain BRace instances")


def suggest_start_week(today: date) -> str:
    """Return the ISO week label of the Monday following ``today``."""
    monday = today + timedelta(days=(7 - today.weekday()) % 7)
    if monday <= today:
        monday = monday + timedelta(days=7)
    iso_year, iso_week, _ = monday.isocalendar()
    return f"{iso_year:04d}-W{iso_week:02d}"


def race_date_window(start_week: str, duration_weeks: int, race: date) -> bool:
    """Return True if ``race`` falls inside the program window."""
    from ..parsing.yaml_loader import parse_iso_week

    _, start = parse_iso_week(start_week)
    end = start + timedelta(days=duration_weeks * 7 - 1)
    return start <= race <= end


def as_dict(request: GeneratorRequest) -> dict[str, Any]:
    """Return a JSON-serialisable summary used in diagnostics."""
    return {
        "start_week": request.start_week,
        "duration_weeks": request.duration_weeks,
        "goal_race_date": request.goal_race.date.isoformat() if request.goal_race.date else None,
        "current_weekly_km": request.current_weekly_km,
        "current_longest_km": request.current_longest_km,
        "training_days": {
            "possible_days": list(request.training_days.possible_days),
            "sessions_per_week": request.training_days.sessions_per_week,
        },
        "progression": request.progression,
        "quality_sessions_per_week": request.quality_sessions_per_week,
        "max_weekly_km": request.max_weekly_km,
        "max_long_run_km": request.max_long_run_km,
        "club_sessions": [
            {
                "weekday": c.weekday,
                "type": c.type,
                "distance_km": c.distance_km,
                "duration_minutes": c.duration_minutes,
                "note": c.note,
            }
            for c in request.club_sessions
        ],
        "b_races": [
            {
                "date": r.date.isoformat(),
                "distance_km": r.distance_km,
                "intensity": r.intensity,
                "note": r.note,
            }
            for r in request.b_races
        ],
    }


__all__ = [
    "BRace",
    "BRaceIntensity",
    "ClubSession",
    "ClubSessionType",
    "DEFAULT_DURATION_WEEKS",
    "DEFAULT_PROGRESSION",
    "DEFAULT_SESSIONS_PER_WEEK",
    "GoalRace",
    "GeneratorRequest",
    "MAX_DURATION_WEEKS",
    "MAX_QUALITY_SESSIONS",
    "MAX_SESSIONS_PER_WEEK",
    "MIN_DURATION_WEEKS",
    "MIN_QUALITY_SESSIONS",
    "MIN_SESSIONS_PER_WEEK",
    "ProgressionProfile",
    "TrainingDays",
    "as_dict",
    "race_date_window",
    "suggest_start_week",
]
