"""Parse human-readable duration, distance and pace values."""

from __future__ import annotations

import re
from typing import Any

from ..domain.errors import WorkoutDefinitionError


def parse_duration(value: Any, location: str) -> float:
    """Convert a duration to seconds while retaining legacy input formats."""
    if isinstance(value, bool):
        raise WorkoutDefinitionError(f"{location}: a duration cannot be true/false")

    if isinstance(value, (int, float)):
        seconds = float(value)
        if seconds <= 0:
            raise WorkoutDefinitionError(f"{location}: the duration must be greater than 0")
        return seconds

    if not isinstance(value, str):
        raise WorkoutDefinitionError(
            f"{location}: the duration must be like 30s, 2m, or 00:30"
        )

    text = value.strip().lower()
    if not text:
        raise WorkoutDefinitionError(f"{location}: the duration is empty")

    if ":" in text:
        parts = text.split(":")
        if len(parts) not in (2, 3) or not all(part.isdigit() for part in parts):
            raise WorkoutDefinitionError(
                f"{location}: invalid time format {value!r}; use for example 02:30"
            )
        numbers = [int(part) for part in parts]
        if len(numbers) == 2:
            minutes, seconds = numbers
            total = minutes * 60 + seconds
        else:
            hours, minutes, seconds = numbers
            total = hours * 3600 + minutes * 60 + seconds
        if total <= 0:
            raise WorkoutDefinitionError(f"{location}: the duration must be greater than 0")
        return float(total)

    token_pattern = re.compile(r"(\d+(?:\.\d+)?)\s*([hms])", re.IGNORECASE)
    matches = list(token_pattern.finditer(text))
    compact_input = re.sub(r"\s+", "", text)
    compact_matches = "".join(
        match.group(0).replace(" ", "") for match in matches
    )
    if not matches or compact_matches != compact_input:
        raise WorkoutDefinitionError(
            f"{location}: invalid duration {value!r}; use for example 30s, 2m, or 1m30s"
        )

    factors = {"h": 3600.0, "m": 60.0, "s": 1.0}
    total = sum(
        float(match.group(1)) * factors[match.group(2).lower()]
        for match in matches
    )
    if total <= 0:
        raise WorkoutDefinitionError(f"{location}: the duration must be greater than 0")
    return total


def parse_distance(value: Any, location: str) -> float:
    """Convert a distance with an explicit unit to meters."""
    if not isinstance(value, str):
        raise WorkoutDefinitionError(
            f"{location}: the distance must be like 400m or 1.5km"
        )
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(m|km)\s*", value, re.IGNORECASE)
    if match is None:
        raise WorkoutDefinitionError(
            f"{location}: invalid distance {value!r}; use for example 400m or 1.5km"
        )
    factor = 1000.0 if match.group(2).lower() == "km" else 1.0
    distance = float(match.group(1)) * factor
    if distance <= 0:
        raise WorkoutDefinitionError(f"{location}: the distance must be greater than 0")
    return distance


def parse_step_end(value: Any, location: str) -> tuple[str, float]:
    """Parse a step end as seconds or meters."""
    if not isinstance(value, dict):
        return "time", parse_duration(value, location)
    end_keys = [key for key in value if key in ("time", "distance")]
    unknown_keys = [
        key
        for key in value
        if key not in ("time", "distance", "pace")
    ]
    if unknown_keys:
        raise WorkoutDefinitionError(
            f"{location}: unknown field {unknown_keys[0]!r}; use 'time', "
            "'distance' and optionally 'pace'"
        )
    if len(end_keys) != 1:
        raise WorkoutDefinitionError(
            f"{location}: the end condition must have exactly one field: 'time' or "
            "'distance'"
        )
    raw_kind = end_keys[0]
    raw_value = value[raw_kind]
    kind = raw_kind.strip().lower()
    if kind == "time":
        return "time", parse_duration(raw_value, f"{location}.{raw_kind}")
    return "distance", parse_distance(raw_value, f"{location}.distance")


def parse_pace(value: Any, location: str) -> tuple[float, float]:
    """Parse min/km pace and return fast/slow seconds per kilometer."""
    if not isinstance(value, str):
        raise WorkoutDefinitionError(
            f"{location}: the pace must be like '4:30-4:45 min/km'"
        )
    match = re.fullmatch(
        r"\s*(\d+):([0-5]\d)\s*(?:-\s*(\d+):([0-5]\d)\s*)?min/km\s*",
        value,
        re.IGNORECASE,
    )
    if match is None:
        raise WorkoutDefinitionError(
            f"{location}: invalid pace {value!r}; use for example '4:30 min/km' "
            "or '4:30-4:45 min/km'"
        )
    first = int(match.group(1)) * 60 + int(match.group(2))
    second = (
        int(match.group(3)) * 60 + int(match.group(4))
        if match.group(3) is not None
        else first
    )
    if first <= 0 or second <= 0:
        raise WorkoutDefinitionError(f"{location}: the pace must be greater than 0")
    return min(first, second), max(first, second)


def step_pace(value: Any, location: str) -> tuple[float, float] | None:
    """Return an optional pace target from a regular step."""
    if not isinstance(value, dict):
        return None
    pace_keys = [key for key in value if key == "pace"]
    if not pace_keys:
        return None
    if len(pace_keys) > 1:
        raise WorkoutDefinitionError(
            f"{location}: use only one pace field"
        )
    return parse_pace(value[pace_keys[0]], f"{location}.{pace_keys[0]}")


__all__ = [
    "parse_distance",
    "parse_duration",
    "parse_pace",
    "parse_step_end",
    "step_pace",
]
