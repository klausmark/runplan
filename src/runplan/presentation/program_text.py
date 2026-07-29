"""Detailed plain-text program export."""

from __future__ import annotations

from ..application.export import ProgramExport
from .text import (
    format_estimated_distance,
    format_model_steps,
    format_model_totals,
    format_seconds_compact,
    format_weekday,
)

SECTION_DIVIDER = "-" * 72


def format_program_text(program: ProgramExport) -> str:
    """Render a selected program as deterministic terminal-friendly text.

    Structural rationale: this is one serialization pass over a stable export model.
    """
    cover = [program.name]
    if program.description:
        cover.extend(("", program.description))
    cover.extend(
        (
            "",
            f"Start week: {program.start_week}",
            f"Program weeks: {program.total_weeks}",
            f"Selected weeks: {program.selected_week_count}",
            f"Total workouts: {program.summary.workout_count}",
            "Estimated total duration: "
            f"{format_seconds_compact(program.summary.estimated_duration_seconds)}",
            "Estimated total distance: "
            f"{format_estimated_distance(program.summary.estimated_distance_meters)}",
        )
    )

    sections = ["\n".join(cover)]
    for week in program.weeks:
        lines = [f"Week {week.number} ({week.start_date} to {week.end_date})"]
        if week.focus:
            lines.append(f"Focus: {week.focus}")
        lines.extend(
            (
                f"Workouts this week: {week.summary.workout_count}",
                "Estimated duration this week: "
                f"{format_seconds_compact(week.summary.estimated_duration_seconds)}",
                "Estimated distance this week: "
                f"{format_estimated_distance(week.summary.estimated_distance_meters)}",
            )
        )
        for workout in week.workouts:
            lines.append(
                f"\n{format_weekday(workout.date)} · {workout.name} · "
                + (
                    f"Actual {format_estimated_distance(workout.effective_distance_meters)} · {format_seconds_compact(workout.effective_duration_seconds)}"
                    if workout.totals_are_actual
                    else format_model_totals(workout.steps)
                )
            )
            if workout.description:
                lines.append(workout.description)
            lines.append(format_model_steps(workout.steps))
        sections.append("\n".join(lines))
    return f"\n\n{SECTION_DIVIDER}\n\n".join(sections)


__all__ = ["SECTION_DIVIDER", "format_program_text"]
