import json
import unittest

from runplan.application.preview import build_preview
from runplan.application.results import SyncPlan
from runplan.presentation.json_output import format_json
from runplan.presentation.overview import format_overview
from tests.helpers import compiled_week


class PreviewFormatterTests(unittest.TestCase):
    def test_overview_formats_structured_multi_week_preview(self) -> None:
        preview = build_preview([compiled_week(1), compiled_week(2)])

        output = format_overview(preview)

        self.assertIn("Program: characterization-plan", output)
        self.assertIn("Week 1", output)
        self.assertIn("Week 2", output)
        self.assertIn("Monday · Week 1 - Mixed", output)
        self.assertIn("Thursday · Week 1 - Easy", output)
        self.assertIn("Sunday · Week 2 - Long", output)
        self.assertNotIn("2026-12-28 · Week 1 - Mixed", output)
        self.assertFalse(output.lstrip().startswith("{"))

    def test_json_formatter_returns_machine_readable_selected_weeks(self) -> None:
        preview = build_preview([compiled_week(1), compiled_week(2)])

        document = json.loads(format_json(preview))

        self.assertEqual("characterization-plan", document["programId"])
        self.assertEqual([1, 2], [week["week"] for week in document["weeks"]])

    def test_formatters_include_structured_sync_diff(self) -> None:
        plan = SyncPlan("characterization-plan", (1, 2))
        plan.add("reuse", "Kept workout", workout_id=10)
        plan.add("delete", "Old workout", workout_id=99)
        preview = build_preview([compiled_week(1), compiled_week(2)], plan)

        overview = format_overview(preview)
        document = json.loads(format_json(preview))

        self.assertIn("reuse: Kept workout", overview)
        self.assertIn("delete: Old workout", overview)
        self.assertEqual(
            ["reuse", "delete"],
            [action["kind"] for action in document["sync"]["actions"]],
        )


if __name__ == "__main__":
    unittest.main()
