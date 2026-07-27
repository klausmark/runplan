"""Week selection value objects shared by sync, preview, and export."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from typing import Literal


class WeekSelectionError(ValueError):
    """Raised when a week selector is malformed or cannot be resolved."""


SelectionKind = Literal["explicit", "current", "next", "ahead", "all"]


@dataclass(frozen=True, slots=True)
class WeekSelection:
    kind: SelectionKind
    weeks: tuple[int, ...] = ()

    @classmethod
    def explicit(cls, expression: str | int) -> WeekSelection:
        """Parse a comma-separated expression containing weeks and ranges."""
        text = str(expression).strip()
        if not text:
            raise WeekSelectionError("week selection cannot be empty")
        selected: set[int] = set()
        for token in text.split(","):
            if not token or not re.fullmatch(r"\d+(?:-\d+)?", token):
                raise WeekSelectionError(f"invalid week selector {token!r}")
            if "-" in token:
                first, last = (int(value) for value in token.split("-", 1))
                if first <= 0 or last < first:
                    raise WeekSelectionError(f"invalid week range {token!r}")
                selected.update(range(first, last + 1))
            else:
                week = int(token)
                if week <= 0:
                    raise WeekSelectionError("week numbers must be positive")
                selected.add(week)
        return cls("explicit", tuple(sorted(selected)))

    @classmethod
    def current(cls) -> WeekSelection:
        return cls("current")

    @classmethod
    def next(cls) -> WeekSelection:
        return cls("next")

    @classmethod
    def all(cls) -> WeekSelection:
        return cls("all")

    @classmethod
    def ahead(cls, count: int) -> WeekSelection:
        """Select the current plan week and `count` subsequent weeks."""
        if isinstance(count, bool) or not isinstance(count, int) or count < 0:
            raise WeekSelectionError("weeks ahead must be a non-negative integer")
        return cls("ahead", (count,))

    @classmethod
    def parse(cls, expression: str) -> WeekSelection:
        """Parse explicit week expressions and named relative selectors."""
        text = expression.strip().lower()
        named = {"current": cls.current, "next": cls.next, "all": cls.all}
        return named[text]() if text in named else cls.explicit(expression)

    def resolve(
        self,
        available_weeks: tuple[int, ...] | range,
        *,
        start_date: date | None = None,
        today: date | None = None,
    ) -> tuple[int, ...]:
        """Resolve and validate this selection against a program."""
        available = tuple(available_weeks)
        if not available:
            raise WeekSelectionError("program has no available weeks")
        if self.kind == "all":
            return available
        if self.kind == "explicit":
            unknown = tuple(week for week in self.weeks if week not in available)
            if unknown:
                raise WeekSelectionError(
                    f"weeks {unknown} are not in the program"
                )
            return self.weeks
        if start_date is None:
            raise WeekSelectionError("relative selection requires a program start date")
        reference_date = today or date.today()
        current = (reference_date - start_date).days // 7 + 1
        if self.kind == "ahead":
            if current not in available:
                raise WeekSelectionError(
                    f"current plan week {current} is outside the program"
                )
            last = current + self.weeks[0]
            return tuple(week for week in available if current <= week <= last)
        offset = 1 if self.kind == "next" else 0
        number = current + offset
        if number not in available:
            raise WeekSelectionError(
                f"resolved week {number} is outside the program"
            )
        return (number,)


__all__ = ["SelectionKind", "WeekSelection", "WeekSelectionError"]
