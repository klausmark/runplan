"""Deterministic structure for first 10K program generation."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date, timedelta
from enum import Enum

from .generation_inputs import (
    BRace,
    ClubSession,
    ClubSessionKind,
    NormalizedFirst10KGenerationInput,
    RaceIntensity,
    Weekday,
)


class TrainingPhase(Enum):
    FOUNDATION = "foundation"
    BUILD = "build"
    CONSOLIDATION = "consolidation"
    TAPER = "taper"


class WorkoutIntent(Enum):
    EASY = "easy"
    LONG = "long"
    QUALITY = "quality"
    CLUB = "club"
    B_RACE = "b-race"
    GOAL_RACE = "goal-race"
    TEST_RUN = "test-run"


class WorkoutSource(Enum):
    BLUEPRINT = "blueprint"
    CLUB = "club"
    B_RACE = "b-race"
    MAIN_RACE = "main-race"
    TEST_RUN = "test-run"


@dataclass(frozen=True, slots=True)
class First10KBlueprint:
    """Versioned coaching policy metadata used to interpret an outline."""

    blueprint_id: str
    version: int
    goal: str
    intended_runner: str
    minimum_duration_weeks: int
    maximum_duration_weeks: int
    recommended_duration_weeks: tuple[int, int]
    consolidation_interval_weeks: int


FIRST_10K_BLUEPRINT = First10KBlueprint(
    blueprint_id="complete-first-10k",
    version=1,
    goal="Complete 10 kilometers",
    intended_runner="A runner preparing to complete their first 10K",
    minimum_duration_weeks=4,
    maximum_duration_weeks=52,
    recommended_duration_weeks=(8, 16),
    consolidation_interval_weeks=4,
)


@dataclass(frozen=True, slots=True)
class First10KWorkoutSlot:
    stable_id: str
    week_number: int
    date: date
    weekday: Weekday
    intent: WorkoutIntent
    source: WorkoutSource
    consumes_quality_capacity: bool = False
    club_session: ClubSession | None = None
    b_race: BRace | None = None


@dataclass(frozen=True, slots=True)
class First10KOutlineWeek:
    number: int
    start_date: date
    end_date: date
    phase: TrainingPhase
    workouts: tuple[First10KWorkoutSlot, ...]


@dataclass(frozen=True, slots=True)
class First10KOutline:
    blueprint: First10KBlueprint
    weeks: tuple[First10KOutlineWeek, ...]


def _phase_for_week(week_number: int, duration_weeks: int) -> TrainingPhase:
    if week_number == duration_weeks:
        return TrainingPhase.TAPER
    if duration_weeks == 2 or week_number == duration_weeks - 1:
        return TrainingPhase.CONSOLIDATION
    if (
        week_number % FIRST_10K_BLUEPRINT.consolidation_interval_weeks == 0
        and week_number < duration_weeks - 2
    ):
        return TrainingPhase.CONSOLIDATION

    foundation_weeks = max(1, duration_weeks // 4)
    if week_number <= foundation_weeks:
        return TrainingPhase.FOUNDATION
    return TrainingPhase.BUILD


def _slot(
    *,
    week_number: int,
    scheduled_date: date,
    intent: WorkoutIntent,
    source: WorkoutSource,
    consumes_quality_capacity: bool = False,
    club_session: ClubSession | None = None,
    b_race: BRace | None = None,
) -> First10KWorkoutSlot:
    return First10KWorkoutSlot(
        stable_id="",
        week_number=week_number,
        date=scheduled_date,
        weekday=Weekday(scheduled_date.isoweekday()),
        intent=intent,
        source=source,
        consumes_quality_capacity=consumes_quality_capacity,
        club_session=club_session,
        b_race=b_race,
    )


def _race_consumes_quality(race: BRace) -> bool:
    return race.intensity in (RaceIntensity.ALL_OUT, RaceIntensity.CONTROLLED)


def _make_room_for_race(
    slots_by_date: dict[date, First10KWorkoutSlot],
    race_date: date,
    *,
    preferred_intent: WorkoutIntent,
    maximum_slots: int,
) -> None:
    if race_date in slots_by_date or len(slots_by_date) < maximum_slots:
        return
    candidates = sorted(
        (
            slot
            for slot in slots_by_date.values()
            if slot.source not in (WorkoutSource.B_RACE, WorkoutSource.MAIN_RACE)
        ),
        key=lambda slot: (
            slot.source != WorkoutSource.BLUEPRINT,
            slot.intent != preferred_intent,
            abs((slot.date - race_date).days),
            slot.date,
        ),
    )
    if not candidates:
        raise ValueError("race insertion would replace an existing race")
    del slots_by_date[candidates[0].date]


def _remove_conflicting_club_quality(
    slots_by_date: dict[date, First10KWorkoutSlot], race_date: date
) -> None:
    for scheduled_date, slot in tuple(slots_by_date.items()):
        if (
            scheduled_date != race_date
            and slot.club_session is not None
            and slot.consumes_quality_capacity
        ):
            del slots_by_date[scheduled_date]


def _remove_goal_week_long_run(
    slots_by_date: dict[date, First10KWorkoutSlot], race_date: date
) -> None:
    for scheduled_date, slot in tuple(slots_by_date.items()):
        is_long = slot.intent == WorkoutIntent.LONG or (
            slot.club_session is not None and slot.club_session.kind == ClubSessionKind.LONG
        )
        if scheduled_date != race_date and is_long:
            del slots_by_date[scheduled_date]
            return


def _assign_stable_ids(
    week_number: int, slots: list[First10KWorkoutSlot]
) -> tuple[First10KWorkoutSlot, ...]:
    occurrences: dict[str, int] = {}
    result = []
    for slot in sorted(slots, key=lambda item: item.date):
        stem = f"w{week_number:02d}-{slot.weekday.name.lower()[:3]}-{slot.intent.value}"
        occurrences[stem] = occurrences.get(stem, 0) + 1
        suffix = f"-{occurrences[stem]}" if occurrences[stem] > 1 else ""
        result.append(replace(slot, stable_id=f"{stem}{suffix}"))
    return tuple(result)


def build_first_10k_outline(
    inputs: NormalizedFirst10KGenerationInput,
) -> First10KOutline:
    """Build an immutable outline without calculating workout load or content."""
    if not isinstance(inputs, NormalizedFirst10KGenerationInput):
        raise TypeError("inputs must be normalized first 10K generation input")

    club_by_weekday = {session.weekday: session for session in inputs.club_sessions}
    races_by_date = {race.date: race for race in inputs.b_races}
    duration = inputs.period.duration_weeks
    week_slots: list[list[First10KWorkoutSlot]] = []

    for week_index in range(duration):
        week_number = week_index + 1
        week_start = inputs.period.start_week + timedelta(weeks=week_index)
        slots_by_date: dict[date, First10KWorkoutSlot] = {}
        for weekday in inputs.weekdays:
            scheduled_date = week_start + timedelta(days=int(weekday) - 1)
            club = club_by_weekday.get(weekday)
            if club is not None:
                consumes_quality = club.kind in (
                    ClubSessionKind.QUALITY,
                    ClubSessionKind.UNKNOWN,
                )
                slots_by_date[scheduled_date] = _slot(
                    week_number=week_number,
                    scheduled_date=scheduled_date,
                    intent=WorkoutIntent.CLUB,
                    source=WorkoutSource.CLUB,
                    consumes_quality_capacity=consumes_quality,
                    club_session=club,
                )
            else:
                intent = (
                    WorkoutIntent.LONG if weekday == inputs.long_run_day else WorkoutIntent.EASY
                )
                slots_by_date[scheduled_date] = _slot(
                    week_number=week_number,
                    scheduled_date=scheduled_date,
                    intent=intent,
                    source=WorkoutSource.BLUEPRINT,
                )

        week_end = week_start + timedelta(days=6)
        for race_date, race in races_by_date.items():
            if race_date == inputs.main_race_date:
                continue
            if week_start <= race_date <= week_end:
                if _race_consumes_quality(race):
                    _remove_conflicting_club_quality(slots_by_date, race_date)
                _make_room_for_race(
                    slots_by_date,
                    race_date,
                    preferred_intent=WorkoutIntent.EASY,
                    maximum_slots=len(inputs.weekdays),
                )
                slots_by_date[race_date] = _slot(
                    week_number=week_number,
                    scheduled_date=race_date,
                    intent=WorkoutIntent.B_RACE,
                    source=WorkoutSource.B_RACE,
                    consumes_quality_capacity=_race_consumes_quality(race),
                    b_race=race,
                )

        if inputs.main_race_date is not None and week_start <= inputs.main_race_date <= week_end:
            _remove_conflicting_club_quality(slots_by_date, inputs.main_race_date)
            _remove_goal_week_long_run(slots_by_date, inputs.main_race_date)
            _make_room_for_race(
                slots_by_date,
                inputs.main_race_date,
                preferred_intent=WorkoutIntent.LONG,
                maximum_slots=len(inputs.weekdays),
            )
            slots_by_date[inputs.main_race_date] = _slot(
                week_number=week_number,
                scheduled_date=inputs.main_race_date,
                intent=WorkoutIntent.GOAL_RACE,
                source=WorkoutSource.MAIN_RACE,
                consumes_quality_capacity=True,
            )
        elif inputs.main_race_date is None and week_number == duration:
            test_date = week_start + timedelta(days=int(inputs.long_run_day) - 1)
            _remove_conflicting_club_quality(slots_by_date, test_date)
            slots_by_date[test_date] = _slot(
                week_number=week_number,
                scheduled_date=test_date,
                intent=WorkoutIntent.TEST_RUN,
                source=WorkoutSource.TEST_RUN,
                consumes_quality_capacity=True,
            )
        week_slots.append(list(slots_by_date.values()))

    quality_dates = {
        slot.date for slots in week_slots for slot in slots if slot.consumes_quality_capacity
    }
    if inputs.quality_sessions_per_week == 1:
        for slots in week_slots:
            if any(slot.consumes_quality_capacity for slot in slots):
                continue
            candidates = (
                slot
                for slot in sorted(slots, key=lambda item: item.date)
                if slot.intent == WorkoutIntent.EASY
                and all(abs((slot.date - quality_date).days) > 1 for quality_date in quality_dates)
            )
            candidate = next(candidates, None)
            if candidate is not None:
                slots[slots.index(candidate)] = replace(
                    candidate,
                    intent=WorkoutIntent.QUALITY,
                    consumes_quality_capacity=True,
                )
                quality_dates.add(candidate.date)

    weeks = []
    for week_index, slots in enumerate(week_slots):
        number = week_index + 1
        start = inputs.period.start_week + timedelta(weeks=week_index)
        weeks.append(
            First10KOutlineWeek(
                number=number,
                start_date=start,
                end_date=start + timedelta(days=6),
                phase=_phase_for_week(number, duration),
                workouts=_assign_stable_ids(number, slots),
            )
        )
    return First10KOutline(FIRST_10K_BLUEPRINT, tuple(weeks))


__all__ = [
    "FIRST_10K_BLUEPRINT",
    "First10KBlueprint",
    "First10KOutline",
    "First10KOutlineWeek",
    "First10KWorkoutSlot",
    "TrainingPhase",
    "WorkoutIntent",
    "WorkoutSource",
    "build_first_10k_outline",
]
