"""Verify that every Nike Run Club template compiles cleanly to Garmin workouts."""

from __future__ import annotations

import re

import pytest

from runplan import build_workout, compile_steps, get_template
from runplan.domain.workout_titles import garmin_workout_title

TITLE_PATTERN = re.compile(r"^[A-Z0-9]+ - W\d+ - .+ - [\d.~]+k(?:m)?$")


@pytest.mark.parametrize(
    "template_id", ["nike-5k", "nike-10k", "nike-half-marathon", "nike-marathon"]
)
def test_every_template_workout_compiles_to_garmin_payload(template_id: str) -> None:
    from runplan.templates.catalog import load_template_program

    program = load_template_program(template_id)
    for week in program.weeks:
        for workout in week.workouts:
            payload = build_workout(workout)
            assert payload.sportType["sportTypeKey"] == "running"
            assert payload.workoutSegments, workout.id
            assert payload.workoutSegments[0].workoutSteps, workout.id
            from runplan.integrations.garmin.mapper import workout_definition

            definition = workout_definition(workout)
            assert compile_steps(definition["steps"]), workout.id


@pytest.mark.parametrize(
    "template_id", ["nike-5k", "nike-10k", "nike-half-marathon", "nike-marathon"]
)
def test_garmin_titles_follow_short_name_pattern(template_id: str) -> None:
    metadata = get_template(template_id)
    from runplan.templates.catalog import load_template_program

    program = load_template_program(template_id)
    short_name = metadata.short_name
    for week in program.weeks:
        for workout in week.workouts:
            title = garmin_workout_title(
                short_name, week.number, workout, fallback_pace_seconds_per_km=300
            )
            assert title.startswith(f"{short_name} - W{week.number} - "), title
            assert TITLE_PATTERN.match(title), f"unexpected title: {title}"


def test_no_garmin_title_collides_within_a_template() -> None:
    for template_id in ["nike-5k", "nike-10k", "nike-half-marathon", "nike-marathon"]:
        metadata = get_template(template_id)
        from runplan.templates.catalog import load_template_program

        program = load_template_program(template_id)
        seen: set[tuple[int, int, str]] = set()
        for week in program.weeks:
            for workout in week.workouts:
                title = garmin_workout_title(
                    metadata.short_name, week.number, workout, fallback_pace_seconds_per_km=300
                )
                key = (week.number, workout.day, workout.name)
                assert key not in seen, f"Duplicate title in {template_id}: {title}"
                seen.add(key)
