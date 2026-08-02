"""Placement of workouts within a week.

The placement step merges the day assignment, the volume plan, and the
variety pick into a concrete list of slots for one week. It also handles
the dates where a B race or the goal race replaces the planned workout.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from .days import WeekAssignment
from .inputs import BRace, ClubSession, GoalRace
from .phase import Phase, PhaseKind
from .workouts import (
    build_long_steady,
    build_race,
    easy_builder,
    easy_minutes_from_km,
    long_run_builder,
    quality_builder,
)


@dataclass(frozen=True, slots=True)
class Slot:
    """One day in a week with its assigned workout."""

    day: int
    workout_id: str
    name: str
    description: str | None
    steps: tuple[dict, ...]
    long_run: bool = False
    quality: bool = False
    race: bool = False

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.workout_id,
            "day": self.day,
            "name": self.name,
            "steps": list(self.steps),
        }
        if self.description:
            result["description"] = self.description
        return result


def _slot_id(week_number: int, day: int, role: str) -> str:
    """Return a stable workout id derived from week, day, and role."""
    return f"week-{week_number:02d}-{role}-{day}"


def _place_long_run(
    week_number: int,
    day: int,
    long_run_km: float,
    style: str,
    pace: list[str] | None,
) -> Slot:
    steps = long_run_builder(style, long_run_km, pace)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "long"),
        name="Long run",
        description=(
            None if pace is None else f"Run {long_run_km:.1f} km at an easy, conversational pace."
        ),
        steps=tuple(steps),
        long_run=True,
    )


def _place_quality(
    week_number: int,
    day: int,
    style: str,
    pace: list[str] | None,
    phase: PhaseKind,
) -> Slot:
    name, steps = quality_builder(style, pace, week_number, phase)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "quality"),
        name=name,
        description=("Run the work intervals at a controlled effort and jog the recoveries."),
        steps=tuple(steps),
        quality=True,
    )


def _place_easy(
    week_number: int,
    day: int,
    target_km: float,
    style: str,
) -> Slot:
    if target_km <= 1.5:
        minutes = max(15, easy_minutes_from_km(target_km))
        steps = [
            {"warmup": "5m"},
            {"run": {"time": f"{minutes}m"}},
            {"cooldown": "5m"},
        ]
        return Slot(
            day=day,
            workout_id=_slot_id(week_number, day, "easy"),
            name="Recovery run",
            description="Run very easily and walk when the effort rises.",
            steps=tuple(steps),
        )
    steps = easy_builder(style, target_km)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "easy"),
        name="Easy run",
        description=("Run at an easy, conversational pace. Walk recoveries are fine."),
        steps=tuple(steps),
    )


def _place_race(
    week_number: int,
    day: int,
    race_distance_km: float,
    race_kind: str,
) -> Slot:
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "race"),
        name="Goal 10K" if race_kind == "goal" else "Race",
        description=("Hold an even effort from start to finish. Walk breaks are allowed."),
        steps=tuple(build_race(race_distance_km)),
        race=True,
    )


def _slot_for_club(
    week_number: int,
    day: int,
    club: ClubSession,
) -> Slot:
    if club.distance_km is not None:
        steps = build_long_steady(club.distance_km, None)
    else:
        minutes = int(club.duration_minutes or 30)
        steps = [
            {"warmup": "5m"},
            {"run": {"time": f"{minutes}m"}},
            {"cooldown": "5m"},
        ]
    note = club.note or "Club session."
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "club"),
        name="Club session",
        description=note,
        steps=tuple(steps),
    )


def _place_b_race(
    week_number: int,
    day: int,
    race: BRace,
) -> Slot:
    if race.intensity in ("all-out", "controlled"):
        steps = build_race(race.distance_km)
    else:
        steps = build_long_steady(race.distance_km, None)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "b-race"),
        name="B race",
        description=race.note or "Treat as a hard effort and recover afterwards.",
        steps=tuple(steps),
        race=True,
    )


def place_week(
    week_number: int,
    week_start: date,
    assignment: WeekAssignment,
    long_run_km: float,
    weekly_km: float,
    long_run_style: str,
    quality_style: str,
    quality_per_week: int,
    easy_style: str,
    pace: list[str] | None,
    phase: Phase,
    club_sessions: tuple[ClubSession, ...],
    b_races: tuple[BRace, ...],
    goal_race: GoalRace,
    goal_race_day: int | None = None,
) -> tuple[Slot, ...]:
    """Return the slots for one program week."""
    slots: list[Slot] = []
    consumed_days: set[int] = set()
    consumed_kinds: set[str] = set()

    if goal_race.date is not None and goal_race_day is not None:
        slots.append(_place_race(week_number, goal_race_day, 10.0, "goal"))
        consumed_days.add(goal_race_day)
        if goal_race_day == assignment.long_run_day:
            consumed_kinds.add("long")

    for race in b_races:
        race_day = _weekday_for_date(week_start, race.date)
        if race_day is None or race_day in consumed_days:
            continue
        slots.append(_place_b_race(week_number, race_day, race))
        consumed_days.add(race_day)
        if race_day is not None:
            consumed_kinds.add(_club_role_for(assignment, race_day))

    for club in club_sessions:
        if club.weekday in consumed_days:
            continue
        slots.append(_slot_for_club(week_number, club.weekday, club))
        consumed_days.add(club.weekday)
        consumed_kinds.add(_club_role_for(assignment, club.weekday))

    if "long" not in consumed_kinds:
        slots.append(
            _place_long_run(week_number, assignment.long_run_day, long_run_km, long_run_style, pace)
        )
        consumed_days.add(assignment.long_run_day)

    if (
        quality_per_week >= 1
        and assignment.quality_day is not None
        and "quality" not in consumed_kinds
    ):
        if assignment.quality_day not in consumed_days:
            slots.append(
                _place_quality(
                    week_number,
                    assignment.quality_day,
                    quality_style,
                    pace,
                    phase.kind,
                )
            )
            consumed_days.add(assignment.quality_day)

    remaining_km = max(0.0, weekly_km - long_run_km)
    easy_count = sum(1 for day in assignment.easy_days if day not in consumed_days)
    for day in assignment.easy_days:
        if day in consumed_days:
            continue
        share = remaining_km / easy_count if easy_count else 0.0
        slots.append(_place_easy(week_number, day, share, easy_style))
        consumed_days.add(day)
        easy_count -= 1

    slots.sort(key=lambda slot: slot.day)
    return tuple(slots)


def _club_role_for(assignment: WeekAssignment, day: int) -> str:
    if day == assignment.long_run_day:
        return "long"
    if day == assignment.quality_day:
        return "quality"
    return "easy"


def _date_for_day(week_start: date, day: int) -> date:
    from datetime import timedelta

    return week_start + timedelta(days=day - 1)


def _weekday_for_date(week_start: date, target: date) -> int | None:
    delta = (target - week_start).days
    if not 0 <= delta < 7:
        return None
    return delta + 1


__all__ = ["Slot", "place_week"]
