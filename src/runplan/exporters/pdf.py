"""PDF export facade."""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate

from ..application.export import ProgramExport
from .pdf_brand import draw_runplan_mark, page_painters, register_pdf_fonts
from .pdf_story import build_pdf_story
from .pdf_styles import build_pdf_styles

_draw_runplan_mark = draw_runplan_mark


def export_pdf(program: ProgramExport, output_path: Path, force: bool) -> None:
    """Export the complete validated program using the web UI's visual identity."""
    output_path = _validated_output_path(output_path, force)
    regular_font, bold_font = register_pdf_fonts()
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
    styles = build_pdf_styles(regular_font, bold_font)
    story = build_pdf_story(program, A4[0] - document.leftMargin - document.rightMargin, styles)
    cover_page, content_page = page_painters(regular_font, bold_font)
    document.build(story, onFirstPage=cover_page, onLaterPages=content_page)


def _validated_output_path(output_path: Path, force: bool) -> Path:
    result = output_path.expanduser().resolve()
    if result.exists() and not force:
        raise FileExistsError(f"Output file already exists: {result}\nUse --force to overwrite it.")
    if not result.parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {result.parent}")
    return result


__all__ = ["export_pdf", "register_pdf_fonts"]
