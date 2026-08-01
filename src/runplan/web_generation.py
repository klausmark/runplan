"""Web-facing boundary for first 10K program generation."""

from __future__ import annotations

import logging
import math
import secrets
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from typing import Any

from .application.generate_first_10k import First10KProgramDraft, GenerateFirst10KProgram
from .application.ports import PlanGenerator
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
    RaceIntensity,
    TrainingAmount,
    Weekday,
)
from .parsing.values import parse_pace
from .users import UserRegistry

logger = logging.getLogger("runplan.web")
GENERATION_JOB_TTL_SECONDS = 15 * 60.0
GENERATION_PHASE_MESSAGES = {
    "queued": "Generation is queued.",
    "preparing": "Preparing the program outline.",
    "generating": "MiniMax is creating the workout details. This can take several minutes.",
    "validating": "Validating the generated program.",
    "repairing": "MiniMax is repairing the draft after validation.",
    "complete": "Program ready.",
    "failed": "Program generation failed.",
}


class GenerationBusyError(RuntimeError):
    """Raised when the same user already has an active generation request."""


class GenerationJobNotFoundError(LookupError):
    """Raised when a generation job is absent, expired, or belongs to another user."""


@dataclass(frozen=True, slots=True)
class GenerationJobSnapshot:
    id: str
    user_id: str
    status: str
    phase: str
    message: str
    elapsed_seconds: int
    draft: First10KProgramDraft | None = None
    error: Exception | None = None


@dataclass(slots=True)
class _GenerationJob:
    id: str
    user_id: str
    status: str
    phase: str
    created_at: float
    finished_at: float | None = None
    draft: First10KProgramDraft | None = None
    error: Exception | None = None


def _start_daemon_worker(operation: Callable[[], None]) -> None:
    threading.Thread(target=operation, name="runplan-program-generation", daemon=True).start()


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
            "qualitySessionsPerWeek",
            "additionalInstructions",
        },
    )
    raw_weekdays = raw.get("weekdays")
    if not isinstance(raw_weekdays, list):
        raise GenerationInputError("weekdays must be an array")
    progression = raw.get("progression", ProgressionProfile.BALANCED.value)
    quality = _integer(raw.get("qualitySessionsPerWeek", 0), "qualitySessionsPerWeek")
    assert quality is not None
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
        quality_sessions_per_week=quality,
        additional_instructions=_text(
            raw.get("additionalInstructions"), "additionalInstructions", optional=True
        ),
    )


class WebProgramGenerationService:
    """Generate drafts with per-user exclusion and no persistence dependency."""

    def __init__(
        self,
        generator: PlanGenerator,
        users: UserRegistry,
        *,
        today: Callable[[], date] = date.today,
        configured: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
        start_worker: Callable[[Callable[[], None]], None] = _start_daemon_worker,
        job_ttl_seconds: float = GENERATION_JOB_TTL_SECONDS,
    ) -> None:
        if job_ttl_seconds <= 0:
            raise ValueError("generation job TTL must be greater than zero")
        self.users = users
        self.today = today
        self._use_case = GenerateFirst10KProgram(generator)
        self._configured = (
            bool(getattr(generator, "configured", True)) if configured is None else configured
        )
        self._clock = clock
        self._start_worker = start_worker
        self._job_ttl_seconds = job_ttl_seconds
        self._locks: dict[str, threading.Lock] = {}
        self._locks_guard = threading.Lock()
        self._jobs: dict[str, _GenerationJob] = {}
        self._jobs_guard = threading.Lock()

    @property
    def configured(self) -> bool:
        return self._configured

    def generate(self, payload: dict[str, Any]) -> First10KProgramDraft:
        user = self.users.get(payload.get("userId"))
        request = parse_first_10k_generation_request(payload)
        lock = self._acquire_user_lock(user.id)
        try:
            return self._use_case.generate(request, today=self.today())
        finally:
            lock.release()

    def start(self, payload: dict[str, Any]) -> GenerationJobSnapshot:
        user = self.users.get(payload.get("userId"))
        request = parse_first_10k_generation_request(payload)
        lock = self._acquire_user_lock(user.id)
        now = self._clock()
        job = _GenerationJob(
            id=secrets.token_urlsafe(24),
            user_id=user.id,
            status="running",
            phase="queued",
            created_at=now,
        )
        with self._jobs_guard:
            self._prune_jobs(now)
            self._jobs[job.id] = job
        logger.info("Program generation started user=%s job=%s", user.id, job.id)
        try:
            self._start_worker(lambda: self._run_job(job.id, request, lock))
        except BaseException:
            with self._jobs_guard:
                self._jobs.pop(job.id, None)
            lock.release()
            raise
        return self.get(job.id, user.id)

    def get(self, job_id: object, user_id: object) -> GenerationJobSnapshot:
        user = self.users.get(user_id)
        now = self._clock()
        with self._jobs_guard:
            self._prune_jobs(now)
            job = self._jobs.get(job_id) if isinstance(job_id, str) else None
            if job is None or job.user_id != user.id:
                raise GenerationJobNotFoundError("Program generation job not found")
            return self._snapshot(job, now)

    def _acquire_user_lock(self, user_id: str) -> threading.Lock:
        with self._locks_guard:
            lock = self._locks.setdefault(user_id, threading.Lock())
        if not lock.acquire(blocking=False):
            raise GenerationBusyError("Program generation is already running for this user")
        return lock

    def _run_job(
        self,
        job_id: str,
        request: First10KGenerationInput,
        lock: threading.Lock,
    ) -> None:
        try:
            draft = self._use_case.generate(
                request,
                today=self.today(),
                progress=lambda phase: self._update_phase(job_id, phase),
            )
        except Exception as exc:
            now = self._clock()
            with self._jobs_guard:
                job = self._jobs[job_id]
                job.status = "failed"
                job.phase = "failed"
                job.finished_at = now
                job.error = exc
            logger.error(
                "Program generation failed user=%s job=%s exception=%s",
                job.user_id,
                job.id,
                type(exc).__name__,
            )
        else:
            now = self._clock()
            with self._jobs_guard:
                job = self._jobs[job_id]
                job.status = "complete"
                job.phase = "complete"
                job.finished_at = now
                job.draft = draft
            logger.info(
                "Program generation completed user=%s job=%s elapsed_seconds=%d attempts=%d",
                job.user_id,
                job.id,
                max(0, int(now - job.created_at)),
                draft.attempt_count,
            )
        finally:
            lock.release()

    def _update_phase(self, job_id: str, phase: str) -> None:
        if phase not in GENERATION_PHASE_MESSAGES:
            raise ValueError("unknown program generation phase")
        with self._jobs_guard:
            job = self._jobs[job_id]
            job.phase = phase
        logger.info(
            "Program generation progress user=%s job=%s phase=%s", job.user_id, job.id, phase
        )

    def _prune_jobs(self, now: float) -> None:
        expired = [
            job_id
            for job_id, job in self._jobs.items()
            if job.finished_at is not None and now - job.finished_at >= self._job_ttl_seconds
        ]
        for job_id in expired:
            del self._jobs[job_id]

    @staticmethod
    def _snapshot(job: _GenerationJob, now: float) -> GenerationJobSnapshot:
        return GenerationJobSnapshot(
            id=job.id,
            user_id=job.user_id,
            status=job.status,
            phase=job.phase,
            message=GENERATION_PHASE_MESSAGES[job.phase],
            elapsed_seconds=max(0, int(now - job.created_at)),
            draft=job.draft,
            error=job.error,
        )


__all__ = [
    "GenerationBusyError",
    "GenerationJobNotFoundError",
    "GenerationJobSnapshot",
    "WebProgramGenerationService",
    "parse_first_10k_generation_request",
]
