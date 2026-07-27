"""Human-readable preview formatting."""

from __future__ import annotations

from ..application.preview import PreviewResult
from .text import format_estimated_distance, format_weekday


def _format_total(duration: float, distance: float) -> str:
    parts: list[str] = []
    if duration:
        minutes, seconds = divmod(round(duration), 60)
        parts.append(f"{minutes} min" + (f" {seconds} sec" if seconds else ""))
    if distance:
        parts.append(format_estimated_distance(distance))
    return " + ".join(parts) or "0 sec"


def format_overview(preview: PreviewResult) -> str:
    """Format selected weeks for a human-readable terminal preview."""
    lines = [f"Program: {preview.program_id}"]
    for week in preview.weeks:
        lines.append(f"\nWeek {week.number} ({week.start_date} to {week.end_date})")
        for workout in week.workouts:
            lines.append(
                f"  {format_weekday(workout.date)} · {workout.name} · "
                f"{_format_total(workout.duration_seconds, workout.distance_meters)}"
            )
    if preview.sync_plan is not None:
        lines.append("\nSync changes:")
        for action in preview.sync_plan.actions:
            detail = f" on {action.date}" if action.date else ""
            lines.append(f"  {action.kind}: {action.name}{detail}")
    lines.append("\nDry run: No data was uploaded or deleted.")
    return "\n".join(lines)


__all__ = ["format_overview"]
