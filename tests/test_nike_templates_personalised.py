"""Verify the NRC templates emit personalised Garmin pace zones."""

from __future__ import annotations

import pytest

from runplan.domain.pace import intensity_pace_seconds, pace_zone
from runplan.integrations.garmin.mapper import build_workout
from runplan.templates.catalog import load_template_program


def _total_seconds(value: str) -> int:
    parts = value.split(":")
    if len(parts) == 2:
        return int(parts[0]) * 60 + int(parts[1])
    return int(parts[0]) * 3600 + int(parts[1]) * 60 + int(parts[2])


def _resolve(five_k_best: str, zone: int):
    five_k_seconds = _total_seconds(five_k_best)

    def resolver(_label: str) -> tuple[float, float]:
        return pace_zone(five_k_seconds, _label, tolerance_seconds_per_km=zone)

    return resolver


@pytest.mark.parametrize(
    "template_id", ["nike-5k", "nike-10k", "nike-half-marathon", "nike-marathon"]
)
def test_templates_resolve_symbolic_paces_for_a_user(template_id: str) -> None:
    program = load_template_program(template_id)
    resolver = _resolve("30:00", 5)
    seen = False
    for week in program.weeks:
        for workout in week.workouts:
            garmin = build_workout(workout, resolve_pace_type=resolver)
            for segment in garmin.workoutSegments:
                for step in segment.workoutSteps:
                    target = getattr(step, "targetType", None)
                    if target and target.get("workoutTargetTypeKey") == "pace.zone":
                        seen = True
    assert seen, f"{template_id} produced no Garmin pace zones"


def test_user_with_faster_5k_produces_faster_zones() -> None:
    program_a = load_template_program("nike-5k")
    program_b = load_template_program("nike-5k")
    resolver_a = _resolve("30:00", 5)
    resolver_b = _resolve("25:00", 5)
    zone_a: float | None = None
    zone_b: float | None = None
    for week in program_a.weeks[:1]:
        for workout in week.workouts:
            garmin = build_workout(workout, resolve_pace_type=resolver_a)
            for segment in garmin.workoutSegments:
                for step in segment.workoutSteps:
                    target = getattr(step, "targetType", None)
                    if target and target.get("workoutTargetTypeKey") == "pace.zone":
                        zone_a = step.targetValueOne
                        break
    for week in program_b.weeks[:1]:
        for workout in week.workouts:
            garmin = build_workout(workout, resolve_pace_type=resolver_b)
            for segment in garmin.workoutSegments:
                for step in segment.workoutSteps:
                    target = getattr(step, "targetType", None)
                    if target and target.get("workoutTargetTypeKey") == "pace.zone":
                        zone_b = step.targetValueOne
                        break
    assert zone_a is not None and zone_b is not None
    assert zone_b > zone_a


def test_zero_tolerance_emits_a_fixed_target() -> None:
    program = load_template_program("nike-5k")
    resolver = _resolve("30:00", 0)
    for week in program.weeks[:1]:
        for workout in week.workouts:
            garmin = build_workout(workout, resolve_pace_type=resolver)
            for segment in garmin.workoutSegments:
                for step in segment.workoutSteps:
                    target = getattr(step, "targetType", None)
                    if target and target.get("workoutTargetTypeKey") == "pace.zone":
                        assert step.targetValueOne == step.targetValueTwo
                        return
    raise AssertionError("no pace zone emitted")


def test_race_day_target_matches_user_distance() -> None:
    program = load_template_program("nike-marathon")
    resolver = _resolve("30:00", 0)
    expected_marathon = intensity_pace_seconds(_total_seconds("30:00"), "marathon")
    for week in program.weeks:
        for workout in week.workouts:
            if "Race Day" not in workout.name:
                continue
            garmin = build_workout(workout, resolve_pace_type=resolver)
            for segment in garmin.workoutSegments:
                for step in segment.workoutSteps:
                    target = getattr(step, "targetType", None)
                    if target and target.get("workoutTargetTypeKey") == "pace.zone":
                        seconds_per_km = 1000.0 / step.targetValueTwo
                        assert seconds_per_km == expected_marathon
                        return
    raise AssertionError("marathon race-day workout not found")
