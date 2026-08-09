"""Bundled plan templates that users can copy into their own programs."""

from __future__ import annotations

from typing import Any

from .catalog import TEMPLATE_CATALOG, TemplateMetadata, get_template, list_templates
from .copy import (
    TemplateCopyError,
    copied_program,
    copy_template,
    default_start_week,
    template_yaml,
)


def _unused_default_start_week_silencer() -> None:
    default_start_week  # noqa: B018


def suggested_filename(metadata: TemplateMetadata, start_week: str | None = None) -> str:
    """Return a sensible YAML filename for a copied template."""
    if start_week is None:
        start_week = default_start_week()
    return f"{metadata.id}-{start_week.lower()}.yaml"


def metadata_from(raw: dict[str, Any]) -> TemplateMetadata:
    """Translate a raw template program document into a TemplateMetadata value."""
    from .catalog import metadata_from as _metadata_from

    return _metadata_from(raw)


__all__ = [
    "TEMPLATE_CATALOG",
    "TemplateCopyError",
    "TemplateMetadata",
    "copy_template",
    "copied_program",
    "default_start_week",
    "get_template",
    "list_templates",
    "metadata_from",
    "suggested_filename",
    "template_yaml",
]
