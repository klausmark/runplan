from __future__ import annotations

from copy import deepcopy
from typing import Any

from runplan import build_workout, load_program


def program_data() -> dict[str, Any]:
    return {
        "program": {
            "id": "characterization-plan",
            "name": "Characterization Plan",
            "short_name": "CHAR",
            "description": "Stable behavior fixture",
            "start_week": "2026-W53",
        },
        "weeks": [
            {
                "week": 1,
                "focus": "Mixed steps",
                "workouts": [
                    {
                        "id": "mixed",
                        "day": 1,
                        "name": "Week 1 - Mixed",
                        "description": "Time, distance and pace",
                        "steps": [
                            {"warmup": {"distance": "1km"}},
                            {
                                "repeat": {
                                    "count": 2,
                                    "steps": [
                                        {
                                            "run": {
                                                "distance": "400m",
                                                "pace": "4:30-4:45 min/km",
                                            }
                                        },
                                        {"recovery": {"time": "90s"}},
                                    ],
                                }
                            },
                            {"cooldown": "5m"},
                        ],
                    },
                    {
                        "id": "easy",
                        "day": 4,
                        "name": "Week 1 - Easy",
                        "description": "Easy run",
                        "steps": [{"run": {"distance": "5km"}}],
                    },
                ],
            },
            {
                "week": 2,
                "focus": "New year",
                "workouts": [
                    {
                        "id": "long",
                        "day": 7,
                        "name": "Week 2 - Long",
                        "description": "Long run",
                        "steps": [{"run": {"distance": "10km"}}],
                    }
                ],
            },
        ],
    }


def normalized_program(selected_week: int = 1) -> dict[str, Any]:
    return load_program(deepcopy(program_data()), selected_week)


def compiled_week(selected_week: int = 1):
    program = normalized_program(selected_week)
    compiled = []
    for workout in program["workouts"]:
        workout["base_description"] = workout.get("description")
        compiled.append((workout, build_workout(workout)))
    return program, compiled
