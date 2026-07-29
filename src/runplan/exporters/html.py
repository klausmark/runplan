"""Standalone HTML program export."""

from __future__ import annotations

import html
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


def format_program_html(program: ProgramExport) -> str:
    esc = html.escape
    parts = [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        f"  <title>{esc(program.name)}</title>",
        "  <style>body{font:16px/1.5 system-ui,sans-serif;max-width:54rem;margin:2rem auto;padding:0 1rem;color:#102a43}header,section{margin-bottom:3rem}section{break-before:page}h1,h2,h3{color:#183153}.summary{list-style:none;padding:0}.steps{background:#f0f4f8;padding:1rem;white-space:pre-wrap}article{margin:2rem 0}</style>",
        "</head>",
        "<body>",
        "<header>",
        f"  <h1>{esc(program.name)}</h1>",
    ]
    if program.description:
        parts.append(f"  <p>{esc(program.description)}</p>")
    parts.extend(
        (
            '  <ul class="summary">',
            f"    <li>Start week: {program.start_week}</li>",
            f"    <li>Program weeks: {program.total_weeks}</li>",
            f"    <li>Selected weeks: {program.selected_week_count}</li>",
            f"    <li>Total workouts: {program.summary.workout_count}</li>",
            "    <li>Estimated total duration: "
            f"{format_seconds_compact(program.summary.estimated_duration_seconds)}</li>",
            "    <li>Estimated total distance: "
            f"{format_estimated_distance(program.summary.estimated_distance_meters)}</li>",
            "  </ul>",
            "</header>",
        )
    )
    for week in program.weeks:
        parts.extend(
            (
                f'<section id="week-{week.number}">',
                f"  <h2>Week {week.number} · {week.start_date} to {week.end_date}</h2>",
            )
        )
        if week.focus:
            parts.append(f"  <p>Focus: {esc(week.focus)}</p>")
        parts.extend(
            (
                '  <ul class="summary">',
                f"    <li>Workouts this week: {week.summary.workout_count}</li>",
                "    <li>Estimated duration this week: "
                f"{format_seconds_compact(week.summary.estimated_duration_seconds)}</li>",
                "    <li>Estimated distance this week: "
                f"{format_estimated_distance(week.summary.estimated_distance_meters)}</li>",
                "  </ul>",
            )
        )
        for workout in week.workouts:
            parts.extend(
                (
                    "  <article>",
                    f"    <h3>{format_weekday(workout.date)} · {esc(workout.name)} · "
                    + (
                        f"Actual {format_estimated_distance(workout.effective_distance_meters)} · {format_seconds_compact(workout.effective_duration_seconds)}"
                        if workout.totals_are_actual
                        else format_model_totals(workout.steps)
                    )
                    + "</h3>",
                )
            )
            if workout.description:
                parts.append(f"    <p>{esc(workout.description)}</p>")
            parts.extend(
                (
                    f'    <pre class="steps">{esc(format_model_steps(workout.steps, indent=""))}</pre>',
                    "  </article>",
                )
            )
        parts.append("</section>")
    parts.extend(("</body>", "</html>"))
    return "\n".join(parts) + "\n"


def export_html(program: ProgramExport, output_path: Path, force: bool) -> None:
    write_export(format_program_html(program), output_path, force)


__all__ = ["export_html", "format_program_html"]
