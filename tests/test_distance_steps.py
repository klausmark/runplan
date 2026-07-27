import unittest

from runplan import (
    WorkoutDefinitionError,
    compile_steps,
    estimate_totals,
    format_totals,
    parse_distance,
    parse_pace,
    parse_step_end,
    step_summary,
)


class DistanceStepTests(unittest.TestCase):
    def test_parses_meter_and_kilometer_distances(self) -> None:
        self.assertEqual(400, parse_distance("400m", "trin[1].distance"))
        self.assertEqual(1500, parse_distance("1.5km", "trin[1].distance"))

    def test_short_m_form_remains_minutes(self) -> None:
        self.assertEqual(("time", 120), parse_step_end("2m", "trin[1]"))
        self.assertEqual(
            ("distance", 2),
            parse_step_end({"distance": "2m"}, "trin[1]"),
        )

    def test_rejects_missing_unit_and_non_positive_distance(self) -> None:
        for value in ("400", "0m", 400):
            with self.subTest(value=value), self.assertRaises(WorkoutDefinitionError):
                parse_distance(value, "trin[1].distance")

    def test_compiles_distance_to_garmin_end_condition(self) -> None:
        for action in ("warmup", "run", "recovery", "cooldown"):
            with self.subTest(action=action):
                step = compile_steps([{action: {"distance": "400m"}}])[0]
                self.assertEqual("distance", step.endCondition["conditionTypeKey"])
                self.assertEqual(3, step.endCondition["conditionTypeId"])
                self.assertEqual(400, step.endConditionValue)

    def test_warmup_and_cooldown_do_not_assume_walking(self) -> None:
        warmup, cooldown = compile_steps([{"warmup": "5m"}, {"cooldown": "5m"}])

        self.assertEqual("Warm up", warmup.description)
        self.assertEqual("Cool down", cooldown.description)

    def test_danish_step_names_are_rejected(self) -> None:
        with self.assertRaisesRegex(WorkoutDefinitionError, "unknown step"):
            compile_steps([{"løb": "5m"}])

    def test_totals_include_nested_time_and_distance(self) -> None:
        steps = [
            {"warmup": "5m"},
            {
                "repeat": {
                    "count": 3,
                    "steps": [
                        {"run": {"distance": "400m"}},
                        {"recovery": {"time": "1m"}},
                    ],
                }
            },
            {"cooldown": {"distance": "1km"}},
        ]

        self.assertEqual((480, 2200), estimate_totals(steps))
        self.assertEqual("8 min + 2.2 km", format_totals(steps))
        self.assertIn("Run 400 m", step_summary(steps))

    def test_parses_and_compiles_pace_range(self) -> None:
        self.assertEqual(
            (270, 285),
            parse_pace("4:30-4:45 min/km", "trin[1].tempo"),
        )
        step = compile_steps(
            [
                {
                    "run": {
                        "distance": "400m",
                        "pace": "4:30-4:45 min/km",
                    }
                }
            ]
        )[0]

        self.assertEqual("pace.zone", step.targetType["workoutTargetTypeKey"])
        self.assertEqual(6, step.targetType["workoutTargetTypeId"])
        self.assertAlmostEqual(1000 / 285, step.targetValueOne)
        self.assertAlmostEqual(1000 / 270, step.targetValueTwo)

    def test_formats_pace_in_step_summary(self) -> None:
        summary = step_summary(
            [{"run": {"time": "5m", "pace": "5:00 min/km"}}]
        )
        self.assertEqual("Run 5 min @ 5:00 min/km", summary)

    def test_rejects_invalid_pace(self) -> None:
        for value in (
            "4.30 min/km",
            "4:60 min/km",
            "4:30 min/mile",
            "0:00 min/km",
            270,
        ):
            with self.subTest(value=value), self.assertRaises(WorkoutDefinitionError):
                parse_pace(value, "trin[1].tempo")

        with self.assertRaises(WorkoutDefinitionError):
            compile_steps([{"run": {"distance": "1km", "pace": None}}])

        with self.assertRaises(WorkoutDefinitionError):
            compile_steps(
                [
                    {
                        "run": {
                            "distance": "1km",
                            "tempo": "5:00 min/km",
                            "pace": "5:00 min/km",
                        }
                    }
                ]
            )


if __name__ == "__main__":
    unittest.main()
