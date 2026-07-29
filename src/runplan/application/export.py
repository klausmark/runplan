"""Renderer-independent program export use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..domain.estimates import DEFAULT_PACE_SECONDS_PER_KM, estimate_steps
from ..domain.models import Program, Step
from ..domain.selectors import WeekSelection
from .presentation_weeks import build_presentation_weeks, presentation_start

SUMMARY_ASSUMED_PACE_SECONDS_PER_KM = DEFAULT_PACE_SECONDS_PER_KM


@dataclass(frozen=True, slots=True)
class ExportWorkout:
    id: str
    date: date
    name: str
    description: str | None
    steps: tuple[Step, ...]
    source_week: int
    source_day: int
    source_name: str
    status: str
    estimated_duration_seconds: float
    estimated_distance_meters: float
    effective_duration_seconds: float
    effective_distance_meters: float
    totals_are_actual: bool


@dataclass(frozen=True, slots=True)
class ExportSummary:
    workout_count: int
    estimated_duration_seconds: float
    estimated_distance_meters: float


@dataclass(frozen=True, slots=True)
class ExportWeek:
    number: int
    start_date: date
    end_date: date
    focus: str | None
    workouts: tuple[ExportWorkout, ...]
    summary: ExportSummary


@dataclass(frozen=True, slots=True)
class ProgramExport:
    id: str
    name: str
    short_name: str
    description: str | None
    start_date: date
    start_week: str
    total_weeks: int
    selected_week_count: int
    weeks: tuple[ExportWeek, ...]
    summary: ExportSummary


def _summary(
    workouts: tuple[ExportWorkout, ...], fallback_pace_seconds_per_km: float
) -> ExportSummary:
    return ExportSummary(
        workout_count=len(workouts),
        estimated_duration_seconds=sum(item.effective_duration_seconds for item in workouts),
        estimated_distance_meters=sum(item.effective_distance_meters for item in workouts),
    )


def build_program_export(
    program: Program,
    selection: WeekSelection,
    *,
    today: date | None = None,
    fallback_pace_seconds_per_km: float = SUMMARY_ASSUMED_PACE_SECONDS_PER_KM,
) -> ProgramExport:
    """Select weeks and build the common model consumed by every renderer."""
    presentation_weeks = build_presentation_weeks(program)
    selected = selection.resolve(
        tuple(week.number for week in presentation_weeks),
        start_date=presentation_start(program),
        today=today,
    )
    selected_weeks = tuple(week for week in presentation_weeks if week.number in selected)
    weeks = tuple(_export_week(week, fallback_pace_seconds_per_km) for week in selected_weeks)
    all_workouts = tuple(workout for week in weeks for workout in week.workouts)
    return ProgramExport(
        id=program.id,
        name=program.name,
        short_name=program.short_name,
        description=program.description,
        start_date=program.start_date,
        start_week=program.start_week,
        total_weeks=len(presentation_weeks),
        selected_week_count=len(weeks),
        weeks=weeks,
        summary=_summary(all_workouts, fallback_pace_seconds_per_km),
    )


def _export_week(week: object, fallback_pace: float) -> ExportWeek:
    workouts = tuple(_export_workout(item, fallback_pace) for item in week.workouts)
    return ExportWeek(
        number=week.number,
        start_date=week.start_date,
        end_date=week.end_date,
        focus=week.focus,
        workouts=workouts,
        summary=_summary(workouts, fallback_pace),
    )


def _export_workout(item: object, fallback_pace: float) -> ExportWorkout:
    workout = item.workout
    estimate = estimate_steps(workout.steps, fallback_pace)
    completed = (
        workout.status == "completed"
        and workout.actual_distance_meters is not None
        and workout.actual_duration_seconds is not None
    )
    terminal_zero = workout.status in ("missed", "retired")
    return ExportWorkout(
        id=workout.id,
        date=workout.schedule_date,
        name=item.name,
        description=workout.description,
        steps=workout.steps,
        source_week=item.source_week,
        source_day=item.source_day,
        source_name=item.source_name,
        status=workout.status,
        estimated_duration_seconds=estimate.duration_seconds,
        estimated_distance_meters=estimate.distance_meters,
        effective_duration_seconds=_effective_total(
            workout.actual_duration_seconds, estimate.duration_seconds, completed, terminal_zero
        ),
        effective_distance_meters=_effective_total(
            workout.actual_distance_meters, estimate.distance_meters, completed, terminal_zero
        ),
        totals_are_actual=completed,
    )


def _effective_total(actual: float | None, estimated: float, completed: bool, zero: bool) -> float:
    if completed:
        assert actual is not None
        return actual
    return 0.0 if zero else estimated


__all__ = [
    "ExportWeek",
    "ExportWorkout",
    "ExportSummary",
    "ProgramExport",
    "SUMMARY_ASSUMED_PACE_SECONDS_PER_KM",
    "build_program_export",
]
