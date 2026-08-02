"""Deterministic workout recipes for first-10K programs."""

from __future__ import annotations

from .first_10k_blueprint import First10KWorkoutSlot, TrainingPhase, WorkoutIntent
from .generation_inputs import (
    AmountKind,
    ClubSessionKind,
    NormalizedFirst10KGenerationInput,
    RaceIntensity,
    TrainingStyle,
)
from .models import Step, StepAction, Workout


def _distance_step(
    action: StepAction, kilometers: float, pace: tuple[float, float] | None = None
) -> Step:
    return Step(
        action=action, end_kind="distance", end_value=round(kilometers * 1000, 3), pace=pace
    )


def _run_walk_steps(kilometers: float, *, long: bool = False) -> tuple[Step, ...]:
    count = 6 if long else 5
    run_meters = round(kilometers * 1000 / count, 3)
    recovery_seconds = 90.0 if long else 75.0
    return (
        Step(
            action="repeat",
            count=count,
            steps=(
                Step(action="run", end_kind="distance", end_value=run_meters),
                Step(action="recovery", end_kind="time", end_value=recovery_seconds),
            ),
        ),
    )


def _continuous_steps(kilometers: float, *, split: bool) -> tuple[Step, ...]:
    if not split or kilometers < 3:
        return (_distance_step("run", kilometers),)
    edge = min(0.75, round(kilometers * 0.15, 2))
    return (
        _distance_step("warmup", edge),
        _distance_step("run", round(kilometers - edge * 2, 2)),
        _distance_step("cooldown", edge),
    )


def _quality_pace(inputs: NormalizedFirst10KGenerationInput) -> tuple[float, float] | None:
    result = inputs.current_training.recent_5k_duration
    if result is None:
        return None
    five_k_seconds_per_km = result.value * 12
    return float(round(five_k_seconds_per_km + 15)), float(round(five_k_seconds_per_km + 35))


def _quality_steps(
    kilometers: float, week_number: int, inputs: NormalizedFirst10KGenerationInput
) -> tuple[str, str, tuple[Step, ...]]:
    names = ("Controlled pickups", "Cruise intervals", "Aerobic intervals")
    descriptions = (
        "Run each pickup with relaxed form at a controlled effort; recover very easily.",
        "Keep every work interval controlled and finish feeling able to complete one more.",
        "Use a comfortably hard aerobic effort without sprinting or straining.",
    )
    index = (week_number - 1) % len(names)
    if kilometers < 3:
        return names[index], descriptions[index], (_distance_step("run", kilometers),)

    counts = (6, 3, 4)
    count = counts[index]
    total_meters = round(kilometers * 1000, 3)
    work_meters = max(200.0, round(total_meters * 0.40 / count / 10) * 10)
    if work_meters * count > total_meters * 0.60:
        work_meters = round(total_meters * 0.35 / count, 3)
    remaining = total_meters - work_meters * count
    warmup = round(remaining / 2, 3)
    cooldown = round(remaining - warmup, 3)
    pace = _quality_pace(inputs)
    return (
        names[index],
        descriptions[index],
        (
            Step(action="warmup", end_kind="distance", end_value=warmup),
            Step(
                action="repeat",
                count=count,
                steps=(
                    Step(
                        action="run",
                        end_kind="distance",
                        end_value=work_meters,
                        pace=pace,
                    ),
                    Step(action="recovery", end_kind="time", end_value=90.0),
                ),
            ),
            Step(action="cooldown", end_kind="distance", end_value=cooldown),
        ),
    )


def _uses_run_walk(
    slot: First10KWorkoutSlot,
    phase: TrainingPhase,
    inputs: NormalizedFirst10KGenerationInput,
) -> bool:
    if slot.intent not in (WorkoutIntent.EASY, WorkoutIntent.LONG):
        return False
    if inputs.training_style is TrainingStyle.RUN_WALK:
        return True
    return (
        inputs.training_style is TrainingStyle.AUTO
        and phase is TrainingPhase.FOUNDATION
        and inputs.current_training.average_weekly_km < 8
    )


def _club_workout(slot: First10KWorkoutSlot) -> tuple[str, str, tuple[Step, ...]]:
    session = slot.club_session
    assert session is not None
    names = {
        ClubSessionKind.EASY: "Easy club run",
        ClubSessionKind.LONG: "Club long run",
        ClubSessionKind.QUALITY: "Club quality session",
        ClubSessionKind.UNKNOWN: "Club session",
    }
    descriptions = {
        ClubSessionKind.EASY: "Run conversationally with the group.",
        ClubSessionKind.LONG: "Keep the group run relaxed and sustainable.",
        ClubSessionKind.QUALITY: "Follow the coached club session without adding extra intensity.",
        ClubSessionKind.UNKNOWN: "Follow the planned club session and keep any extra running easy.",
    }
    amount = session.amount
    if amount.kind is AmountKind.DISTANCE_KM:
        steps = (_distance_step("run", amount.value),)
    else:
        steps = (Step(action="run", end_kind="time", end_value=amount.value * 60),)
    return names[session.kind], descriptions[session.kind], steps


def _race_workout(slot: First10KWorkoutSlot) -> tuple[str, str, tuple[Step, ...]]:
    if slot.intent is WorkoutIntent.B_RACE:
        race = slot.b_race
        assert race is not None
        descriptions = {
            RaceIntensity.ALL_OUT: "Race with a controlled start, then use your best sustainable effort.",
            RaceIntensity.CONTROLLED: "Run strongly but keep enough reserve to resume training normally.",
            RaceIntensity.TRAINING_RUN: "Treat the event as a supported training run rather than a race.",
        }
        return (
            f"{race.distance_km:g}K preparation race",
            descriptions[race.intensity],
            (_distance_step("run", race.distance_km),),
        )
    if slot.intent is WorkoutIntent.GOAL_RACE:
        return (
            "First 10K race",
            "Start patiently, settle into a sustainable effort, and focus on completing 10 kilometers.",
            (_distance_step("run", 10),),
        )
    return (
        "10K completion run",
        "Run the first half conservatively and complete the full distance at a sustainable effort.",
        (_distance_step("run", 10),),
    )


def build_first_10k_workout(
    slot: First10KWorkoutSlot,
    kilometers: float,
    phase: TrainingPhase,
    inputs: NormalizedFirst10KGenerationInput,
) -> Workout:
    """Render one deterministic workout from an outline slot and load allocation."""
    if slot.club_session is not None:
        name, description, steps = _club_workout(slot)
    elif slot.intent in (WorkoutIntent.B_RACE, WorkoutIntent.GOAL_RACE, WorkoutIntent.TEST_RUN):
        name, description, steps = _race_workout(slot)
    elif slot.intent is WorkoutIntent.QUALITY:
        name, description, steps = _quality_steps(kilometers, slot.week_number, inputs)
    elif slot.intent is WorkoutIntent.LONG:
        name = "Easy long run" if phase is not TrainingPhase.CONSOLIDATION else "Reduced long run"
        description = "Keep the effort conversational and finish with relaxed form."
        steps = (
            _run_walk_steps(kilometers, long=True)
            if _uses_run_walk(slot, phase, inputs)
            else _continuous_steps(kilometers, split=slot.week_number % 2 == 0)
        )
    else:
        recovery = phase in (TrainingPhase.CONSOLIDATION, TrainingPhase.TAPER)
        name = "Recovery run" if recovery else "Easy aerobic run"
        description = "Run easily enough to speak in complete sentences."
        steps = (
            _run_walk_steps(kilometers)
            if _uses_run_walk(slot, phase, inputs)
            else _continuous_steps(kilometers, split=not recovery and slot.week_number % 2 == 1)
        )
    return Workout(
        id=slot.stable_id,
        day=int(slot.weekday),
        name=name,
        description=description,
        steps=steps,
        schedule_date=slot.date,
    )


__all__ = ["build_first_10k_workout"]
