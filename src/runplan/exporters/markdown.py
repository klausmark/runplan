"""Deterministic CommonMark program export."""

from __future__ import annotations

import re
from pathlib import Path

from ..application.export import ProgramExport
from ..presentation.text import (
    format_estimated_distance,
    format_model_steps,
    format_model_totals,
    format_seconds_compact,
    format_weekday,
)
from .writer import write_export


def _escape(value: str) -> str:
    return re.sub(r"([\\`*\[\]_<>])", r"\\\1", value)


def format_program_markdown(program: ProgramExport) -> str:
    """Render one complete export model as Markdown.

    Structural rationale: the function performs one deterministic serialization; its
    length reflects the document sections rather than independent business rules.
    """
    lines = [f"# {_escape(program.name)}"]
    if program.description:
        lines.extend(("", _escape(program.description)))
    lines.extend(
        (
            "",
            f"- Start week: {program.start_week}",
            f"- Program weeks: {program.total_weeks}",
            f"- Selected weeks: {program.selected_week_count}",
            f"- Total workouts: {program.summary.workout_count}",
            "- Estimated total duration: "
            f"{format_seconds_compact(program.summary.estimated_duration_seconds)}",
            "- Estimated total distance: "
            f"{format_estimated_distance(program.summary.estimated_distance_meters)}",
        )
    )
    for week in program.weeks:
        lines.extend(
            (
                "",
                "---",
                "",
                f"## Week {week.number} · {week.start_date} to {week.end_date}",
            )
        )
        if week.focus:
            lines.extend(("", f"Focus: {_escape(week.focus)}"))
        lines.extend(
            (
                "",
                f"- Workouts this week: {week.summary.workout_count}",
                "- Estimated duration this week: "
                f"{format_seconds_compact(week.summary.estimated_duration_seconds)}",
                "- Estimated distance this week: "
                f"{format_estimated_distance(week.summary.estimated_distance_meters)}",
            )
        )
        for workout in week.workouts:
            lines.extend(
                (
                    "",
                    f"### {format_weekday(workout.date)} · {_escape(workout.name)} · "
                    + (
                        f"Actual {format_estimated_distance(workout.effective_distance_meters)} · {format_seconds_compact(workout.effective_duration_seconds)}"
                        if workout.totals_are_actual
                        else format_model_totals(workout.steps)
                    ),
                )
            )
            if workout.description:
                lines.extend(("", _escape(workout.description)))
            lines.extend(("", "```text", format_model_steps(workout.steps, indent=""), "```"))
    return "\n".join(lines) + "\n"


def export_markdown(program: ProgramExport, output_path: Path, force: bool) -> None:
    write_export(format_program_markdown(program), output_path, force)


__all__ = ["export_markdown", "format_program_markdown"]
