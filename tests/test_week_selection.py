from __future__ import annotations

from datetime import date

import pytest

from runplan.domain.selectors import WeekSelection, WeekSelectionError


def test_explicit_expression_is_sorted_and_deduplicated() -> None:
    selection = WeekSelection.explicit("5-7,1,3,3,6")

    assert selection.resolve(range(1, 9)) == (1, 3, 5, 6, 7)


def test_all_selects_every_available_week() -> None:
    assert WeekSelection.all().resolve((1, 2, 3)) == (1, 2, 3)


@pytest.mark.parametrize(
    ("selection", "expected"),
    [(WeekSelection.current(), (3,)), (WeekSelection.next(), (4,))],
)
def test_relative_selection_uses_injected_date(
    selection: WeekSelection, expected: tuple[int]
) -> None:
    result = selection.resolve(range(1, 6), start_date=date(2026, 7, 6), today=date(2026, 7, 20))

    assert result == expected


@pytest.mark.parametrize(
    ("today", "weeks_ahead", "expected"),
    [
        (date(2026, 7, 26), 1, (1, 2)),
        (date(2026, 7, 27), 1, (2, 3)),
        (date(2026, 8, 10), 2, (4,)),
    ],
)
def test_weeks_ahead_selects_current_and_complete_subsequent_weeks(
    today: date, weeks_ahead: int, expected: tuple[int, ...]
) -> None:
    result = WeekSelection.ahead(weeks_ahead).resolve(
        range(1, 5), start_date=date(2026, 7, 20), today=today
    )

    assert result == expected


@pytest.mark.parametrize("expression", ["", "3-1", "1,,2", "one", "0", "1-"])
def test_invalid_explicit_expression_is_rejected(expression: str) -> None:
    with pytest.raises(WeekSelectionError):
        WeekSelection.explicit(expression)


def test_explicit_unknown_week_is_rejected() -> None:
    with pytest.raises(WeekSelectionError, match="not in the program"):
        WeekSelection.explicit("2,5").resolve((1, 2, 3))


def test_relative_selection_without_start_date_is_rejected() -> None:
    with pytest.raises(WeekSelectionError, match="start date"):
        WeekSelection.current().resolve((1, 2))


def test_next_week_outside_program_is_rejected() -> None:
    with pytest.raises(WeekSelectionError, match="outside the program"):
        WeekSelection.next().resolve((1, 2), start_date=date(2026, 7, 6), today=date(2026, 7, 13))


@pytest.mark.parametrize("outside", [date(2026, 6, 29), date(2026, 7, 20)])
def test_current_week_outside_program_is_rejected(outside: date) -> None:
    with pytest.raises(WeekSelectionError, match="current plan week.*outside"):
        WeekSelection.ahead(1).resolve((1, 2), start_date=date(2026, 7, 6), today=outside)
