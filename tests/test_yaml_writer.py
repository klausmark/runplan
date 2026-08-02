from __future__ import annotations

from dataclasses import replace

import yaml

from runplan.parsing.yaml_loader import load_program_model
from runplan.parsing.yaml_writer import dump_program_yaml
from tests.helpers import program_data


def test_dump_program_yaml_is_canonical_and_round_trips() -> None:
    program = load_program_model(program_data())

    text = dump_program_yaml(program)

    assert (
        text
        == """program:
  id: characterization-plan
  name: Characterization Plan
  short_name: CHAR
  description: Stable behavior fixture
  start_week: 2026-W53
weeks:
  - week: 1
    focus: Mixed steps
    workouts:
      - id: mixed
        day: 1
        name: Week 1 - Mixed
        description: Time, distance and pace
        steps:
          - warmup:
              distance: 1km
          - repeat:
              count: 2
              steps:
                - run:
                    distance: 400m
                    pace: 4:30-4:45 min/km
                - recovery:
                    time: 1m30s
          - cooldown:
              time: 5m
      - id: easy
        day: 4
        name: Week 1 - Easy
        description: Easy run
        steps:
          - run:
              distance: 5km
  - week: 2
    focus: New year
    workouts:
      - id: long
        day: 7
        name: Week 2 - Long
        description: Long run
        steps:
          - run:
              distance: 10km
"""
    )
    assert load_program_model(yaml.safe_load(text)) == program


def test_dump_program_yaml_omits_derived_and_lifecycle_fields_recursively() -> None:
    program = load_program_model(program_data())
    workout = replace(
        program.weeks[0].workouts[0],
        status="completed",
        garmin_workout_id=12,
        garmin_schedule_id=34,
        activity_id=56,
        completed_at="2026-12-28T12:00:00",
        actual_distance_meters=2400,
        actual_duration_seconds=900,
    )
    enriched = replace(
        program,
        weeks=(replace(program.weeks[0], workouts=(workout,)), program.weeks[1]),
    )

    raw = yaml.safe_load(dump_program_yaml(enriched))

    assert set(raw["program"]) == {"id", "name", "short_name", "description", "start_week"}
    assert set(raw["weeks"][0]["workouts"][0]) == {
        "id",
        "day",
        "name",
        "description",
        "steps",
    }
    assert raw["weeks"][0]["workouts"][0]["steps"][1]["repeat"]["steps"] == [
        {"run": {"distance": "400m", "pace": "4:30-4:45 min/km"}},
        {"recovery": {"time": "1m30s"}},
    ]
