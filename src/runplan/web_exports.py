"""Export a validated program document to web-download formats."""

from __future__ import annotations

import logging
import os
import tempfile
from http import HTTPStatus
from pathlib import Path
from typing import Any

from .application.export import build_program_export
from .domain.errors import WorkoutDefinitionError
from .domain.selectors import WeekSelection
from .exporters.markdown import format_program_markdown
from .exporters.pdf import export_pdf
from .parsing.yaml_loader import load_program_model
from .users import (
    DEFAULT_FIVE_K_BEST,
    ENV_FIVE_K_BEST,
    WebError,
    fallback_pace_seconds_per_km,
)

logger = logging.getLogger("runplan.web")


def export_program(
    path: Path,
    raw: dict[str, Any],
    format_name: str,
    *,
    fallback_pace_value: str | None = None,
    pace_zone_seconds_per_km: int | None = None,
) -> tuple[bytes, str, str]:
    """Render one program document in the requested download format."""
    try:
        model = load_program_model(raw)
        five_k_best = fallback_pace_value or os.getenv(ENV_FIVE_K_BEST, DEFAULT_FIVE_K_BEST)
        view = build_program_export(
            model,
            WeekSelection.all(),
            fallback_pace_seconds_per_km=fallback_pace_seconds_per_km(five_k_best),
        )
    except (WorkoutDefinitionError, ValueError) as exc:
        raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _render_export(path, view, format_name)


def _render_export(path: Path, view: Any, format_name: str) -> tuple[bytes, str, str]:
    stem = path.stem
    if format_name == "markdown":
        logger.info("Program exported file=%s format=markdown", path)
        return format_program_markdown(view).encode(), "text/markdown; charset=utf-8", f"{stem}.md"
    if format_name == "yaml":
        logger.info("Program exported file=%s format=yaml", path)
        return path.read_bytes(), "application/yaml; charset=utf-8", path.name
    if format_name == "pdf":
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / f"{stem}.pdf"
            export_pdf(view, output, False)
            logger.info("Program exported file=%s format=pdf", path)
            return output.read_bytes(), "application/pdf", output.name
    raise WebError(HTTPStatus.BAD_REQUEST, "Format must be yaml, markdown, or pdf")
