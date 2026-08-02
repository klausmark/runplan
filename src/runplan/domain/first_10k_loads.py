"""Deterministic weekly load planning for first-10K programs."""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

from .estimates import DEFAULT_PACE_SECONDS_PER_KM
from .first_10k_blueprint import First10KOutline, First10KWorkoutSlot, TrainingPhase, WorkoutIntent
from .generation_inputs import AmountKind, ClubSessionKind, NormalizedFirst10KGenerationInput

ABSOLUTE_MINIMUM_FLEXIBLE_KM = 0.5
_NOMINAL_GROWTH = {
    "cautious": 0.03,
    "balanced": 0.05,
    "ambitious": 0.07,
}
_HARD_GROWTH = {
    "cautious": (0.05, 1.0),
    "balanced": (0.08, 1.5),
    "ambitious": (0.10, 2.0),
}
_SOFT_PEAK_BY_DAYS = {2: 18.0, 3: 24.0, 4: 30.0, 5: 35.0, 6: 38.0, 7: 42.0}


class First10KPlanInfeasibleError(ValueError):
    """Raised when fixed commitments cannot satisfy the coaching constraints."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class PlannedWeekLoad:
    week_number: int
    target_km: float
    workout_km: tuple[tuple[str, float], ...]

    def distance_for(self, slot: First10KWorkoutSlot) -> float:
        return dict(self.workout_km)[slot.stable_id]


def planning_pace_seconds(inputs: NormalizedFirst10KGenerationInput) -> float:
    pace = inputs.current_training.easy_pace
    if pace is None:
        return DEFAULT_PACE_SECONDS_PER_KM
    return (pace.fast_seconds_per_km + pace.slow_seconds_per_km) / 2


def _recent_long_km(inputs: NormalizedFirst10KGenerationInput, pace_seconds: float) -> float:
    amount = inputs.current_training.longest_recent_run
    if amount.kind is AmountKind.DISTANCE_KM:
        return amount.value
    return amount.value * 60 / pace_seconds


def _minimum_flexible_km(inputs: NormalizedFirst10KGenerationInput) -> float:
    current = inputs.current_training.average_weekly_km
    if current == 0:
        return ABSOLUTE_MINIMUM_FLEXIBLE_KM
    return round(
        min(2.0, max(ABSOLUTE_MINIMUM_FLEXIBLE_KM, current / len(inputs.weekdays) * 0.40)), 2
    )


def _fixed_distance_km(slot: First10KWorkoutSlot, pace_seconds: float) -> float | None:
    if slot.intent == WorkoutIntent.B_RACE:
        assert slot.b_race is not None
        return slot.b_race.distance_km
    if slot.intent in (WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN):
        return 10.0
    if slot.club_session is None:
        return None
    amount = slot.club_session.amount
    if amount.kind is AmountKind.DISTANCE_KM:
        return amount.value
    return amount.value * 60 / pace_seconds


def _is_long(slot: First10KWorkoutSlot) -> bool:
    return slot.intent is WorkoutIntent.LONG or (
        slot.club_session is not None and slot.club_session.kind is ClubSessionKind.LONG
    )


def _week_floor(
    slots: tuple[First10KWorkoutSlot, ...], pace_seconds: float, minimum_flexible_km: float
) -> tuple[float, float | None]:
    fixed = 0.0
    fixed_long: float | None = None
    flexible_count = 0
    for slot in slots:
        distance = _fixed_distance_km(slot, pace_seconds)
        if distance is None:
            flexible_count += 1
        else:
            fixed += distance
            if _is_long(slot):
                fixed_long = distance
    floor = fixed + flexible_count * minimum_flexible_km
    if fixed_long is not None:
        floor = max(floor, fixed_long / 0.45)
    return floor, fixed_long


def _increase_allowance(previous: float, inputs: NormalizedFirst10KGenerationInput) -> float:
    relative, absolute = _HARD_GROWTH[inputs.progression.value]
    return max(previous * relative, absolute)


def _initial_target(inputs: NormalizedFirst10KGenerationInput) -> float:
    current = inputs.current_training.average_weekly_km
    if current > 0:
        return current
    return min(10.0, len(inputs.weekdays) * 2.5)


def _target_curve(
    inputs: NormalizedFirst10KGenerationInput,
    outline: First10KOutline,
    floors: tuple[float, ...],
) -> list[float]:
    maximum = inputs.maximum_weekly_km
    targets: list[float] = []
    peak = 0.0
    soft_peak = max(
        inputs.current_training.average_weekly_km,
        _SOFT_PEAK_BY_DAYS[len(inputs.weekdays)],
    )
    for index, week in enumerate(outline.weeks):
        if index == 0:
            target = max(_initial_target(inputs), floors[index])
            current = inputs.current_training.average_weekly_km
            if current > 0 and target > current * 1.10 + 0.001:
                raise First10KPlanInfeasibleError(
                    "first_week_fixed_load",
                    "Fixed week-one sessions exceed 110% of the current weekly distance.",
                )
            if current == 0 and target > 10.0 + 0.001:
                raise First10KPlanInfeasibleError(
                    "zero_load_first_week",
                    "Fixed week-one sessions exceed the cautious 10 km start limit.",
                )
        elif week.phase is TrainingPhase.CONSOLIDATION:
            target = max(targets[-1] * 0.85, floors[index])
            if target >= targets[-1] - 0.001:
                raise First10KPlanInfeasibleError(
                    "consolidation_fixed_load",
                    f"Fixed sessions prevent a reduced load in week {week.number}.",
                )
        elif week.phase is TrainingPhase.TAPER:
            target = max(targets[-1] * 0.70, floors[index])
        else:
            previous = targets[-1]
            nominal = max(0.5, previous * _NOMINAL_GROWTH[inputs.progression.value])
            target = min(previous + nominal, soft_peak)
            if outline.weeks[index - 1].phase is TrainingPhase.CONSOLIDATION:
                target = min(peak, previous + _increase_allowance(previous, inputs))
            target = max(target, floors[index])
            if target > previous + _increase_allowance(previous, inputs) + 0.001:
                raise First10KPlanInfeasibleError(
                    "fixed_load_progression",
                    f"Fixed sessions in week {week.number} exceed the progression limit.",
                )
        target = max(floors[index], floor((target + 1e-9) * 100) / 100)
        if maximum is not None and target > maximum + 0.001:
            raise First10KPlanInfeasibleError(
                "maximum_weekly_distance",
                f"Week {week.number} cannot fit within the maximum weekly distance.",
            )
        targets.append(target)
        if week.phase is not TrainingPhase.CONSOLIDATION:
            peak = max(peak, target)
    return targets


def _long_distance(
    target: float,
    previous_long: float | None,
    phase: TrainingPhase,
    inputs: NormalizedFirst10KGenerationInput,
    minimum_flexible_km: float,
) -> float:
    desired = target * 0.40
    if phase is TrainingPhase.CONSOLIDATION and previous_long is not None:
        desired = min(desired, previous_long * 0.85)
    hard_cap = float("inf")
    if previous_long is not None:
        hard_cap = min(hard_cap, previous_long + max(previous_long * 0.10, 1.0))
    if inputs.maximum_long_run_km is not None:
        hard_cap = min(hard_cap, inputs.maximum_long_run_km)
    if hard_cap < minimum_flexible_km - 0.001:
        raise First10KPlanInfeasibleError(
            "long_run_constraints",
            "The recent long run and maximum long-run distance do not allow the minimum "
            "safe workout distance.",
        )
    distance = max(minimum_flexible_km, min(desired, hard_cap))
    return floor((distance + 1e-9) * 100) / 100


def _allocate_week(
    target: float,
    slots: tuple[First10KWorkoutSlot, ...],
    pace_seconds: float,
    previous_long: float | None,
    phase: TrainingPhase,
    inputs: NormalizedFirst10KGenerationInput,
    minimum_flexible_km: float,
) -> tuple[dict[str, float], float | None]:
    allocated: dict[str, float] = {}
    flexible: list[First10KWorkoutSlot] = []
    long_slot: First10KWorkoutSlot | None = None
    fixed_total = 0.0
    current_long = previous_long
    for slot in slots:
        fixed = _fixed_distance_km(slot, pace_seconds)
        if fixed is not None:
            allocated[slot.stable_id] = fixed
            fixed_total += fixed
            if _is_long(slot):
                if previous_long is not None:
                    allowance = max(previous_long * 0.10, 1.0)
                    if fixed > previous_long + allowance + 0.001:
                        raise First10KPlanInfeasibleError(
                            "fixed_long_run_progression",
                            f"The fixed long session in week {slot.week_number} exceeds the "
                            "safe progression from the previous long run.",
                        )
                if (
                    inputs.maximum_long_run_km is not None
                    and fixed > inputs.maximum_long_run_km + 0.001
                ):
                    raise First10KPlanInfeasibleError(
                        "maximum_long_run_distance",
                        f"The fixed long session in week {slot.week_number} exceeds the maximum.",
                    )
                current_long = fixed
        elif _is_long(slot):
            long_slot = slot
        else:
            flexible.append(slot)

    if long_slot is not None:
        long_km = _long_distance(target, previous_long, phase, inputs, minimum_flexible_km)
        available = target - fixed_total - len(flexible) * minimum_flexible_km
        long_km = min(long_km, max(minimum_flexible_km, available))
        allocated[long_slot.stable_id] = long_km
        fixed_total += long_km
        current_long = long_km

    remaining = target - fixed_total
    minimum = len(flexible) * minimum_flexible_km
    if remaining < minimum - 0.001:
        raise First10KPlanInfeasibleError(
            "insufficient_flexible_load",
            f"Fixed sessions leave too little safe training volume in week {slots[0].week_number}.",
        )
    if flexible:
        weights = [1.10 if slot.intent is WorkoutIntent.QUALITY else 1.0 for slot in flexible]
        distributable = remaining - minimum
        values = [minimum_flexible_km + distributable * weight / sum(weights) for weight in weights]
        rounded = [round(value, 2) for value in values]
        rounded[-1] = round(rounded[-1] + target - fixed_total - sum(rounded), 2)
        allocated.update(
            (slot.stable_id, value) for slot, value in zip(flexible, rounded, strict=True)
        )
    elif long_slot is not None and remaining > 0.001:
        updated = allocated[long_slot.stable_id] + remaining
        if updated > target * 0.45 + 0.001:
            raise First10KPlanInfeasibleError(
                "long_run_share",
                f"Week {slots[0].week_number} cannot distribute load without an excessive long run.",
            )
        allocated[long_slot.stable_id] = round(updated, 2)
        current_long = allocated[long_slot.stable_id]
    return allocated, current_long


def plan_first_10k_loads(
    inputs: NormalizedFirst10KGenerationInput, outline: First10KOutline
) -> tuple[PlannedWeekLoad, ...]:
    """Plan deterministic weekly and workout distance targets."""
    pace_seconds = planning_pace_seconds(inputs)
    minimum_flexible_km = _minimum_flexible_km(inputs)
    floor_data = tuple(
        _week_floor(week.workouts, pace_seconds, minimum_flexible_km) for week in outline.weeks
    )
    targets = _target_curve(inputs, outline, tuple(item[0] for item in floor_data))
    result = []
    previous_long: float | None = _recent_long_km(inputs, pace_seconds)
    for week, target in zip(outline.weeks, targets, strict=True):
        allocated, previous_long = _allocate_week(
            target,
            week.workouts,
            pace_seconds,
            previous_long,
            week.phase,
            inputs,
            minimum_flexible_km,
        )
        actual = round(sum(allocated.values()), 2)
        result.append(PlannedWeekLoad(week.number, actual, tuple(sorted(allocated.items()))))
    return tuple(result)


__all__ = [
    "First10KPlanInfeasibleError",
    "PlannedWeekLoad",
    "plan_first_10k_loads",
    "planning_pace_seconds",
]
