"""Standalone HTML program export."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

from ..application.export import ProgramExport
from ..presentation.text import (
    format_estimated_distance,
    format_model_steps,
    format_model_totals,
    format_seconds_compact,
    format_weekday,
)
from .coaching_sections import coaching_lines
from .writer import write_export


def format_program_html(program: ProgramExport) -> str:
    """Render one complete export model as HTML from section serializers."""
    parts = _document_start(program) + _program_header(program)
    if program.coaching is not None:
        parts.extend(_coaching_html(program.coaching))
    parts.extend(line for week in program.weeks for line in _week_html(week))
    parts.extend(("</body>", "</html>"))
    return "\n".join(parts) + "\n"


def _document_start(program: ProgramExport) -> list[str]:
    return [
        "<!doctype html>",
        '<html lang="en">',
        "<head>",
        '  <meta charset="utf-8">',
        f"  <title>{html.escape(program.name)}</title>",
        "  <style>body{font:16px/1.5 system-ui,sans-serif;max-width:54rem;margin:2rem auto;padding:0 1rem;color:#102a43}header,section{margin-bottom:3rem}section{break-before:page}h1,h2,h3{color:#183153}.summary{list-style:none;padding:0}.steps{background:#f0f4f8;padding:1rem;white-space:pre-wrap}article{margin:2rem 0}.coaching table{border-collapse:collapse;width:100%}.coaching th,.coaching td{border:1px solid #cbd2d9;padding:.4rem .6rem;text-align:left;font-size:.9rem}.coaching th{background:#eef3f8}</style>",
        "</head>",
        "<body>",
    ]


def _program_header(program: ProgramExport) -> list[str]:
    result = ["<header>", f"  <h1>{html.escape(program.name)}</h1>"]
    if program.description:
        result.append(f"  <p>{html.escape(program.description)}</p>")
    result.extend(
        [
            '  <ul class="summary">',
            f"    <li>Start week: {program.start_week}</li>",
            f"    <li>Program weeks: {program.total_weeks}</li>",
            f"    <li>Selected weeks: {program.selected_week_count}</li>",
            f"    <li>Total workouts: {program.summary.workout_count}</li>",
            f"    <li>Estimated total duration: {format_seconds_compact(program.summary.estimated_duration_seconds)}</li>",
            f"    <li>Estimated total distance: {format_estimated_distance(program.summary.estimated_distance_meters)}</li>",
            "  </ul>",
            "</header>",
        ]
    )
    return result


def _coaching_html(guide) -> list[str]:
    sections = coaching_lines(guide)
    if not sections:
        return []
    lines = ['<section class="coaching">', "  <h2>Coaching guide</h2>"]
    for title, content in sections:
        if title == "__eyebrow__":
            lines.append(f"  <p><em>{html.escape(content[0])}</em></p>")
            continue
        lines.append(f"  <h3>{html.escape(title)}</h3>")
        lines.extend(_coaching_section_html(title, content))
    lines.append("</section>")
    return lines


def _coaching_section_html(title: str, content: list[str]) -> list[str]:
    blocks = _split_paragraphs(content)
    rendered: list[str] = []
    for block in blocks:
        kind = _classify_block(title, block)
        if kind == "table":
            rendered.extend(_render_table(block))
        elif kind == "list":
            rendered.append("  <ul>")
            rendered.extend(f"    <li>{html.escape(line[2:])}</li>" for line in block)
            rendered.append("  </ul>")
        else:
            rendered.append("  <p>" + "<br>".join(html.escape(line) for line in block) + "</p>")
    return rendered


def _split_paragraphs(content: list[str]) -> list[list[str]]:
    paragraphs: list[list[str]] = []
    current: list[str] = []
    for line in content:
        if line == "":
            if current:
                paragraphs.append(current)
                current = []
            continue
        current.append(line)
    if current:
        paragraphs.append(current)
    return paragraphs


def _classify_block(title: str, block: list[str]) -> str:
    if title == "Nike Run Club Pace Chart" and block and block[0].startswith("|"):
        return "table"
    if all(line.startswith("- ") for line in block):
        return "list"
    return "prose"


def _render_table(block: list[str]) -> list[str]:
    rows = [line for line in block if line.startswith("|")]
    if len(rows) < 3:
        return ["  <p>" + "<br>".join(html.escape(line) for line in block) + "</p>"]
    header_cells = [cell.strip() for cell in rows[0].strip("|").split("|")]
    body_rows = rows[2:]
    lines = ["  <table>"]
    lines.append(
        "    <thead><tr>"
        + "".join(f"<th>{html.escape(cell)}</th>" for cell in header_cells)
        + "</tr></thead>"
    )
    lines.append("    <tbody>")
    for row in body_rows:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        lines.append(
            "      <tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in cells) + "</tr>"
        )
    lines.append("    </tbody>")
    lines.append("  </table>")
    return lines


def _week_html(week: Any) -> list[str]:
    result = [
        f'<section id="week-{week.number}">',
        f"  <h2>Week {week.number} · {week.start_date} to {week.end_date}</h2>",
    ]
    if week.focus:
        result.append(f"  <p>Focus: {html.escape(week.focus)}</p>")
    result.extend(
        [
            '  <ul class="summary">',
            f"    <li>Workouts this week: {week.summary.workout_count}</li>",
            f"    <li>Estimated duration this week: {format_seconds_compact(week.summary.estimated_duration_seconds)}</li>",
            f"    <li>Estimated distance this week: {format_estimated_distance(week.summary.estimated_distance_meters)}</li>",
            "  </ul>",
        ]
    )
    result.extend(line for workout in week.workouts for line in _workout_html(workout))
    result.append("</section>")
    return result


def _workout_html(workout: Any) -> list[str]:
    totals = (
        f"Actual {format_estimated_distance(workout.effective_distance_meters)} · {format_seconds_compact(workout.effective_duration_seconds)}"
        if workout.totals_are_actual
        else format_model_totals(workout.steps)
    )
    result = [
        "  <article>",
        f"    <h3>{format_weekday(workout.date)} · {html.escape(workout.name)} · {totals}</h3>",
    ]
    if workout.description:
        result.append(f"    <p>{html.escape(workout.description)}</p>")
    result.extend(
        [
            f'    <pre class="steps">{html.escape(format_model_steps(workout.steps, indent=""))}</pre>',
            "  </article>",
        ]
    )
    return result


def export_html(program: ProgramExport, output_path: Path, force: bool) -> None:
    write_export(format_program_html(program), output_path, force)


__all__ = ["export_html", "format_program_html"]
