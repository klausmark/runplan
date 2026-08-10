"""Human-readable workout step and total formatting."""

from __future__ import annotations

from datetime import date
from typing import Any

from ..domain.models import Step
from ..domain.steps import (
    estimate_duration,
    estimate_totals,
    normalize_action,
    repeat_parts,
)
from ..parsing.values import parse_step_end, step_note, step_pace

WEEKDAYS = (
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
)


def format_weekday(value: str | date) -> str:
    """Return the weekday label used by human-readable plan renderers."""
    parsed = date.fromisoformat(value) if isinstance(value, str) else value
    return WEEKDAYS[parsed.weekday()]


def format_seconds_compact(seconds: float) -> str:
    whole_seconds = round(seconds)
    hours, remainder = divmod(whole_seconds, 3600)
    minutes, remaining = divmod(remainder, 60)
    parts = []
    if hours:
        parts.append(f"{hours} hr")
    if minutes:
        parts.append(f"{minutes} min")
    if remaining:
        parts.append(f"{remaining} sec")
    return " ".join(parts) or "0 sec"


def format_distance_compact(meters: float) -> str:
    return f"{meters / 1000:g} km" if meters >= 1000 else f"{meters:g} m"


def format_estimated_distance(meters: float) -> str:
    """Format an estimated total at a human-friendly precision."""
    if meters >= 1000:
        return f"{meters / 1000:.1f}".rstrip("0").rstrip(".") + " km"
    return f"{round(meters / 10) * 10:g} m"


def format_pace(pace: tuple[float, float]) -> str:
    def one(value: float) -> str:
        minutes, seconds = divmod(round(value), 60)
        return f"{minutes}:{seconds:02d}"

    fast, slow = pace
    return f"{one(fast)} min/km" if fast == slow else f"{one(fast)}-{one(slow)} min/km"


def format_model_step_value(step: Step) -> str:
    """Format the end condition, optional pace, and optional note of a typed step."""
    assert step.end_kind is not None and step.end_value is not None
    value = (
        format_seconds_compact(step.end_value)
        if step.end_kind == "time"
        else format_distance_compact(step.end_value)
    )
    parts = [value]
    if step.pace:
        parts.append(f"@ {format_pace(step.pace)}")
    if step.note:
        parts.append(f"— {step.note}")
    return " ".join(parts)


def _format_note(note: str | None) -> str:
    """Return the human-readable note suffix, or empty when absent."""
    return f" — {note}" if note else ""


def model_step_totals(steps: tuple[Step, ...]) -> tuple[float, float]:
    """Calculate known duration and distance from typed recursive steps."""
    duration = 0.0
    distance = 0.0
    for step in steps:
        multiplier = step.count or 1
        if step.action == "repeat":
            child_duration, child_distance = model_step_totals(step.steps)
            duration += multiplier * child_duration
            distance += multiplier * child_distance
        elif step.end_kind == "time":
            duration += step.end_value or 0
        else:
            distance += step.end_value or 0
    return duration, distance


def format_model_totals(steps: tuple[Step, ...]) -> str:
    duration, distance = model_step_totals(steps)
    parts = []
    if duration:
        parts.append(format_seconds_compact(duration))
    if distance:
        parts.append(format_distance_compact(distance))
    return " + ".join(parts) or "0 sec"


def format_model_steps(steps: tuple[Step, ...], indent: str = "  ") -> str:
    """Format typed recursive steps as indented human-readable lines."""
    labels = {
        "warmup": "Warmup",
        "run": "Run",
        "recovery": "Recovery",
        "cooldown": "Cooldown",
    }
    lines = []
    for step in steps:
        if step.action == "repeat":
            lines.append(f"{indent}Repeat {step.count} times:")
            lines.append(format_model_steps(step.steps, indent + "  "))
        else:
            lines.append(f"{indent}{labels[step.action]}: {format_model_step_value(step)}")
    return "\n".join(lines)


STEP_LABELS: dict[str, str] = {
    "warmup": "Warmup",
    "run": "Run",
    "recovery": "Recovery",
    "cooldown": "Cooldown",
}


def _step_view(step: Step) -> dict[str, Any]:
    """Return the renderer-independent view of one regular step."""
    assert step.end_kind is not None and step.end_value is not None
    return {
        "action": step.action,
        "kind_label": STEP_LABELS[step.action],
        "end_kind": step.end_kind,
        "end_value": step.end_value,
        "end_value_display": (
            format_seconds_compact(step.end_value)
            if step.end_kind == "time"
            else format_distance_compact(step.end_value)
        ),
        "pace_display": format_pace(step.pace) if step.pace else None,
        "note": step.note,
    }


def step_view(steps: tuple[Step, ...]) -> list[dict[str, Any]]:
    """Return a JSON-safe structured view of typed recursive steps."""
    result: list[dict[str, Any]] = []
    for step in steps:
        if step.action == "repeat":
            result.append(
                {
                    "action": "repeat",
                    "kind_label": "Repeat",
                    "count": step.count,
                    "steps": step_view(step.steps),
                }
            )
        else:
            result.append(_step_view(step))
    return result


def format_model_step_summary(steps: tuple[Step, ...]) -> str:
    """Format typed recursive steps on one compact line."""
    labels = {
        "warmup": "Warmup",
        "run": "Run",
        "recovery": "Recovery",
        "cooldown": "Cooldown",
    }
    parts = []
    for step in steps:
        if step.action == "repeat":
            parts.append(f"Repeat {step.count} times: {format_model_step_summary(step.steps)}")
        else:
            parts.append(f"{labels[step.action]} {format_model_step_value(step)}")
    return " · ".join(parts)


def format_step_value(value: Any, location: str) -> str:
    kind, end_value = parse_step_end(value, location)
    formatted = (
        format_seconds_compact(end_value) if kind == "time" else format_distance_compact(end_value)
    )
    pace = step_pace(value, location)
    return f"{formatted} @ {format_pace(pace)}" if pace else formatted


def format_totals(steps: list[Any]) -> str:
    duration, distance = estimate_totals(steps)
    parts = []
    if duration:
        parts.append(format_seconds_compact(duration))
    if distance:
        parts.append(format_distance_compact(distance))
    return " + ".join(parts) or "0 sec"


def step_summary(steps: list[Any]) -> str:
    labels = {"warmup": "Warmup", "run": "Run", "walk": "Recovery", "cooldown": "Cooldown"}
    parts = []
    for index, item in enumerate(steps, start=1):
        raw_action, value = next(iter(item.items()))
        action = normalize_action(raw_action, f"steps[{index}]")
        if action == "repeat":
            count, children = repeat_parts(value, f"steps[{index}]")
            parts.append(f"Repeat {count} times: {step_summary(children)}")
        else:
            location = f"steps[{index}]"
            note = step_note(value, location)
            parts.append(
                f"{labels[action]} {format_step_value(value, location)}{_format_note(note)}"
            )
    return " · ".join(parts)


def format_step_overview(steps: list[Any], indent: str = "    ") -> str:
    labels = {"warmup": "Warmup", "run": "Run", "walk": "Recovery", "cooldown": "Cooldown"}
    lines = []
    for index, item in enumerate(steps, start=1):
        raw_action, value = next(iter(item.items()))
        action = normalize_action(raw_action, f"steps[{index}]")
        if action == "repeat":
            count, children = repeat_parts(value, f"steps[{index}]")
            lines.append(f"{indent}Repeat {count} times:")
            lines.append(format_step_overview(children, indent + "  "))
        else:
            location = f"steps[{index}]"
            lines.append(f"{indent}{labels[action]}: {format_step_value(value, location)}")
    return "\n".join(lines)


__all__ = [
    "estimate_duration",
    "estimate_totals",
    "format_model_steps",
    "format_model_step_summary",
    "format_model_totals",
    "format_estimated_distance",
    "format_step_overview",
    "format_totals",
    "format_weekday",
    "step_summary",
    "step_view",
]
