"""Copy a bundled template into a per-user program with a chosen start week."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

import yaml

from ..domain.errors import WorkoutDefinitionError
from ..parsing.yaml_loader import load_program_model, parse_iso_week
from .catalog import list_templates, load_template_document


class TemplateCopyError(ValueError):
    """Raised when a template cannot be copied with the requested settings."""


def _next_monday(today: date) -> date:
    iso = today.isocalendar()
    monday = date.fromisocalendar(iso[0], iso[1], 1)
    if monday < today:
        monday = monday + timedelta(days=7)
    return monday


def default_start_week(today: date | None = None) -> str:
    """Return the ISO week label of the next Monday from `today`."""
    if today is None:
        today = date.today()
    monday = _next_monday(today)
    iso = monday.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def _copy_document(
    raw: dict[str, Any],
    *,
    template_id: str,
    start_week: str,
) -> dict[str, Any]:
    label, _monday = parse_iso_week(start_week, "start_week")
    program = dict(raw["program"])
    program["id"] = f"{template_id}-{label.lower()}"
    program["start_week"] = label
    return {"program": program, "weeks": list(raw["weeks"])}


def copy_template(
    template_id: str,
    *,
    start_week: str | None = None,
    today: date | None = None,
) -> dict[str, Any]:
    """Return a new program document derived from a bundled template."""
    available_ids = {item.id for item in list_templates()}
    if template_id not in available_ids:
        available = ", ".join(sorted(available_ids))
        raise TemplateCopyError(
            f"Unknown template {template_id!r}; available templates: {available}"
        )
    if start_week is None:
        start_week = default_start_week(today)
    raw = load_template_document(template_id)
    try:
        copy = _copy_document(raw, template_id=template_id, start_week=start_week)
    except WorkoutDefinitionError as exc:
        raise TemplateCopyError(str(exc)) from exc
    return copy


def template_yaml(
    template_id: str,
    *,
    start_week: str | None = None,
    today: date | None = None,
) -> str:
    """Return a YAML document string for a copied template, ready to upload."""
    copy = copy_template(template_id, start_week=start_week, today=today)
    return yaml.safe_dump(copy, sort_keys=False, allow_unicode=True)


def copied_program(
    template_id: str,
    *,
    start_week: str | None = None,
    today: date | None = None,
):
    """Return a typed `Program` for the copied template, validated by the loader."""
    copy = copy_template(template_id, start_week=start_week, today=today)
    return load_program_model(copy)


__all__ = [
    "TemplateCopyError",
    "copy_template",
    "copied_program",
    "default_start_week",
    "template_yaml",
]
