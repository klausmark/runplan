"""Calendar-aligned presentation weeks derived from source program coordinates."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta

from ..domain.models import Program, Workout


@dataclass(frozen=True, slots=True)
class PresentationWorkout:
    source_week: int
    source_day: int
    source_name: str
    name: str
    workout: Workout


@dataclass(frozen=True, slots=True)
class PresentationWeek:
    number: int
    start_date: date
    end_date: date
    focus: str | None
    workouts: tuple[PresentationWorkout, ...]


def presentation_start(program: Program) -> date:
    """Return the Monday anchoring presentation week one."""
    return program.start_date - timedelta(days=program.start_date.weekday())


def presentation_name(name: str) -> str:
    """Remove a conventional source-week prefix for user-facing output."""
    return re.sub(r"^Week\s+\d+\s+-\s*", "", name, count=1, flags=re.IGNORECASE)


def build_presentation_weeks(program: Program) -> tuple[PresentationWeek, ...]:
    """Group dated workouts into Monday-to-Sunday presentation weeks."""
    anchor = presentation_start(program)
    grouped: dict[int, list[PresentationWorkout]] = {}
    focuses: dict[int, list[str]] = {}
    for source_week in program.weeks:
        for workout in source_week.workouts:
            number = (workout.schedule_date - anchor).days // 7 + 1
            grouped.setdefault(number, []).append(
                PresentationWorkout(
                    source_week=source_week.number,
                    source_day=workout.day,
                    source_name=workout.name,
                    name=presentation_name(workout.name),
                    workout=workout,
                )
            )
            if source_week.focus and source_week.focus not in focuses.setdefault(number, []):
                focuses[number].append(source_week.focus)
    return tuple(
        PresentationWeek(
            number=number,
            start_date=anchor + timedelta(weeks=number - 1),
            end_date=anchor + timedelta(weeks=number - 1, days=6),
            focus=" / ".join(focuses.get(number, ())) or None,
            workouts=tuple(sorted(workouts, key=lambda item: item.workout.schedule_date)),
        )
        for number, workouts in sorted(grouped.items())
    )


__all__ = [
    "PresentationWeek",
    "PresentationWorkout",
    "build_presentation_weeks",
    "presentation_name",
    "presentation_start",
]
