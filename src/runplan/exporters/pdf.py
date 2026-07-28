"""PDF export implementation."""

from __future__ import annotations

import html
from pathlib import Path
from typing import Any

import reportlab
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from ..application.export import ProgramExport
from ..presentation.text import (
    format_estimated_distance,
    format_model_step_summary,
    format_model_totals,
    format_seconds_compact,
    format_weekday,
)


PAPER = colors.HexColor("#F6F5EF")
CARD = colors.HexColor("#FFFEF9")
INK = colors.HexColor("#17251F")
MUTED = colors.HexColor("#68756F")
LINE = colors.HexColor("#DEDFD7")
GREEN = colors.HexColor("#1D6B4D")
GREEN_DARK = colors.HexColor("#124D38")


def _draw_runplan_mark(canvas: Any, x: float, y: float, size: float) -> None:
    """Draw the canonical 64-unit Runplan mark on a ReportLab canvas."""
    canvas.saveState()
    canvas.translate(x + size / 2, y + size / 2)
    # SVG uses a downward y-axis, so its -4 degree rotation is +4 in PDF space.
    canvas.rotate(4)
    canvas.scale(size / 64, -size / 64)
    canvas.translate(-32, -32)
    canvas.setFillColor(GREEN)
    canvas.roundRect(7, 7, 50, 50, 15, fill=1, stroke=0)

    glyph = canvas.beginPath()
    glyph.moveTo(20, 49)
    glyph.lineTo(20, 15)
    glyph.lineTo(35, 15)
    glyph.curveTo(43, 15, 48, 19.7, 48, 27)
    glyph.curveTo(48, 31, 45.5, 34.5, 41, 36)
    glyph.lineTo(50, 43)
    glyph.lineTo(44, 49)
    glyph.lineTo(35, 42)
    glyph.lineTo(31, 39)
    glyph.lineTo(28, 39)
    glyph.lineTo(28, 49)
    glyph.close()
    glyph.moveTo(28, 22)
    glyph.lineTo(28, 32)
    glyph.lineTo(35, 32)
    glyph.curveTo(38.6, 32, 41, 30, 41, 27)
    glyph.curveTo(41, 24, 38.6, 22, 35, 22)
    glyph.close()
    canvas.setFillColor(colors.white)
    canvas.drawPath(glyph, fill=1, stroke=0, fillMode=0)
    canvas.restoreState()


class RunplanMark(Flowable):
    """The canonical Runplan mark used by the web application."""

    def __init__(self, size: float = 18 * mm) -> None:
        super().__init__()
        self.width = size
        self.height = size

    def draw(self) -> None:
        _draw_runplan_mark(self.canv, 0, 0, self.width)


def register_pdf_fonts() -> tuple[str, str]:
    """Register ReportLab's bundled Unicode fonts for embedded, portable PDFs."""
    fonts_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    regular_name = "RunplanVera"
    bold_name = "RunplanVeraBold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, fonts_dir / "Vera.ttf"))
        pdfmetrics.registerFont(TTFont(bold_name, fonts_dir / "VeraBd.ttf"))
    return regular_name, bold_name


def export_pdf(program: ProgramExport, output_path: Path, force: bool) -> None:
    """Export the complete validated program using the web UI's visual identity."""
    output_path = output_path.expanduser().resolve()
    if output_path.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {output_path}\nUse --force to overwrite it."
        )
    if not output_path.parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {output_path.parent}")

    regular_font, bold_font = register_pdf_fonts()
    styles = getSampleStyleSheet()
    eyebrow_style = ParagraphStyle(
        "RunplanEyebrow",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=8,
        leading=10,
        textColor=GREEN,
        spaceAfter=3 * mm,
    )
    title_style = ParagraphStyle(
        "RunplanTitle",
        parent=styles["Title"],
        fontName=bold_font,
        fontSize=29,
        leading=34,
        alignment=TA_LEFT,
        textColor=INK,
        spaceAfter=4 * mm,
    )
    subtitle_style = ParagraphStyle(
        "RunplanSubtitle",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=10.5,
        leading=16,
        textColor=MUTED,
        spaceAfter=3 * mm,
    )
    week_number_style = ParagraphStyle(
        "RunplanWeekNumber",
        parent=styles["Heading1"],
        fontName=bold_font,
        fontSize=21,
        leading=25,
        textColor=INK,
        spaceAfter=1.5 * mm,
    )
    week_date_style = ParagraphStyle(
        "RunplanWeekDate",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=9,
        leading=12,
        textColor=MUTED,
    )
    focus_style = ParagraphStyle(
        "RunplanFocus",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=9.5,
        leading=14,
        textColor=INK,
        spaceBefore=2 * mm,
    )
    stat_value_style = ParagraphStyle(
        "RunplanStatValue",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=12,
        leading=15,
        alignment=TA_CENTER,
        textColor=GREEN_DARK,
    )
    stat_label_style = ParagraphStyle(
        "RunplanStatLabel",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=7,
        leading=9,
        alignment=TA_CENTER,
        textColor=MUTED,
    )
    workout_day_style = ParagraphStyle(
        "RunplanWorkoutDay",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=8,
        leading=10,
        textColor=GREEN,
        spaceAfter=0.5 * mm,
    )
    workout_date_style = ParagraphStyle(
        "RunplanWorkoutDate",
        parent=styles["Normal"],
        fontName=regular_font,
        fontSize=7.5,
        leading=9,
        textColor=MUTED,
    )
    workout_total_style = ParagraphStyle(
        "RunplanWorkoutTotal",
        parent=styles["Normal"],
        fontName=bold_font,
        fontSize=8,
        leading=11,
        alignment=TA_RIGHT,
        textColor=GREEN_DARK,
    )
    workout_style = ParagraphStyle(
        "RunplanWorkout",
        parent=styles["Heading2"],
        fontName=bold_font,
        fontSize=11.5,
        leading=14,
        textColor=INK,
        spaceAfter=1.5 * mm,
    )
    body_style = ParagraphStyle(
        "RunplanBody",
        parent=styles["BodyText"],
        fontName=regular_font,
        fontSize=8.5,
        leading=12,
        textColor=MUTED,
        spaceAfter=2 * mm,
    )
    steps_style = ParagraphStyle(
        "RunplanSteps",
        parent=body_style,
        fontSize=8,
        leading=11,
        textColor=GREEN_DARK,
        spaceBefore=0.5 * mm,
        spaceAfter=0,
    )

    document = SimpleDocTemplate(
        str(output_path),
        pagesize=A4,
        rightMargin=18 * mm,
        leftMargin=18 * mm,
        topMargin=16 * mm,
        bottomMargin=19 * mm,
        title=program.name,
        author="Runplan",
        subject="Training plan",
        invariant=1,
    )
    content_width = A4[0] - document.leftMargin - document.rightMargin

    def paint_page(canvas: Any, doc: Any, *, footer: bool) -> None:
        canvas.saveState()
        canvas.setFillColor(PAPER)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        if footer:
            canvas.setStrokeColor(LINE)
            canvas.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
            _draw_runplan_mark(canvas, 18 * mm, 5.3 * mm, 5 * mm)
            canvas.setFillColor(GREEN)
            canvas.setFont(bold_font, 8)
            canvas.drawString(25 * mm, 7.5 * mm, "RUNPLAN")
            canvas.setFillColor(MUTED)
            canvas.setFont(regular_font, 8)
            canvas.drawRightString(A4[0] - 18 * mm, 7.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    def cover_page(canvas: Any, doc: Any) -> None:
        paint_page(canvas, doc, footer=False)

    def content_page(canvas: Any, doc: Any) -> None:
        paint_page(canvas, doc, footer=True)

    def stat_card(value: str, label: str) -> list[Paragraph]:
        return [
            Paragraph(html.escape(value), stat_value_style),
            Paragraph(html.escape(label), stat_label_style),
        ]

    selected_dates = ""
    if program.weeks:
        selected_dates = (
            f"{program.weeks[0].start_date:%d %b %Y} – "
            f"{program.weeks[-1].end_date:%d %b %Y}"
        )

    cover_stats = Table(
        [[
            stat_card(str(program.selected_week_count), "SELECTED WEEKS"),
            stat_card(str(program.summary.workout_count), "WORKOUTS"),
            stat_card(
                format_seconds_compact(program.summary.estimated_duration_seconds),
                "DURATION",
            ),
            stat_card(
                format_estimated_distance(program.summary.estimated_distance_meters),
                "DISTANCE",
            ),
        ]],
        colWidths=[content_width / 4] * 4,
    )
    cover_stats.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CARD),
        ("BOX", (0, 0), (-1, -1), 0.7, LINE),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))

    story: list[Any] = [
        Spacer(1, 16 * mm),
        RunplanMark(),
        Spacer(1, 15 * mm),
        Paragraph("RUNPLAN · TRAINING PLAN", eyebrow_style),
        Paragraph(html.escape(program.name), title_style),
    ]
    if program.description:
        story.append(Paragraph(html.escape(program.description), subtitle_style))
    if selected_dates:
        story.append(Paragraph(html.escape(selected_dates), subtitle_style))
    story.extend([
        Spacer(1, 12 * mm),
        cover_stats,
        Spacer(1, 9 * mm),
        Paragraph(
            f"Start week: {program.start_week}<br/>"
            f"Program weeks: {program.total_weeks}<br/>"
            f"Selected weeks: {program.selected_week_count}<br/>"
            f"Total workouts: {program.summary.workout_count}<br/>"
            "Estimated total duration: "
            f"{format_seconds_compact(program.summary.estimated_duration_seconds)}<br/>"
            "Estimated total distance: "
            f"{format_estimated_distance(program.summary.estimated_distance_meters)}",
            subtitle_style,
        ),
        PageBreak(),
    ])

    for week_index, week in enumerate(program.weeks):
        header_left: list[Paragraph] = [
            Paragraph("TRAINING WEEK", eyebrow_style),
            Paragraph(f"Week {week.number}", week_number_style),
            Paragraph(
                f"{week.start_date:%d %b} – {week.end_date:%d %b %Y}",
                week_date_style,
            ),
        ]
        if week.focus:
            header_left.append(
                Paragraph(f"<b>Focus</b> · {html.escape(week.focus)}", focus_style)
            )
        week_stats = Table(
            [[
                stat_card(str(week.summary.workout_count), "WORKOUTS"),
                stat_card(
                    format_seconds_compact(week.summary.estimated_duration_seconds),
                    "DURATION",
                ),
                stat_card(
                    format_estimated_distance(week.summary.estimated_distance_meters),
                    "DISTANCE",
                ),
            ]],
            colWidths=[29 * mm] * 3,
        )
        week_stats.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("LEFTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 2 * mm),
            ("INNERGRID", (0, 0), (-1, -1), 0.5, LINE),
        ]))
        week_header = Table(
            [[header_left, week_stats]],
            colWidths=[content_width - 91 * mm, 91 * mm],
        )
        week_header.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), CARD),
            ("BOX", (0, 0), (-1, -1), 0.7, LINE),
            ("LINEBEFORE", (0, 0), (0, -1), 3, GREEN),
            ("LEFTPADDING", (0, 0), (0, 0), 6 * mm),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 5 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 5 * mm),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ]))
        story.extend([week_header, Spacer(1, 3 * mm)])

        for workout in week.workouts:
            day_content = [
                Paragraph(format_weekday(workout.date).upper(), workout_day_style),
                Paragraph(f"{workout.date:%d %b}".upper(), workout_date_style),
            ]
            workout_content: list[Paragraph] = [
                Paragraph(html.escape(workout.name), workout_style),
            ]
            if workout.description:
                workout_content.append(
                    Paragraph(html.escape(workout.description), body_style)
                )
            workout_content.append(
                Paragraph(html.escape(format_model_step_summary(workout.steps)), steps_style)
            )
            workout_row = Table(
                [[
                    day_content,
                    workout_content,
                    Paragraph(
                        html.escape(
                            f"{'Actual' if workout.totals_are_actual else 'Planned'} "
                            f"{format_estimated_distance(workout.effective_distance_meters)} · "
                            f"{format_seconds_compact(workout.effective_duration_seconds)}"
                        ),
                        workout_total_style,
                    ),
                ]],
                colWidths=[25 * mm, content_width - 58 * mm, 33 * mm],
            )
            workout_row.setStyle(TableStyle([
                ("LINEBELOW", (0, 0), (-1, -1), 0.6, LINE),
                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                ("RIGHTPADDING", (0, 0), (0, 0), 4 * mm),
                ("RIGHTPADDING", (1, 0), (1, 0), 4 * mm),
                ("RIGHTPADDING", (2, 0), (2, 0), 0),
                ("TOPPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5 * mm),
                ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ]))
            story.append(KeepTogether(workout_row))

        if week_index < len(program.weeks) - 1:
            story.append(PageBreak())

    document.build(story, onFirstPage=cover_page, onLaterPages=content_page)


__all__ = ["export_pdf", "register_pdf_fonts"]
