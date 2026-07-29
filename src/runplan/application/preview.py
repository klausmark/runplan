"""Renderer-independent preview use case."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from ..domain.steps import estimate_totals
from .results import SyncPlan


@dataclass(frozen=True, slots=True)
class PreviewWorkout:
    id: str
    date: str
    name: str
    duration_seconds: float
    distance_meters: float
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class PreviewWeek:
    number: int
    start_date: str
    end_date: str
    workouts: tuple[PreviewWorkout, ...]


@dataclass(frozen=True, slots=True)
class PreviewResult:
    program_id: str
    weeks: tuple[PreviewWeek, ...]
    sync_plan: SyncPlan | None = None


def build_preview(
    selections: list[tuple[dict[str, Any], list[tuple[dict[str, Any], Any]]]],
    sync_plan: SyncPlan | None = None,
) -> PreviewResult:
    """Build a stable preview from selected, compiled program weeks.

    Structural rationale: workout, week, and total fields form one preview projection.
    """
    if not selections:
        raise ValueError("preview requires at least one selected week")
    grouped: dict[int, list[PreviewWorkout]] = {}
    for _program, compiled in selections:
        for definition, workout in compiled:
            known_duration, known_distance = estimate_totals(definition["steps"])
            grouped.setdefault(definition.get("presentation_week", _program["week"]), []).append(
                PreviewWorkout(
                    id=definition["id"],
                    date=definition["schedule_date"],
                    name=definition.get("presentation_name", workout.workoutName),
                    duration_seconds=definition.get(
                        "estimated_duration_seconds",
                        known_duration,
                    ),
                    distance_meters=definition.get(
                        "estimated_distance_meters",
                        known_distance,
                    ),
                    payload=workout.to_dict(),
                )
            )
    return PreviewResult(
        program_id=selections[0][0]["program_id"],
        weeks=tuple(
            PreviewWeek(
                number=number,
                start_date=(
                    date.fromisoformat(min(item.date for item in workouts))
                    - timedelta(
                        days=date.fromisoformat(min(item.date for item in workouts)).weekday()
                    )
                ).isoformat(),
                end_date=(
                    date.fromisoformat(min(item.date for item in workouts))
                    - timedelta(
                        days=date.fromisoformat(min(item.date for item in workouts)).weekday()
                    )
                    + timedelta(days=6)
                ).isoformat(),
                workouts=tuple(sorted(workouts, key=lambda item: item.date)),
            )
            for number, workouts in sorted(grouped.items())
        ),
        sync_plan=sync_plan,
    )


__all__ = ["PreviewResult", "PreviewWeek", "PreviewWorkout", "build_preview"]
