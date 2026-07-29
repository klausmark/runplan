"""Construct the named paragraph styles used by Runplan PDFs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm

from .pdf_theme import GREEN, GREEN_DARK, INK, MUTED


@dataclass(frozen=True)
class PdfStyles:
    eyebrow: ParagraphStyle
    title: ParagraphStyle
    subtitle: ParagraphStyle
    week_number: ParagraphStyle
    week_date: ParagraphStyle
    focus: ParagraphStyle
    stat_value: ParagraphStyle
    stat_label: ParagraphStyle
    workout_day: ParagraphStyle
    workout_date: ParagraphStyle
    workout_total: ParagraphStyle
    workout: ParagraphStyle
    body: ParagraphStyle
    steps: ParagraphStyle


def build_pdf_styles(regular_font: str, bold_font: str) -> PdfStyles:
    """Create the complete immutable style catalog."""
    base = getSampleStyleSheet()
    shared = {"regular": regular_font, "bold": bold_font, "base": base}
    return PdfStyles(
        **_document_styles(**shared), **_week_styles(**shared), **_workout_styles(**shared)
    )


def _style(name: str, parent: ParagraphStyle, font: str, **values: Any) -> ParagraphStyle:
    return ParagraphStyle(name, parent=parent, fontName=font, **values)


def _document_styles(regular: str, bold: str, base: Any) -> dict[str, ParagraphStyle]:
    normal = base["Normal"]
    return {
        "eyebrow": _style(
            "RunplanEyebrow",
            normal,
            bold,
            fontSize=8,
            leading=10,
            textColor=GREEN,
            spaceAfter=3 * mm,
        ),
        "title": _style(
            "RunplanTitle",
            base["Title"],
            bold,
            fontSize=29,
            leading=34,
            alignment=TA_LEFT,
            textColor=INK,
            spaceAfter=4 * mm,
        ),
        "subtitle": _style(
            "RunplanSubtitle",
            normal,
            regular,
            fontSize=10.5,
            leading=16,
            textColor=MUTED,
            spaceAfter=3 * mm,
        ),
    }


def _week_styles(regular: str, bold: str, base: Any) -> dict[str, ParagraphStyle]:
    """Create the cohesive style family used by week summary headers."""
    normal = base["Normal"]
    return {
        "week_number": _style(
            "RunplanWeekNumber",
            base["Heading1"],
            bold,
            fontSize=21,
            leading=25,
            textColor=INK,
            spaceAfter=1.5 * mm,
        ),
        "week_date": _style(
            "RunplanWeekDate", normal, regular, fontSize=9, leading=12, textColor=MUTED
        ),
        "focus": _style(
            "RunplanFocus",
            normal,
            regular,
            fontSize=9.5,
            leading=14,
            textColor=INK,
            spaceBefore=2 * mm,
        ),
        "stat_value": _style(
            "RunplanStatValue",
            normal,
            bold,
            fontSize=12,
            leading=15,
            alignment=TA_CENTER,
            textColor=GREEN_DARK,
        ),
        "stat_label": _style(
            "RunplanStatLabel",
            normal,
            regular,
            fontSize=7,
            leading=9,
            alignment=TA_CENTER,
            textColor=MUTED,
        ),
    }


def _workout_styles(regular: str, bold: str, base: Any) -> dict[str, ParagraphStyle]:
    """Create the cohesive style family used by workout rows."""
    normal = base["Normal"]
    body = _style(
        "RunplanBody",
        base["BodyText"],
        regular,
        fontSize=8.5,
        leading=12,
        textColor=MUTED,
        spaceAfter=2 * mm,
    )
    return {
        "workout_day": _style(
            "RunplanWorkoutDay",
            normal,
            bold,
            fontSize=8,
            leading=10,
            textColor=GREEN,
            spaceAfter=0.5 * mm,
        ),
        "workout_date": _style(
            "RunplanWorkoutDate", normal, regular, fontSize=7.5, leading=9, textColor=MUTED
        ),
        "workout_total": _style(
            "RunplanWorkoutTotal",
            normal,
            bold,
            fontSize=8,
            leading=11,
            alignment=TA_RIGHT,
            textColor=GREEN_DARK,
        ),
        "workout": _style(
            "RunplanWorkout",
            base["Heading2"],
            bold,
            fontSize=11.5,
            leading=14,
            textColor=INK,
            spaceAfter=1.5 * mm,
        ),
        "body": body,
        "steps": ParagraphStyle(
            "RunplanSteps",
            parent=body,
            fontSize=8,
            leading=11,
            textColor=GREEN_DARK,
            spaceBefore=0.5 * mm,
            spaceAfter=0,
        ),
    }
