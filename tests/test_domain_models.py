from __future__ import annotations

import unittest
from datetime import date

from runplan import Program, Step, Workout, build_workout, load_program_model
from tests.helpers import normalized_program, program_data


class DomainModelTests(unittest.TestCase):
    def test_loads_complete_program_as_typed_recursive_models(self) -> None:
        program = load_program_model(program_data())

        self.assertIsInstance(program, Program)
        self.assertEqual("CHAR", program.short_name)
        self.assertEqual(date(2026, 12, 28), program.start_date)
        self.assertEqual("2026-W53", program.start_week)
        self.assertEqual((1, 2), tuple(week.number for week in program.weeks))
        workout = program.week(1).workouts[0]
        self.assertIsInstance(workout, Workout)
        repeat = workout.steps[1]
        self.assertIsInstance(repeat, Step)
        self.assertEqual("repeat", repeat.action)
        self.assertEqual(2, repeat.count)
        self.assertEqual(("run", "recovery"), tuple(step.action for step in repeat.steps))
        self.assertEqual((270, 285), repeat.steps[0].pace)

    def test_typed_workout_produces_same_garmin_payload_as_normalized_dict(self) -> None:
        program = load_program_model(program_data())
        typed_workout = program.week(1).workouts[0]
        normalized = normalized_program(1)["workouts"][0]

        self.assertEqual(
            build_workout(normalized).to_dict(),
            build_workout(typed_workout).to_dict(),
        )

    def test_invalid_repeat_model_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "positive count"):
            Step(action="repeat", count=0, steps=())

    def test_unknown_week_is_explicit(self) -> None:
        program = load_program_model(program_data())

        with self.assertRaisesRegex(KeyError, "does not contain week 9"):
            program.week(9)

    def test_workout_can_be_enriched_with_local_lifecycle_state(self) -> None:
        workout = load_program_model(program_data()).week(1).workouts[0]

        enriched = workout.with_lifecycle(
            {
                "status": "completed",
                "workout_id": 10,
                "schedule_id": 20,
                "activity_id": 30,
                "completed_at": "2026-12-28T12:00:00",
            }
        )

        self.assertEqual("planned", workout.status)
        self.assertEqual("completed", enriched.status)
        self.assertEqual(10, enriched.garmin_workout_id)
        self.assertEqual(20, enriched.garmin_schedule_id)
        self.assertEqual(30, enriched.activity_id)


if __name__ == "__main__":
    unittest.main()
