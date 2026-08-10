"""Build ReportLab flowables for a Runplan training program."""

from __future__ import annotations

import html
import re
from typing import Any

from reportlab.lib.units import mm
from reportlab.platypus import KeepTogether, PageBreak, Paragraph, Spacer, Table, TableStyle

from ..application.export import ProgramExport
from ..presentation.text import (
    format_estimated_distance,
    format_model_step_summary,
    format_seconds_compact,
    format_weekday,
)
from .coaching_sections import coaching_lines
from .pdf_brand import RunplanMark
from .pdf_styles import PdfStyles
from .pdf_theme import CARD, GREEN, LINE

_BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
_ITALIC_PATTERN = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_LIST_INDENT = "    "


def build_pdf_story(program: ProgramExport, width: float, styles: PdfStyles) -> list[Any]:
    """Build the cover followed by one page of flowables per selected week."""
    story = _cover(program, width, styles)
    if program.coaching is not None and coaching_lines(program.coaching):
        story.extend(_coaching_section(program.coaching, width, styles))
        story.append(PageBreak())
    for index, week in enumerate(program.weeks):
        story.extend([_week_header(week, width, styles), Spacer(1, 3 * mm)])
        story.extend(
            KeepTogether(_workout_row(workout, width, styles)) for workout in week.workouts
        )
        if index < len(program.weeks) - 1:
            story.append(PageBreak())
    return story


def _coaching_section(guide, width: float, styles: PdfStyles) -> list[Any]:
    flowables: list[Any] = []
    flowables.append(Paragraph("COACHING GUIDE", styles.eyebrow))
    flowables.append(Paragraph("Read before you start", styles.title))
    if guide.tagline:
        flowables.append(Paragraph(f"<i>{html.escape(guide.tagline)}</i>", styles.subtitle))
    flowables.append(Spacer(1, 6 * mm))

    for title, content in coaching_lines(guide):
        if title == "__eyebrow__":
            continue
        flowables.append(Paragraph(html.escape(title), styles.week_number))
        flowables.extend(_coaching_blocks(content, width, styles))
        flowables.append(Spacer(1, 4 * mm))
    return flowables


def _coaching_blocks(content: list[str], width: float, styles: PdfStyles) -> list[Any]:
    flowables: list[Any] = []
    for kind, lines in _split_coaching_blocks(content):
        if kind == "table":
            flowables.extend(_coaching_table(lines, width, styles))
        elif kind == "list":
            flowables.extend(_coaching_list(lines, styles))
        else:
            flowables.extend(_coaching_prose(lines, styles))
    return flowables


def _split_coaching_blocks(content: list[str]) -> list[tuple[str, list[str]]]:
    blocks: list[tuple[str, list[str]]] = []
    current: list[str] = []
    current_kind: str | None = None

    def flush() -> None:
        nonlocal current, current_kind
        if current:
            blocks.append((current_kind or "prose", current))
            current = []
            current_kind = None

    for line in content:
        if line == "":
            flush()
            continue
        kind = _classify_line(line)
        if kind != current_kind:
            flush()
            current_kind = kind
        current.append(line)
    flush()
    return blocks


def _classify_line(line: str) -> str:
    if line.startswith("|"):
        return "table"
    if line.lstrip().startswith("- "):
        return "list"
    return "prose"


def _coaching_prose(lines: list[str], styles: PdfStyles) -> list[Any]:
    flowables: list[Any] = []
    for line in lines:
        if line == "":
            flowables.append(Spacer(1, 1 * mm))
            continue
        flowables.append(Paragraph(_inline_markup(line), styles.body))
    return flowables


def _coaching_list(lines: list[str], styles: PdfStyles) -> list[Any]:
    flowables: list[Any] = []
    for line in lines:
        if line.startswith("  - "):
            prefix = _LIST_INDENT + _LIST_INDENT + "\u2022\u00a0"
            item = line[4:]
        else:
            prefix = _LIST_INDENT + "\u2022\u00a0"
            item = line[2:]
        flowables.append(Paragraph(f"{prefix}{_inline_markup(item)}", styles.body))
    return flowables


def _coaching_table(lines: list[str], width: float, styles: PdfStyles) -> list[Any]:
    rows = [line for line in lines if line.startswith("|")]
    if len(rows) < 3:
        return _coaching_prose(lines, styles)
    header = [cell.strip() for cell in rows[0].strip("|").split("|")]
    data: list[list[Any]] = [
        [Paragraph(f"<b>{_inline_markup(cell)}</b>", styles.body) for cell in header]
    ]
    for row in rows[2:]:
        cells = [cell.strip() for cell in row.strip("|").split("|")]
        data.append([Paragraph(_inline_markup(cell), styles.body) for cell in cells])
    col_width = width / len(header)
    table = Table(data, colWidths=[col_width] * len(header), repeatRows=1)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), CARD),
                ("BOX", (0, 0), (-1, -1), 0.5, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.3, LINE),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 1.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 1.5 * mm),
            ]
        )
    )
    return [table]


def _inline_markup(text: str) -> str:
    escaped = html.escape(text)
    placeholders: list[str] = []

    def stash(match: re.Match[str]) -> str:
        placeholders.append(f"<b>{match.group(1)}</b>")
        return f"\x00{len(placeholders) - 1}\x00"

    escaped = _BOLD_PATTERN.sub(stash, escaped)
    escaped = _ITALIC_PATTERN.sub(lambda m: f"<i>{m.group(1)}</i>", escaped)
    for index, snippet in enumerate(placeholders):
        escaped = escaped.replace(f"\x00{index}\x00", snippet)
    return escaped


def _stat(value: str, label: str, styles: PdfStyles) -> list[Paragraph]:
    return [
        Paragraph(html.escape(value), styles.stat_value),
        Paragraph(html.escape(label), styles.stat_label),
    ]


def _cover(program: ProgramExport, width: float, styles: PdfStyles) -> list[Any]:
    """Assemble the single cover-page layout and its summary card.

    Structural rationale: the flowables jointly define one indivisible cover component.
    """
    stats = Table(
        [
            [
                _stat(str(program.selected_week_count), "SELECTED WEEKS", styles),
                _stat(str(program.summary.workout_count), "WORKOUTS", styles),
                _stat(
                    format_seconds_compact(program.summary.estimated_duration_seconds),
                    "DURATION",
                    styles,
                ),
                _stat(
                    format_estimated_distance(program.summary.estimated_distance_meters),
                    "DISTANCE",
                    styles,
                ),
            ]
        ],
        colWidths=[width / 4] * 4,
    )
    stats.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    story: list[Any] = [
        Spacer(1, 16 * mm),
        RunplanMark(),
        Spacer(1, 15 * mm),
        Paragraph("RUNPLAN · TRAINING PLAN", styles.eyebrow),
        Paragraph(html.escape(program.name), styles.title),
    ]
    if program.description:
        story.append(Paragraph(html.escape(program.description), styles.subtitle))
    if program.weeks:
        dates = f"{program.weeks[0].start_date:%d %b %Y} – {program.weeks[-1].end_date:%d %b %Y}"
        story.append(Paragraph(html.escape(dates), styles.subtitle))
    story.extend(
        [Spacer(1, 12 * mm), stats, Spacer(1, 9 * mm), _cover_details(program, styles), PageBreak()]
    )
    return story


def _cover_details(program: ProgramExport, styles: PdfStyles) -> Paragraph:
    return Paragraph(
        f"Start week: {program.start_week}<br/>Program weeks: {program.total_weeks}<br/>"
        f"Selected weeks: {program.selected_week_count}<br/>Total workouts: {program.summary.workout_count}<br/>"
        f"Estimated total duration: {format_seconds_compact(program.summary.estimated_duration_seconds)}<br/>"
        f"Estimated total distance: {format_estimated_distance(program.summary.estimated_distance_meters)}",
        styles.subtitle,
    )


def _week_header(week: Any, width: float, styles: PdfStyles) -> Table:
    """Assemble the single week-header table and its summary cells.

    Structural rationale: the nested tables jointly define one week-header component.
    """
    left: list[Paragraph] = [
        Paragraph("TRAINING WEEK", styles.eyebrow),
        Paragraph(f"Week {week.number}", styles.week_number),
        Paragraph(f"{week.start_date:%d %b} – {week.end_date:%d %b %Y}", styles.week_date),
    ]
    if week.focus:
        left.append(Paragraph(f"<b>Focus</b> · {html.escape(week.focus)}", styles.focus))
    stats = Table(
        [
            [
                _stat(str(week.summary.workout_count), "WORKOUTS", styles),
                _stat(
                    format_seconds_compact(week.summary.estimated_duration_seconds),
                    "DURATION",
                    styles,
                ),
                _stat(
                    format_estimated_distance(week.summary.estimated_distance_meters),
                    "DISTANCE",
                    styles,
                ),
            ]
        ],
        colWidths=[29 * mm] * 3,
    )
    stats.setStyle(
        TableStyle(
            [
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
                ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
            ]
        )
    )
    header = Table([[left, stats]], colWidths=[width - 91 * mm, 91 * mm])
    header.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, -1), CARD),
                ("BOX", (0, 0), (-1, -1), 0.7, LINE),
                ("LINEBEFORE", (0, 0), (0, -1), 3, GREEN),
                ("LEFTPADDING", (0, 0), (0, 0), 6 * mm),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
                ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ]
        )
    )
    return header


def _workout_row(workout: Any, width: float, styles: PdfStyles) -> Table:
    day = [
        Paragraph(format_weekday(workout.date).upper(), styles.workout_day),
        Paragraph(f"{workout.date:%d %b}".upper(), styles.workout_date),
    ]
    detail: list[Paragraph] = [Paragraph(html.escape(workout.name), styles.workout)]
    if workout.description:
        detail.append(Paragraph(html.escape(workout.description), styles.body))
    detail.append(Paragraph(html.escape(format_model_step_summary(workout.steps)), styles.steps))
    label = "Actual" if workout.totals_are_actual else "Planned"
    total = Paragraph(
        html.escape(
            f"{label} {format_estimated_distance(workout.effective_distance_meters)} · {format_seconds_compact(workout.effective_duration_seconds)}"
        ),
        styles.workout_total,
    )
    row = Table([[day, detail, total]], colWidths=[25 * mm, width - 58 * mm, 33 * mm])
    row.setStyle(
        TableStyle(
            [
                ("LINEBELOW", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (1, 0), (1, 0), 4 * mm),
                ("RIGHTPADDING", (2, 0), (2, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]
        )
    )
    return row
