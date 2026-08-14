"""Placement of workouts within a week.

The placement step merges the day assignment, the volume plan, and the
recipe variety pick into a concrete list of slots for one week. Races
and club sessions retain their raw builders because they are not recipe
candidates; long, quality, and easy slots instantiate through the
recipe catalogue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ..domain.models import Step
from ..domain.recipes import RecipeParameters, WorkoutRecipe
from ..parsing.yaml_models import build_step
from .days import WeekAssignment
from .inputs import BRace, ClubSession, GoalRace
from .phase import Phase, PhaseKind
from .recipe_dose import easy_dose, long_run_dose, quality_dose
from .workouts import build_long_steady, build_race


@dataclass(frozen=True, slots=True)
class Slot:
    """One day in a week with its assigned workout."""

    day: int
    workout_id: str
    name: str
    description: str | None
    steps: tuple[Step, ...]
    long_run: bool = False
    quality: bool = False
    race: bool = False
    recipe_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {
            "id": self.workout_id,
            "day": self.day,
            "name": self.name,
            "steps": [_step_to_dict(step) for step in self.steps],
        }
        if self.description:
            result["description"] = self.description
        return result


def _step_to_dict(step: Step) -> dict[str, Any]:
    """Render a :class:`Step` as a raw dict for snapshot comparisons."""
    if step.action == "repeat":
        return {
            "repeat": {
                "count": step.count,
                "steps": [_step_to_dict(child) for child in step.steps],
            }
        }
    payload: dict[str, Any] = {step.action: {}}
    if step.end_kind == "time":
        payload[step.action]["time"] = f"{int(step.end_value // 60)}m{int(step.end_value % 60)}s"
    elif step.end_kind == "distance":
        payload[step.action]["distance"] = f"{int(step.end_value)}m"
    if step.pace:
        fast, slow = step.pace
        fast_min, fast_sec = divmod(int(fast), 60)
        slow_min, slow_sec = divmod(int(slow), 60)
        if fast == slow:
            payload[step.action]["pace"] = f"{fast_min}:{fast_sec:02d} min/km"
        else:
            payload[step.action]["pace"] = (
                f"{fast_min}:{fast_sec:02d}-{slow_min}:{slow_sec:02d} min/km"
            )
    return payload


def _slot_id(week_number: int, day: int, role: str) -> str:
    """Return a stable workout id derived from week, day, and role."""
    return f"week-{week_number:02d}-{role}-{day}"


def _place_long_run(
    week_number: int,
    day: int,
    long_run_km: float,
    recipe: WorkoutRecipe,
    easy_pace_sec_per_km: list[Any] | None,
) -> Slot:
    params = long_run_dose(
        recipe,
        target_km=long_run_km,
        easy_pace_sec_per_km=tuple(easy_pace_sec_per_km or ())
        if easy_pace_sec_per_km is not None
        else None,
    )
    pair = recipe.instantiate(params)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "long"),
        name=pair.workout.name,
        description=pair.workout.description,
        steps=tuple(pair.workout.steps),
        long_run=True,
        recipe_key=recipe.key,
    )


def _place_quality(
    week_number: int,
    day: int,
    recipe: WorkoutRecipe,
    easy_pace_sec_per_km: list[Any] | None,
    phase: Phase,
) -> Slot:
    recipe, params = _resolve_quality_recipe(
        recipe,
        week=week_number,
        phase=phase.kind,
        easy_pace_sec_per_km=easy_pace_sec_per_km,
    )
    pair = recipe.instantiate(params)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "quality"),
        name=pair.workout.name,
        description=pair.workout.description,
        steps=tuple(pair.workout.steps),
        quality=True,
        recipe_key=recipe.key,
    )


def _resolve_quality_recipe(
    recipe: WorkoutRecipe,
    *,
    week: int,
    phase: PhaseKind,
    easy_pace_sec_per_km: list[Any] | None,
) -> tuple[WorkoutRecipe, RecipeParameters]:
    """Return the recipe plus parameters that match its declared form.

    ``interval.track_1k`` collapses to a tempo recipe in the first few
    weeks of the program. The dose calculator returns tempo parameters
    in that case, so the helper swaps to the matching recipe instance
    before instantiation.
    """
    from ..domain.recipes import get_recipe

    params = quality_dose(
        recipe,
        week=week,
        phase=phase,
        easy_pace_sec_per_km=tuple(easy_pace_sec_per_km or ())
        if easy_pace_sec_per_km is not None
        else None,
    )
    if type(params).__name__ == recipe.parameters_type.__name__:
        return recipe, params
    swapped_key = _recipe_key_for_params(type(params).__name__)
    return get_recipe(swapped_key), params


def _recipe_key_for_params(parameters_type_name: str) -> str:
    """Map recipe parameter type names back to their recipe keys."""
    return {
        "ContinuousTempoParameters": "tempo.continuous",
        "CruiseIntervalsParameters": "tempo.cruise_intervals",
        "Track400mParameters": "interval.track_400m",
        "Track1kParameters": "interval.track_1k",
        "HillRepeatsParameters": "interval.hill_repeats",
        "FartlekParameters": "interval.fartlek",
    }.get(parameters_type_name, "tempo.continuous")


def _place_easy(
    week_number: int,
    day: int,
    target_km: float,
    recipe: WorkoutRecipe,
) -> Slot:
    params = easy_dose(recipe, target_km=target_km)
    pair = recipe.instantiate(params)
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "easy"),
        name=pair.workout.name,
        description=pair.workout.description,
        steps=tuple(pair.workout.steps),
        recipe_key=recipe.key,
    )


def _place_race(
    week_number: int,
    day: int,
    race_distance_km: float,
    race_kind: str,
) -> Slot:
    raw = build_race(race_distance_km)
    steps = tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "race"),
        name="Goal 10K" if race_kind == "goal" else "Race",
        description=("Hold an even effort from start to finish. Walk breaks are allowed."),
        steps=steps,
        race=True,
    )


def _slot_for_club(
    week_number: int,
    day: int,
    club: ClubSession,
) -> Slot:
    if club.distance_km is not None:
        raw = build_long_steady(club.distance_km, None)
    else:
        minutes = int(club.duration_minutes or 30)
        raw = [
            {"warmup": "5m"},
            {"run": {"time": f"{minutes}m"}},
            {"cooldown": "5m"},
        ]
    steps = tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))
    note = club.note or "Club session."
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "club"),
        name="Club session",
        description=note,
        steps=steps,
    )


def _place_b_race(
    week_number: int,
    day: int,
    race: BRace,
) -> Slot:
    if race.intensity in ("all-out", "controlled"):
        raw = build_race(race.distance_km)
    else:
        raw = build_long_steady(race.distance_km, None)
    steps = tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))
    return Slot(
        day=day,
        workout_id=_slot_id(week_number, day, "b-race"),
        name="B race",
        description=race.note or "Treat as a hard effort and recover afterwards.",
        steps=steps,
        race=True,
    )


def place_week(
    week_number: int,
    week_start: date,
    assignment: WeekAssignment,
    long_run_km: float,
    weekly_km: float,
    long_recipe: WorkoutRecipe,
    quality_recipe: WorkoutRecipe,
    easy_recipe: WorkoutRecipe,
    quality_per_week: int,
    easy_pace_sec_per_km: list[Any] | None,
    phase: Phase,
    club_sessions: tuple[ClubSession, ...],
    b_races: tuple[BRace, ...],
    goal_race: GoalRace,
    goal_race_day: int | None = None,
    test_run_day: int | None = None,
) -> tuple[Slot, ...]:
    """Return the slots for one program week.

    When ``test_run_day`` is set, a 10K test run replaces the long run on
    that day. The test run takes priority over a normal long run but yields
    to a registered goal race, club session, or B race on the same date.
    """
    slots: list[Slot] = []
    consumed_days: set[int] = set()
    consumed_kinds: set[str] = set()

    if goal_race.date is not None and goal_race_day is not None:
        slots.append(_place_race(week_number, goal_race_day, 10.0, "goal"))
        consumed_days.add(goal_race_day)
        if goal_race_day == assignment.long_run_day:
            consumed_kinds.add("long")

    if test_run_day is not None and test_run_day not in consumed_days:
        slots.append(_place_race(week_number, test_run_day, 10.0, "test"))
        consumed_days.add(test_run_day)
        if test_run_day == assignment.long_run_day:
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
            _place_long_run(
                week_number,
                assignment.long_run_day,
                long_run_km,
                long_recipe,
                easy_pace_sec_per_km,
            )
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
                    quality_recipe,
                    easy_pace_sec_per_km,
                    phase,
                )
            )
            consumed_days.add(assignment.quality_day)

    remaining_km = max(0.0, weekly_km - long_run_km)
    easy_count = sum(1 for day in assignment.easy_days if day not in consumed_days)
    for day in assignment.easy_days:
        if day in consumed_days:
            continue
        share = remaining_km / easy_count if easy_count else 0.0
        slots.append(_place_easy(week_number, day, share, easy_recipe))
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
