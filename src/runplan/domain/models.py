"""Integration-independent typed models for normalized running programs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Literal, Mapping


StepAction = Literal["warmup", "run", "recovery", "cooldown", "repeat"]
EndKind = Literal["time", "distance"]
WorkoutStatus = Literal["planned", "scheduled", "completed", "missed", "retired"]


@dataclass(frozen=True, slots=True)
class Step:
    """One regular step or a recursive repeat group."""

    action: StepAction
    end_kind: EndKind | None = None
    end_value: float | None = None
    pace: tuple[float, float] | None = None
    count: int | None = None
    steps: tuple[Step, ...] = ()

    def __post_init__(self) -> None:
        if self.action == "repeat":
            if self.count is None or self.count <= 0 or not self.steps:
                raise ValueError("repeat steps require a positive count and child steps")
            if self.end_kind is not None or self.end_value is not None or self.pace:
                raise ValueError("repeat steps cannot have an end condition or pace")
        elif self.end_kind is None or self.end_value is None or self.end_value <= 0:
            raise ValueError("regular steps require a positive end condition")
        elif self.count is not None or self.steps:
            raise ValueError("regular steps cannot contain repeat fields")

@dataclass(frozen=True, slots=True)
class Workout:
    id: str
    day: int
    name: str
    description: str | None
    steps: tuple[Step, ...]
    schedule_date: date
    status: WorkoutStatus = "planned"
    garmin_workout_id: int | None = None
    garmin_schedule_id: int | None = None
    activity_id: int | None = None
    completed_at: str | None = None
    actual_distance_meters: float | None = None
    actual_duration_seconds: float | None = None

    def with_lifecycle(self, record: Mapping[str, Any]) -> Workout:
        """Return this planned workout enriched from local synchronization state."""
        from dataclasses import replace

        return replace(
            self,
            status=record.get("status", self.status),
            garmin_workout_id=record.get("workout_id"),
            garmin_schedule_id=record.get("schedule_id"),
            activity_id=record.get("activity_id"),
            completed_at=record.get("completed_at"),
            actual_distance_meters=record.get("actual_distance_meters"),
            actual_duration_seconds=record.get("actual_duration_seconds"),
        )

@dataclass(frozen=True, slots=True)
class Week:
    number: int
    focus: str | None
    workouts: tuple[Workout, ...]


@dataclass(frozen=True, slots=True)
class Program:
    id: str
    name: str
    short_name: str
    description: str | None
    start_date: date
    start_week: str
    weeks: tuple[Week, ...]

    def week(self, number: int) -> Week:
        for week in self.weeks:
            if week.number == number:
                return week
        raise KeyError(f"program does not contain week {number}")


__all__ = [
    "EndKind",
    "Program",
    "Step",
    "StepAction",
    "Week",
    "Workout",
    "WorkoutStatus",
]
