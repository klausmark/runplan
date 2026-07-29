from __future__ import annotations

import unittest
from datetime import date

from runplan.domain.selectors import WeekSelection, WeekSelectionError


class WeekSelectionTests(unittest.TestCase):
    def test_explicit_expression_is_sorted_and_deduplicated(self) -> None:
        selection = WeekSelection.explicit("5-7,1,3,3,6")

        self.assertEqual((1, 3, 5, 6, 7), selection.resolve(range(1, 9)))

    def test_all_selects_every_available_week(self) -> None:
        self.assertEqual((1, 2, 3), WeekSelection.all().resolve((1, 2, 3)))

    def test_current_and_next_use_an_injected_date(self) -> None:
        start = date(2026, 7, 6)

        self.assertEqual(
            (3,),
            WeekSelection.current().resolve(range(1, 6), start_date=start, today=date(2026, 7, 20)),
        )
        self.assertEqual(
            (4,),
            WeekSelection.next().resolve(range(1, 6), start_date=start, today=date(2026, 7, 20)),
        )

    def test_weeks_ahead_selects_current_and_subsequent_complete_plan_weeks(self) -> None:
        start = date(2026, 7, 20)

        self.assertEqual(
            (1, 2),
            WeekSelection.ahead(1).resolve(range(1, 5), start_date=start, today=date(2026, 7, 26)),
        )
        self.assertEqual(
            (2, 3),
            WeekSelection.ahead(1).resolve(range(1, 5), start_date=start, today=date(2026, 7, 27)),
        )
        self.assertEqual(
            (4,),
            WeekSelection.ahead(2).resolve(range(1, 5), start_date=start, today=date(2026, 8, 10)),
        )

    def test_invalid_ranges_and_unknown_weeks_are_rejected(self) -> None:
        for expression in ("", "3-1", "1,,2", "one", "0", "1-"):
            with self.subTest(expression=expression), self.assertRaises(WeekSelectionError):
                WeekSelection.explicit(expression)

        with self.assertRaisesRegex(WeekSelectionError, "not in the program"):
            WeekSelection.explicit("2,5").resolve((1, 2, 3))

    def test_relative_selection_requires_dates_and_must_be_in_program(self) -> None:
        with self.assertRaisesRegex(WeekSelectionError, "start date"):
            WeekSelection.current().resolve((1, 2))

        with self.assertRaisesRegex(WeekSelectionError, "outside the program"):
            WeekSelection.next().resolve(
                (1, 2), start_date=date(2026, 7, 6), today=date(2026, 7, 13)
            )

        for outside in (date(2026, 6, 29), date(2026, 7, 20)):
            with (
                self.subTest(outside=outside),
                self.assertRaisesRegex(WeekSelectionError, "current plan week.*outside"),
            ):
                WeekSelection.ahead(1).resolve((1, 2), start_date=date(2026, 7, 6), today=outside)


if __name__ == "__main__":
    unittest.main()
