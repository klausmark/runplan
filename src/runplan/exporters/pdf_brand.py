"""Fonts, logo, and page decoration for Runplan PDFs."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import reportlab
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable

from .pdf_theme import GREEN, LINE, MUTED, PAPER


def draw_runplan_mark(canvas: Any, x: float, y: float, size: float) -> None:
    """Draw the canonical 64-unit Runplan mark on a ReportLab canvas."""
    canvas.saveState()
    canvas.translate(x + size / 2, y + size / 2)
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
        draw_runplan_mark(self.canv, 0, 0, self.width)


def register_pdf_fonts() -> tuple[str, str]:
    """Register ReportLab's bundled Unicode fonts for embedded, portable PDFs."""
    fonts_dir = Path(reportlab.__file__).resolve().parent / "fonts"
    regular_name, bold_name = "RunplanVera", "RunplanVeraBold"
    if regular_name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(regular_name, fonts_dir / "Vera.ttf"))
        pdfmetrics.registerFont(TTFont(bold_name, fonts_dir / "VeraBd.ttf"))
    return regular_name, bold_name


def page_painters(
    regular_font: str, bold_font: str
) -> tuple[Callable[..., None], Callable[..., None]]:
    """Return cover and content decorators bound to the selected fonts."""

    def paint(canvas: Any, doc: Any, *, footer: bool) -> None:
        canvas.saveState()
        canvas.setFillColor(PAPER)
        canvas.rect(0, 0, A4[0], A4[1], fill=1, stroke=0)
        if footer:
            canvas.setStrokeColor(LINE)
            canvas.line(18 * mm, 12 * mm, A4[0] - 18 * mm, 12 * mm)
            draw_runplan_mark(canvas, 18 * mm, 5.3 * mm, 5 * mm)
            canvas.setFillColor(GREEN)
            canvas.setFont(bold_font, 8)
            canvas.drawString(25 * mm, 7.5 * mm, "RUNPLAN")
            canvas.setFillColor(MUTED)
            canvas.setFont(regular_font, 8)
            canvas.drawRightString(A4[0] - 18 * mm, 7.5 * mm, f"Page {doc.page}")
        canvas.restoreState()

    return lambda canvas, doc: paint(canvas, doc, footer=False), lambda canvas, doc: paint(
        canvas, doc, footer=True
    )
