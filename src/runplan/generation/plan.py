"""Compose the first 10K program from a request.

The compose function is the single entry point that combines every other
module. It returns a typed ``Program`` (the existing Runplan domain model)
so the plan can be previewed, exported, and synced through the existing
Studio flow without any new persistence path.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..domain.models import Program, Step, Week, Workout
from ..parsing.yaml_loader import parse_iso_week
from .days import assign_program
from .errors import GenerationError
from .inputs import GeneratorRequest, suggest_start_week
from .intensity import summarise_targets, target_for_phase
from .phase import PhaseKind, phase_for, phase_plan
from .placement import Slot, place_week
from .progression import VolumePlan, build_volume_plan
from .variety import (
    VarietyBoard,
    pick_easy_kind,
    pick_long_run_kind,
    pick_quality_kind,
)


@dataclass(frozen=True, slots=True)
class GeneratorResult:
    """The generator output plus diagnostics."""

    program: Program
    warnings: tuple[Any, ...]
    volume_plan: VolumePlan
    intensity_targets: tuple[Any, ...]
    variety_summary: dict[str, Any]

    def to_summary(self) -> dict[str, Any]:
        return {
            "weeks": len(self.program.weeks),
            "workouts": sum(len(week.workouts) for week in self.program.weeks),
            "total_km": round(self.volume_plan.total_km(), 1),
            "peak_km": round(self.volume_plan.peak_km(), 1),
            "variety": self.variety_summary,
            "intensity": self.intensity_targets_summary(),
        }

    def intensity_targets_summary(self) -> dict[str, float]:
        avg = summarise_targets(self.intensity_targets)
        return avg.as_dict()


def _normalise_start_week(
    request: GeneratorRequest,
    today: date,
) -> tuple[str, date]:
    """Return the canonical start-week label and the Monday of week 1."""
    if request.start_week is None or request.start_week == "next":
        return suggest_start_week(today), _monday_of_week(suggest_start_week(today))
    return request.start_week, _monday_of_week(request.start_week)


def _monday_of_week(week_label: str) -> date:
    label, monday = parse_iso_week(week_label)
    return monday


def _program_id_from_week(start_week: str) -> str:
    label, _ = parse_iso_week(start_week)
    return f"first-10k-{label.lower()}"


def compose_program(
    request: GeneratorRequest,
    today: date | None = None,
) -> GeneratorResult:
    """Build a complete first 10K program from ``request``."""
    if today is None:
        today = date.today()
    start_week, start_monday = _normalise_start_week(request, today)
    if request.goal_race.date is not None and not (
        start_monday
        <= request.goal_race.date
        <= start_monday + timedelta(days=request.duration_weeks * 7 - 1)
    ):
        raise GenerationError(
            "goal_race.date is outside the program window",
        )
    assignments = assign_program(
        request.training_days,
        request.duration_weeks,
        preferred_long_run_day=request.preferred_long_run_day,
        quality_per_week=request.quality_sessions_per_week,
    )
    phases = phase_plan(request.duration_weeks)
    volume_plan = build_volume_plan(
        duration_weeks=request.duration_weeks,
        current_weekly_km=request.current_weekly_km,
        current_longest_km=request.current_longest_km,
        sessions_per_week=request.training_days.sessions_per_week,
        profile=request.progression,
        max_weekly_km=request.max_weekly_km,
        max_long_run_km=request.max_long_run_km,
    )
    pace = _format_pace(request.known_easy_pace_sec)
    b_races_in_window = tuple(
        race
        for race in request.b_races
        if start_monday
        <= race.date
        <= start_monday + timedelta(days=request.duration_weeks * 7 - 1)
    )

    weeks: list[Week] = []
    intensity_targets: list[Any] = []
    variety = VarietyBoard()
    goal_race_day_in_program: int | None = None
    if request.goal_race.date is not None:
        delta = (request.goal_race.date - start_monday).days
        if 0 <= delta < request.duration_weeks * 7:
            goal_race_day_in_program = (delta % 7) + 1
    pool = request.training_days.possible_days
    test_run_day = pool[-1] if request.goal_race.date is None else None
    for week_index in range(request.duration_weeks):
        week_number = week_index + 1
        week_start = start_monday + timedelta(days=week_index * 7)
        assignment = assignments[week_index]
        phase = phase_for(phases, week_number)
        is_recovery = week_number in volume_plan.recovery_weeks
        is_taper = phase.kind is PhaseKind.TAPER

        long_style, variety = pick_long_run_kind(variety, week_index)
        quality_style, variety = pick_quality_kind(variety, week_index + 1)
        easy_style, variety = pick_easy_kind(variety, week_index + 2)

        is_race_week = (
            request.goal_race.date is not None
            and week_start <= request.goal_race.date <= week_start + timedelta(days=6)
        )
        is_final_week = week_index == request.duration_weeks - 1
        slots = place_week(
            week_number=week_number,
            week_start=week_start,
            assignment=assignment,
            long_run_km=volume_plan.long_run_km[week_index],
            weekly_km=volume_plan.weekly_km[week_index],
            long_run_style=long_style,
            quality_style=quality_style,
            quality_per_week=request.quality_sessions_per_week,
            easy_style=easy_style,
            pace=pace,
            phase=phase,
            club_sessions=request.club_sessions,
            b_races=b_races_in_window,
            goal_race=request.goal_race,
            goal_race_day=goal_race_day_in_program if is_race_week else None,
            test_run_day=test_run_day if (is_final_week and not is_race_week) else None,
        )

        workouts = tuple(_to_workout(slot, week_number) for slot in slots)
        focus = _focus_text(phase.kind, is_recovery, is_race_week)
        weeks.append(Week(number=week_number, focus=focus, workouts=workouts))
        intensity_targets.append(target_for_phase(phase.kind, is_recovery or is_taper))

    description = _description_text(request)
    program = Program(
        id=_program_id_from_week(start_week),
        name=_program_name(request, start_week),
        short_name="F10K",
        description=description,
        start_date=start_monday,
        start_week=start_week,
        weeks=tuple(weeks),
    )
    warnings = _build_warnings(request, volume_plan)
    return GeneratorResult(
        program=program,
        warnings=warnings,
        volume_plan=volume_plan,
        intensity_targets=tuple(intensity_targets),
        variety_summary=variety.summary_for_result()
        if hasattr(variety, "summary_for_result")
        else _summary_stats(variety),
    )


def _to_workout(slot: Slot, week_number: int) -> Workout:
    """Adapt a generated slot to the existing Runplan Workout model."""
    steps = tuple(_to_step(step) for step in slot.steps)
    return Workout(
        id=slot.workout_id,
        day=slot.day,
        name=slot.name,
        description=slot.description,
        steps=steps,
        schedule_date=date(1970, 1, 1),  # placeholder, replaced by parser
    )


def _to_step(step: dict) -> Step:
    """Convert a generated step dict to the domain Step dataclass."""
    from ..parsing.yaml_loader import load_program_model

    # Use the existing YAML loader to normalise a single-step program. This
    # guarantees the generated steps round-trip through the same parser.
    mini_program = {
        "program": {"id": "tmp", "name": "tmp", "short_name": "TMP", "start_week": "2026-W01"},
        "weeks": [
            {
                "week": 1,
                "workouts": [
                    {"id": "s1", "day": 1, "name": "s1", "steps": [step]},
                ],
            }
        ],
    }
    model = load_program_model(mini_program)
    return model.weeks[0].workouts[0].steps[0]


def _format_pace(known_easy_pace_sec: tuple[int, int] | None) -> list[str] | None:
    if known_easy_pace_sec is None:
        return None
    return [
        f"{known_easy_pace_sec[0] // 60}:{known_easy_pace_sec[0] % 60:02d}",
        f"{known_easy_pace_sec[1] // 60}:{known_easy_pace_sec[1] % 60:02d}",
    ]


def _summary_stats(board: VarietyBoard) -> dict[str, Any]:
    from .variety import summary_stats as _summary

    return _summary(board)


def _focus_text(phase: PhaseKind, recovery: bool, race_week: bool) -> str:
    if race_week:
        return "Race week: stay smooth, sleep, and trust the work."
    if phase is PhaseKind.FOUNDATION:
        return "Foundation: easy volume and short intervals to build rhythm."
    if phase is PhaseKind.BUILD:
        return "Build: introduce quality work and grow the long run."
    if phase is PhaseKind.PEAK:
        return "Peak: race-specific intensity and the longest run."
    if phase is PhaseKind.TAPER:
        return "Taper: reduce volume and keep one sharp session."
    if recovery:
        return "Recovery: shorter runs and lower intensity."
    return "Steady week"


def _program_name(request: GeneratorRequest, start_week: str) -> str:
    label = start_week
    distance = "10K"
    return f"First 10K - {label} ({distance})"


def _description_text(request: GeneratorRequest) -> str:
    base = (
        "Deterministic first 10K program generated from a typed request. "
        "The plan follows a soft pyramidal intensity distribution inspired by "
        "Knopp et al. (2024) and uses a four-week microcycle with a forced "
        "recovery week."
    )
    if request.goal_race.date is None:
        return base + " The final week ends with a 10K test run."
    return base + " The goal race is the 10K on " + request.goal_race.date.isoformat() + "."


def _build_warnings(request: GeneratorRequest, volume_plan: VolumePlan) -> tuple[Any, ...]:
    from .errors import GenerationWarning

    warnings: list[GenerationWarning] = []
    if request.current_weekly_km == 0:
        warnings.append(
            GenerationWarning(
                "no-history",
                "No current weekly volume was supplied. The first weeks use a "
                "cautious run/walk start.",
            )
        )
    if request.training_days.sessions_per_week < 3:
        warnings.append(
            GenerationWarning(
                "few-sessions",
                "Fewer than three sessions per week slows the 10K progression.",
            )
        )
    if request.training_days.sessions_per_week >= 5:
        warnings.append(
            GenerationWarning(
                "many-sessions",
                "Five or more sessions per week requires more recovery planning.",
            )
        )
    if request.known_easy_pace_sec is None:
        warnings.append(
            GenerationWarning(
                "no-pace",
                "No known easy pace was supplied. Quality workouts use "
                "effort-based descriptions only.",
            )
        )
    return tuple(warnings)


__all__ = ["GeneratorResult", "compose_program"]
