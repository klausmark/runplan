from argparse import Namespace
from datetime import date
from pathlib import Path
import tempfile
import unittest

import yaml

from runplan.application.export import build_program_export
from runplan.application.presentation_weeks import build_presentation_weeks
from runplan.cli import prepare_sync_selections
from runplan.domain.selectors import WeekSelection
from runplan.parsing.yaml_loader import load_program_model


def saturday_program():
    def workout(identifier, day, name):
        return {
            "id": identifier,
            "day": day,
            "name": name,
            "steps": [{"run": "10m"}],
        }

    return {
        "program": {
            "id": "calendar-plan",
            "name": "Calendar plan",
            "short_name": "CAL",
            "start_week": "2026-W01",
        },
        "weeks": [
            {
                "week": 1,
                "focus": "First source focus",
                "workouts": [
                    workout("first", 1, "Week 1 - Monday run"),
                    workout("friday", 5, "Week 1 - Friday run"),
                    workout("saturday", 6, "Week 1 - Saturday run"),
                ],
            },
            {
                "week": 2,
                "focus": "Second source focus",
                "workouts": [workout("second", 1, "Week 2 - Monday run")],
            },
        ],
    }


class PresentationWeekTests(unittest.TestCase):
    def test_groups_calendar_weeks_without_rewriting_source_coordinates(self):
        weeks = build_presentation_weeks(load_program_model(saturday_program()))

        self.assertEqual([1, 2], [week.number for week in weeks])
        self.assertEqual(
            (date(2025, 12, 29), date(2026, 1, 4)),
            (weeks[0].start_date, weeks[0].end_date),
        )
        self.assertEqual(
            ["Monday run", "Friday run", "Saturday run"],
            [item.name for item in weeks[0].workouts],
        )
        self.assertEqual([2], [item.source_week for item in weeks[1].workouts])
        self.assertEqual([1], [item.source_day for item in weeks[1].workouts])
        self.assertEqual("Week 2 - Monday run", weeks[1].workouts[0].source_name)

    def test_export_selects_the_requested_calendar_aligned_week(self):
        export = build_program_export(
            load_program_model(saturday_program()), WeekSelection.explicit(2)
        )

        self.assertEqual([2], [week.number for week in export.weeks])
        self.assertEqual(
            ["Monday run"],
            [workout.name for workout in export.weeks[0].workouts],
        )
        self.assertEqual(
            [2], [workout.source_week for workout in export.weeks[0].workouts]
        )

    def test_sync_selection_preserves_source_names_weeks_and_dates(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory, "program.yaml")
            path.write_text(yaml.safe_dump(saturday_program()), encoding="utf-8")
            arguments = Namespace(
                yaml_file=path,
                select_weeks="2",
            )
            selections = prepare_sync_selections(arguments)

        self.assertEqual([2], [definition["week"] for definition, _ in selections])
        definitions = [item for _, compiled in selections for item, _ in compiled]
        self.assertEqual(
            ["CAL - W2 - Monday run - ~1.7k"],
            [item["name"] for item in definitions],
        )
        self.assertEqual(
            ["2026-01-05"],
            [item["schedule_date"] for item in definitions],
        )
        self.assertTrue(all(item["presentation_week"] == 2 for item in definitions))


if __name__ == "__main__":
    unittest.main()
