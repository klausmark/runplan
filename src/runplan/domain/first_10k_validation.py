"""Pure validation of generated programs against a first 10K outline."""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date
from typing import Literal

from .estimates import DEFAULT_PACE_SECONDS_PER_KM, WorkoutEstimate, estimate_steps
from .first_10k_blueprint import (
    First10KOutline,
    First10KWorkoutSlot,
    TrainingPhase,
    WorkoutIntent,
)
from .generation_inputs import (
    AmountKind,
    ClubSessionKind,
    NormalizedFirst10KGenerationInput,
    ProgressionProfile,
)
from .models import Program, Step, Workout

IssueSeverity = Literal["error", "warning"]

# Coaching policy tolerances. Club amounts allow 10%, with a useful floor for
# ordinary GPS/duration variation. Long-run share is advisory until it is extreme.
CLUB_AMOUNT_RELATIVE_TOLERANCE = 0.10
CLUB_DISTANCE_TOLERANCE_FLOOR_METERS = 500.0
CLUB_DURATION_TOLERANCE_FLOOR_SECONDS = 5 * 60.0
LONG_SHARE_WARNING = 0.45
LONG_SHARE_ERROR = 0.60
ZERO_LOAD_FIRST_WEEK_MAX_METERS = 10_000.0
ZERO_LOAD_WORKOUT_MAX_METERS = 5_000.0
DISTANCE_EPSILON_METERS = 1.0

_PROGRESSION_LIMITS = {
    ProgressionProfile.CAUTIOUS: (0.05, 1_000.0),
    ProgressionProfile.BALANCED: (0.08, 1_500.0),
    ProgressionProfile.AMBITIOUS: (0.10, 2_000.0),
}


@dataclass(frozen=True, slots=True)
class CandidateOccurrence:
    """A stable location in a generated candidate."""

    week_number: int
    workout_id: str | None = None
    day: int | None = None
    date: date | None = None


@dataclass(frozen=True, slots=True)
class CandidateValidationIssue:
    """One machine-addressable candidate validation result."""

    severity: IssueSeverity
    code: str
    message: str
    occurrence: CandidateOccurrence


@dataclass(frozen=True, slots=True)
class _MappedWorkout:
    slot: First10KWorkoutSlot
    workout: Workout
    estimate: WorkoutEstimate


def _slot_occurrence(slot: First10KWorkoutSlot) -> CandidateOccurrence:
    return CandidateOccurrence(slot.week_number, slot.stable_id, int(slot.weekday), slot.date)


def _workout_occurrence(week_number: int, workout: Workout) -> CandidateOccurrence:
    return CandidateOccurrence(week_number, workout.id, workout.day, workout.schedule_date)


def _week_occurrence(week_number: int) -> CandidateOccurrence:
    return CandidateOccurrence(week_number)


def _issue(
    severity: IssueSeverity,
    code: str,
    message: str,
    occurrence: CandidateOccurrence,
) -> CandidateValidationIssue:
    return CandidateValidationIssue(severity, code, message, occurrence)


def _map_occurrences(
    program: Program,
    outline: First10KOutline,
    pace_seconds_per_km: float,
) -> tuple[list[CandidateValidationIssue], tuple[_MappedWorkout, ...]]:
    issues: list[CandidateValidationIssue] = []
    actual_by_id: dict[str, list[tuple[int, Workout]]] = {}
    for week in program.weeks:
        for workout in week.workouts:
            actual_by_id.setdefault(workout.id, []).append((week.number, workout))

    expected_ids = {slot.stable_id for week in outline.weeks for slot in week.workouts}
    mapped: list[_MappedWorkout] = []
    for outline_week in outline.weeks:
        for slot in outline_week.workouts:
            candidates = actual_by_id.get(slot.stable_id, [])
            if not candidates:
                issues.append(
                    _issue(
                        "error",
                        "outline_occurrence_missing",
                        f"Required outline workout {slot.stable_id!r} is missing.",
                        _slot_occurrence(slot),
                    )
                )
                continue
            exact = next(
                (
                    item
                    for item in candidates
                    if item[0] == slot.week_number
                    and item[1].day == int(slot.weekday)
                    and item[1].schedule_date == slot.date
                ),
                None,
            )
            week_number, workout = exact or candidates[0]
            candidates.remove((week_number, workout))
            if (
                week_number != slot.week_number
                or workout.day != int(slot.weekday)
                or workout.schedule_date != slot.date
            ):
                issues.append(
                    _issue(
                        "error",
                        "outline_occurrence_altered",
                        f"Outline workout {slot.stable_id!r} must remain in week "
                        f"{slot.week_number} on day {int(slot.weekday)} ({slot.date.isoformat()}).",
                        _workout_occurrence(week_number, workout),
                    )
                )
            mapped.append(
                _MappedWorkout(slot, workout, estimate_steps(workout.steps, pace_seconds_per_km))
            )

    for workout_id, candidates in actual_by_id.items():
        for week_number, workout in candidates:
            detail = (
                "duplicates an outline ID"
                if workout_id in expected_ids
                else "is not in the outline"
            )
            issues.append(
                _issue(
                    "error",
                    "outline_occurrence_extra",
                    f"Workout {workout_id!r} {detail}.",
                    _workout_occurrence(week_number, workout),
                )
            )
    return issues, tuple(mapped)


def _progression_allowance(previous_meters: float, profile: ProgressionProfile) -> float:
    relative, absolute = _PROGRESSION_LIMITS[profile]
    return max(previous_meters * relative, absolute)


def _contains_recovery(steps: tuple[Step, ...]) -> bool:
    return any(
        step.action == "recovery" or (step.action == "repeat" and _contains_recovery(step.steps))
        for step in steps
    )


def _has_pace(steps: tuple[Step, ...]) -> bool:
    return any(
        step.pace is not None or (step.action == "repeat" and _has_pace(step.steps))
        for step in steps
    )


def _paced_actions(steps: tuple[Step, ...]) -> set[str]:
    actions: set[str] = set()
    for step in steps:
        if step.pace is not None:
            actions.add(step.action)
        if step.action == "repeat":
            actions.update(_paced_actions(step.steps))
    return actions


def _validate_pace_policy(
    program: Program,
    mapped: tuple[_MappedWorkout, ...],
    inputs: NormalizedFirst10KGenerationInput,
) -> list[CandidateValidationIssue]:
    issues: list[CandidateValidationIssue] = []
    has_source = (
        inputs.current_training.recent_5k_duration is not None
        or inputs.current_training.easy_pace is not None
    )
    for week in program.weeks:
        for workout in week.workouts:
            actions = _paced_actions(workout.steps)
            if not actions:
                continue
            occurrence = _workout_occurrence(week.number, workout)
            if actions & {"warmup", "cooldown", "recovery"}:
                issues.append(
                    _issue(
                        "error",
                        "non_work_step_pace_target",
                        "Warmup, cooldown, and recovery steps must not contain pace targets.",
                        occurrence,
                    )
                )
            if not has_source:
                issues.append(
                    _issue(
                        "error",
                        "pace_target_without_source",
                        "Structured pace targets require a recent 5K duration or easy pace.",
                        occurrence,
                    )
                )
    for item in mapped:
        if not _has_pace(item.workout.steps):
            continue
        quality_slot = item.slot.intent == WorkoutIntent.QUALITY or (
            item.slot.club_session is not None
            and item.slot.club_session.kind == ClubSessionKind.QUALITY
        )
        if not quality_slot:
            issues.append(
                _issue(
                    "error",
                    "slot_pace_target_not_allowed",
                    "This workout slot must not contain a structured pace target.",
                    _slot_occurrence(item.slot),
                )
            )
    return issues


def _validate_first_week(
    mapped: tuple[_MappedWorkout, ...],
    weekly_loads: tuple[float, ...],
    inputs: NormalizedFirst10KGenerationInput,
) -> list[CandidateValidationIssue]:
    issues: list[CandidateValidationIssue] = []
    current = inputs.current_training.average_weekly_km * 1000
    first = weekly_loads[0] if weekly_loads else 0.0
    if current > 0:
        if first < current * 0.80 - DISTANCE_EPSILON_METERS:
            issues.append(
                _issue(
                    "error",
                    "first_week_load_too_low",
                    "Week 1 is below 80% of current weekly load.",
                    _week_occurrence(1),
                )
            )
        if first > current * 1.10 + DISTANCE_EPSILON_METERS:
            issues.append(
                _issue(
                    "error",
                    "first_week_load_too_high",
                    "Week 1 exceeds 110% of current weekly load.",
                    _week_occurrence(1),
                )
            )
        return issues

    issues.append(
        _issue(
            "warning",
            "zero_current_load_cautious_start",
            "Current weekly load is zero; the first week is checked against cautious start limits.",
            _week_occurrence(1),
        )
    )
    if first > ZERO_LOAD_FIRST_WEEK_MAX_METERS + DISTANCE_EPSILON_METERS:
        issues.append(
            _issue(
                "error",
                "zero_load_first_week_too_high",
                "Week 1 exceeds the cautious 10 km start limit.",
                _week_occurrence(1),
            )
        )
    first_week = [item for item in mapped if item.slot.week_number == 1]
    for item in first_week:
        if item.estimate.distance_meters > ZERO_LOAD_WORKOUT_MAX_METERS + DISTANCE_EPSILON_METERS:
            issues.append(
                _issue(
                    "error",
                    "zero_load_workout_too_long",
                    "A week 1 workout exceeds the cautious 5 km workout limit.",
                    _slot_occurrence(item.slot),
                )
            )
    if first_week and not any(_contains_recovery(item.workout.steps) for item in first_week):
        issues.append(
            _issue(
                "warning",
                "zero_load_run_walk_not_explicit",
                "Week 1 does not contain an explicit walk/recovery step for a cautious run/walk start.",
                _week_occurrence(1),
            )
        )
    return issues


def _validate_weekly_progression(
    weekly_loads: tuple[float, ...],
    outline: First10KOutline,
    profile: ProgressionProfile,
) -> list[CandidateValidationIssue]:
    issues: list[CandidateValidationIssue] = []
    rising_weeks = 0
    for index in range(1, len(weekly_loads)):
        previous, current = weekly_loads[index - 1], weekly_loads[index]
        rising = current > previous + DISTANCE_EPSILON_METERS
        rising_weeks = rising_weeks + 1 if rising else 0
        phase = outline.weeks[index].phase
        if rising and phase not in (TrainingPhase.CONSOLIDATION, TrainingPhase.TAPER):
            allowance = _progression_allowance(previous, profile)
            if current > previous + allowance + DISTANCE_EPSILON_METERS:
                issues.append(
                    _issue(
                        "error",
                        "weekly_progression_exceeded",
                        f"Week {index + 1} exceeds the {profile.value} weekly progression limit.",
                        _week_occurrence(index + 1),
                    )
                )
        if rising_weeks > 3:
            issues.append(
                _issue(
                    "error",
                    "too_many_rising_weeks",
                    "Weekly load rises for more than three consecutive weeks.",
                    _week_occurrence(index + 1),
                )
            )

        if phase == TrainingPhase.CONSOLIDATION and previous > 0:
            reduction = (previous - current) / previous
            if reduction <= 0:
                issues.append(
                    _issue(
                        "error",
                        "consolidation_not_reduced",
                        "A consolidation week must reduce the prior week's load.",
                        _week_occurrence(index + 1),
                    )
                )
            elif reduction < 0.10 or reduction > 0.20:
                issues.append(
                    _issue(
                        "warning",
                        "consolidation_reduction_outside_range",
                        "A practical consolidation week is normally 10% to 20% below the prior week.",
                        _week_occurrence(index + 1),
                    )
                )

    for index, week in enumerate(outline.weeks[:-1]):
        if week.phase != TrainingPhase.CONSOLIDATION or index == 0:
            continue
        if outline.weeks[index + 1].phase == TrainingPhase.TAPER:
            continue
        prior_peak = max(weekly_loads[:index])
        rebound = weekly_loads[index + 1]
        if (
            rebound
            > prior_peak + _progression_allowance(prior_peak, profile) + DISTANCE_EPSILON_METERS
        ):
            issues.append(
                _issue(
                    "error",
                    "recovery_rebound_too_high",
                    "Load after consolidation is materially above the preceding peak.",
                    _week_occurrence(index + 2),
                )
            )
    return issues


def _is_long_slot(slot: First10KWorkoutSlot) -> bool:
    return slot.intent == WorkoutIntent.LONG or (
        slot.club_session is not None and slot.club_session.kind == ClubSessionKind.LONG
    )


def _validate_long_runs(
    mapped: tuple[_MappedWorkout, ...],
    weekly_loads: tuple[float, ...],
    inputs: NormalizedFirst10KGenerationInput,
    week_count: int,
    pace_seconds_per_km: float,
) -> list[CandidateValidationIssue]:
    issues: list[CandidateValidationIssue] = []
    long_by_week: list[_MappedWorkout | None] = [None] * week_count
    for item in mapped:
        if not _is_long_slot(item.slot):
            continue
        long_by_week[item.slot.week_number - 1] = item
        distance = item.estimate.distance_meters
        if (
            inputs.maximum_long_run_km is not None
            and distance > inputs.maximum_long_run_km * 1000 + DISTANCE_EPSILON_METERS
        ):
            issues.append(
                _issue(
                    "error",
                    "maximum_long_run_exceeded",
                    "The workout exceeds the requested maximum long-run distance.",
                    _slot_occurrence(item.slot),
                )
            )
        weekly = weekly_loads[item.slot.week_number - 1]
        share = distance / weekly if weekly > 0 else 0.0
        if share > LONG_SHARE_ERROR:
            severity: IssueSeverity = "error"
        elif share > LONG_SHARE_WARNING:
            severity = "warning"
        else:
            continue
        issues.append(
            _issue(
                severity,
                "long_run_share_high",
                "The long run is above the normal 40% to 45% share of weekly distance.",
                _slot_occurrence(item.slot),
            )
        )
    recent = inputs.current_training.longest_recent_run
    previous_distance = (
        recent.value * 1000
        if recent.kind is AmountKind.DISTANCE_KM
        else recent.value * 60 / pace_seconds_per_km * 1000
    )
    for current in long_by_week:
        if current is None:
            continue
        allowance = max(previous_distance * 0.10, 1_000.0)
        if (
            current.estimate.distance_meters
            > previous_distance + allowance + DISTANCE_EPSILON_METERS
        ):
            issues.append(
                _issue(
                    "error",
                    "long_run_progression_exceeded",
                    "The long run increases by more than 10% or 1 km.",
                    _slot_occurrence(current.slot),
                )
            )
        previous_distance = current.estimate.distance_meters
    return issues


def _validate_quality(
    outline: First10KOutline, inputs: NormalizedFirst10KGenerationInput
) -> list[CandidateValidationIssue]:
    issues: list[CandidateValidationIssue] = []
    quality_slots = sorted(
        (
            slot
            for week in outline.weeks
            for slot in week.workouts
            if slot.consumes_quality_capacity
        ),
        key=lambda slot: slot.date,
    )
    for week in outline.weeks:
        consuming = [slot for slot in week.workouts if slot.consumes_quality_capacity]
        blueprint_quality = [slot for slot in week.workouts if slot.intent == WorkoutIntent.QUALITY]
        if len(blueprint_quality) > inputs.quality_sessions_per_week:
            issues.append(
                _issue(
                    "error",
                    "quality_sessions_exceeded",
                    "The outline contains more optional quality sessions than requested.",
                    _week_occurrence(week.number),
                )
            )
        if len(consuming) > 1:
            issues.append(
                _issue(
                    "error",
                    "quality_capacity_exceeded",
                    "More than one workout consumes quality capacity in this week.",
                    _week_occurrence(week.number),
                )
            )
    for previous, current in zip(quality_slots, quality_slots[1:], strict=False):
        if (current.date - previous.date).days == 1:
            issues.append(
                _issue(
                    "error",
                    "quality_workouts_adjacent",
                    "Quality-capacity workouts must not occur on consecutive days.",
                    _slot_occurrence(current),
                )
            )
    return issues


def _validate_club_and_races(mapped: tuple[_MappedWorkout, ...]) -> list[CandidateValidationIssue]:
    issues: list[CandidateValidationIssue] = []
    for item in mapped:
        slot, estimate = item.slot, item.estimate
        if slot.club_session is not None:
            amount = slot.club_session.amount
            if amount.kind == AmountKind.DISTANCE_KM:
                actual, expected = estimate.distance_meters, amount.value * 1000
                tolerance = max(
                    expected * CLUB_AMOUNT_RELATIVE_TOLERANCE, CLUB_DISTANCE_TOLERANCE_FLOOR_METERS
                )
            else:
                actual, expected = estimate.duration_seconds, amount.value * 60
                tolerance = max(
                    expected * CLUB_AMOUNT_RELATIVE_TOLERANCE, CLUB_DURATION_TOLERANCE_FLOOR_SECONDS
                )
            if abs(actual - expected) > tolerance:
                issues.append(
                    _issue(
                        "error",
                        "club_amount_outside_tolerance",
                        "The club workout estimate differs from its expected amount by more than 10% (minimum 0.5 km or 5 minutes).",
                        _slot_occurrence(slot),
                    )
                )

        expected_race_meters: float | None = None
        race_label = "race"
        if slot.intent == WorkoutIntent.B_RACE and slot.b_race is not None:
            expected_race_meters = slot.b_race.distance_km * 1000
            race_label = "B race"
        elif slot.intent in (WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN):
            expected_race_meters = 10_000.0
            race_label = "goal race" if slot.intent == WorkoutIntent.GOAL_RACE else "10K test run"
        if expected_race_meters is not None and estimate.distance_is_approximate:
            issues.append(
                _issue(
                    "error",
                    "race_distance_approximate",
                    f"The {race_label} distance must be explicit rather than pace-estimated.",
                    _slot_occurrence(slot),
                )
            )
        if (
            expected_race_meters is not None
            and abs(estimate.distance_meters - expected_race_meters) > DISTANCE_EPSILON_METERS
        ):
            issues.append(
                _issue(
                    "error",
                    "race_distance_mismatch",
                    f"The {race_label} must total exactly {expected_race_meters / 1000:g} km.",
                    _slot_occurrence(slot),
                )
            )
        if expected_race_meters is not None and item.workout.schedule_date != slot.date:
            issues.append(
                _issue(
                    "error",
                    "race_date_mismatch",
                    f"The {race_label} must remain on {slot.date.isoformat()}.",
                    _workout_occurrence(slot.week_number, item.workout),
                )
            )
        if slot.intent == WorkoutIntent.GOAL_RACE and _has_pace(item.workout.steps):
            issues.append(
                _issue(
                    "error",
                    "goal_race_pace_target",
                    "The goal race must not contain a structured pace target.",
                    _slot_occurrence(slot),
                )
            )
    return issues


def validate_first_10k_candidate(
    program: Program,
    inputs: NormalizedFirst10KGenerationInput,
    outline: First10KOutline,
    *,
    fallback_pace_seconds_per_km: float = DEFAULT_PACE_SECONDS_PER_KM,
) -> tuple[CandidateValidationIssue, ...]:
    """Return immutable issues for one parsed generated-program candidate.

    Distances and durations come exclusively from :func:`estimate_steps`. A supplied easy
    pace midpoint takes precedence over ``fallback_pace_seconds_per_km`` for time-based steps.
    """
    if not isinstance(program, Program):
        raise TypeError("program must be a parsed Program")
    if not isinstance(inputs, NormalizedFirst10KGenerationInput):
        raise TypeError("inputs must be normalized first 10K generation input")
    if not isinstance(outline, First10KOutline):
        raise TypeError("outline must be a first 10K outline")
    if not math.isfinite(fallback_pace_seconds_per_km) or fallback_pace_seconds_per_km <= 0:
        raise ValueError("fallback pace must be a finite positive number")

    pace = fallback_pace_seconds_per_km
    if inputs.current_training.easy_pace is not None:
        easy_pace = inputs.current_training.easy_pace
        pace = (easy_pace.fast_seconds_per_km + easy_pace.slow_seconds_per_km) / 2

    issues: list[CandidateValidationIssue] = []
    expected_start = inputs.period.start_week
    if program.start_date != expected_start:
        issues.append(
            _issue(
                "error",
                "program_start_mismatch",
                f"Program start must be {expected_start.isoformat()}.",
                _week_occurrence(1),
            )
        )
    if len(program.weeks) != len(outline.weeks):
        issues.append(
            _issue(
                "error",
                "program_week_count_mismatch",
                f"Program must contain exactly {len(outline.weeks)} weeks.",
                _week_occurrence(min(len(program.weeks), len(outline.weeks)) + 1),
            )
        )

    occurrence_issues, mapped = _map_occurrences(program, outline, pace)
    issues.extend(occurrence_issues)
    weekly_loads = tuple(
        sum(
            item.estimate.distance_meters for item in mapped if item.slot.week_number == week.number
        )
        for week in outline.weeks
    )
    issues.extend(_validate_first_week(mapped, weekly_loads, inputs))
    issues.extend(_validate_weekly_progression(weekly_loads, outline, inputs.progression))
    for index, load in enumerate(weekly_loads, start=1):
        if (
            inputs.maximum_weekly_km is not None
            and load > inputs.maximum_weekly_km * 1000 + DISTANCE_EPSILON_METERS
        ):
            issues.append(
                _issue(
                    "error",
                    "maximum_weekly_load_exceeded",
                    "The week exceeds the requested maximum weekly distance.",
                    _week_occurrence(index),
                )
            )
    issues.extend(_validate_long_runs(mapped, weekly_loads, inputs, len(outline.weeks), pace))
    issues.extend(_validate_quality(outline, inputs))
    issues.extend(_validate_club_and_races(mapped))
    issues.extend(_validate_pace_policy(program, mapped, inputs))
    return tuple(issues)


__all__ = [
    "CLUB_AMOUNT_RELATIVE_TOLERANCE",
    "CandidateOccurrence",
    "CandidateValidationIssue",
    "IssueSeverity",
    "validate_first_10k_candidate",
]
