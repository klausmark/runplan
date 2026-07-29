"""Integration-independent workout step behavior."""

from __future__ import annotations

from typing import Any

from ..parsing.values import parse_step_end
from .errors import WorkoutDefinitionError

ACTION_NAMES = {
    "warmup": "warmup",
    "run": "run",
    "recovery": "walk",
    "cooldown": "cooldown",
    "repeat": "repeat",
}


def first_present(mapping: dict[str, Any], *keys: str, default: Any = None) -> Any:
    """Return the first value whose key exists in a mapping."""
    for key in keys:
        if key in mapping:
            return mapping[key]
    return default


def normalize_action(raw_action: Any, location: str) -> str:
    """Map a canonical YAML action name to its internal action."""
    if not isinstance(raw_action, str):
        raise WorkoutDefinitionError(f"{location}: the step name must be text")
    action = ACTION_NAMES.get(raw_action.strip().lower())
    if action is None:
        valid = "warmup, run, recovery, repeat or cooldown"
        raise WorkoutDefinitionError(f"{location}: unknown step {raw_action!r}; use {valid}")
    return action


def repeat_parts(value: Any, location: str) -> tuple[int, list[Any]]:
    """Validate and return repeat count and child steps."""
    if not isinstance(value, dict):
        raise WorkoutDefinitionError(f"{location}: 'repeat' must contain 'count' and 'steps'")
    count = value.get("count")
    child_steps = value.get("steps")
    if isinstance(count, bool) or not isinstance(count, int) or count <= 0:
        raise WorkoutDefinitionError(f"{location}.count: must be a positive integer")
    if not isinstance(child_steps, list) or not child_steps:
        raise WorkoutDefinitionError(f"{location}.steps: must be a non-empty list")
    return count, child_steps


def estimate_totals(step_definitions: list[Any], location: str = "steps") -> tuple[float, float]:
    """Calculate known seconds and meters, including nested repeats."""
    time_total = 0.0
    distance_total = 0.0
    for order, item in enumerate(step_definitions, start=1):
        item_location = f"{location}[{order}]"
        if not isinstance(item, dict) or len(item) != 1:
            raise WorkoutDefinitionError(f"{item_location}: each step must have exactly one action")
        raw_action, value = next(iter(item.items()))
        action = normalize_action(raw_action, item_location)
        if action == "repeat":
            count, child_steps = repeat_parts(value, item_location)
            child_time, child_distance = estimate_totals(child_steps, f"{item_location}.steps")
            time_total += count * child_time
            distance_total += count * child_distance
        else:
            kind, end_value = parse_step_end(value, item_location)
            if kind == "time":
                time_total += end_value
            else:
                distance_total += end_value
    return time_total, distance_total


def estimate_duration(step_definitions: list[Any], location: str = "steps") -> float:
    """Calculate known duration without inferring time from distance."""
    return estimate_totals(step_definitions, location)[0]


__all__ = [
    "estimate_duration",
    "estimate_totals",
    "first_present",
    "normalize_action",
    "repeat_parts",
]
