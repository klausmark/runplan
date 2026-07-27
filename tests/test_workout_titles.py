from __future__ import annotations

import unittest

from runplan.domain.estimates import estimate_steps
from runplan.domain.workout_titles import format_compact_distance, garmin_workout_title
from runplan.parsing.yaml_loader import load_program_model
from tests.helpers import program_data


class WorkoutTitleTests(unittest.TestCase):
    def test_formats_exact_distance_compactly(self) -> None:
        workout = load_program_model(program_data()).week(2).workouts[0]

        self.assertEqual("10k", format_compact_distance(estimate_steps(workout.steps)))
        self.assertEqual(
            "CHAR - W2 - Week 2 - Long - 10k",
            garmin_workout_title("CHAR", 2, workout),
        )

    def test_marks_distance_approximate_when_timed_steps_need_fallback_pace(self) -> None:
        workout = load_program_model(program_data()).week(1).workouts[0]

        estimate = estimate_steps(workout.steps)

        self.assertTrue(estimate.distance_is_approximate)
        self.assertAlmostEqual(2633.333, estimate.distance_meters, places=3)
        self.assertEqual("~2.6k", format_compact_distance(estimate))
        self.assertEqual(
            "CHAR - W1 - Mixed - ~2.6k",
            garmin_workout_title("CHAR", 1, workout, workout_name="Mixed"),
        )

    def test_timed_step_with_explicit_pace_is_not_marked_approximate(self) -> None:
        raw = program_data()
        raw["weeks"][0]["workouts"][0]["steps"] = [
            {"run": {"time": "10m", "pace": "5:00 min/km"}}
        ]
        workout = load_program_model(raw).week(1).workouts[0]

        estimate = estimate_steps(workout.steps)

        self.assertFalse(estimate.distance_is_approximate)
        self.assertEqual(2000, estimate.distance_meters)
        self.assertEqual("2k", format_compact_distance(estimate))


if __name__ == "__main__":
    unittest.main()
