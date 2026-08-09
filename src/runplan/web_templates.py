"""HTTP endpoints for browsing and copying bundled plan templates."""

from __future__ import annotations

import logging
from typing import Any

import yaml

from .domain.errors import WorkoutDefinitionError
from .templates import (
    TemplateCopyError,
    copy_template,
    get_template,
    list_templates,
    suggested_filename,
    template_yaml,
)

logger = logging.getLogger("runplan.web")


def list_templates_response() -> dict[str, Any]:
    """Return the public JSON catalog payload."""
    return {
        "templates": [_metadata_payload(item) for item in list_templates()],
    }


def get_template_response(template_id: str) -> dict[str, Any]:
    """Return a single template's metadata, suggested filename and coaching summary."""
    metadata = get_template(template_id)
    response: dict[str, Any] = {
        "template": _metadata_payload(metadata),
        "suggestedFilename": suggested_filename(metadata),
    }
    response["hasCoaching"] = _template_has_coaching(template_id)
    return response


def copy_template_response(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a YAML document for a copied template, ready to upload."""
    if not isinstance(payload, dict):
        raise ValueError("Template copy payload must be a JSON object")
    start_week_raw = payload.get("start_week")
    if start_week_raw is not None and not isinstance(start_week_raw, str):
        raise ValueError("start_week must be a string in YYYY-Www format")
    start_week = start_week_raw.strip() if isinstance(start_week_raw, str) else None
    try:
        body = template_yaml(template_id, start_week=start_week or None)
    except TemplateCopyError as exc:
        raise ValueError(str(exc)) from exc
    except WorkoutDefinitionError as exc:
        raise ValueError(str(exc)) from exc
    try:
        metadata = get_template(template_id)
        filename = suggested_filename(metadata, start_week=start_week)
    except KeyError:
        filename = f"{template_id}.yaml"
    return {
        "templateId": template_id,
        "filename": filename,
        "content": body,
    }


def copy_template_dict_response(template_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Return a parsed dictionary form for the copied template."""
    if not isinstance(payload, dict):
        raise ValueError("Template copy payload must be a JSON object")
    start_week_raw = payload.get("start_week")
    if start_week_raw is not None and not isinstance(start_week_raw, str):
        raise ValueError("start_week must be a string in YYYY-Www format")
    start_week = start_week_raw.strip() if isinstance(start_week_raw, str) else None
    try:
        copy = copy_template(template_id, start_week=start_week or None)
    except TemplateCopyError as exc:
        raise ValueError(str(exc)) from exc
    return {
        "templateId": template_id,
        "program": copy["program"],
    }


def parse_template_yaml(text: str) -> dict[str, Any]:
    """Parse a YAML document and raise ValueError on invalid structure."""
    try:
        loaded = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {exc}") from exc
    if not isinstance(loaded, dict):
        raise ValueError("Template YAML must contain a program document")
    return loaded


def _template_has_coaching(template_id: str) -> bool:
    from .parsing.yaml_loader import load_program_model
    from .templates.catalog import load_template_document

    raw = load_template_document(template_id)
    return load_program_model(raw).coaching is not None


def _metadata_payload(item: Any) -> dict[str, Any]:
    return {
        "id": item.id,
        "name": item.name,
        "shortName": item.short_name,
        "description": item.description,
        "durationWeeks": item.duration_weeks,
        "sessionsPerWeek": item.sessions_per_week,
        "goalDistanceKm": item.goal_distance_km,
        "distanceLabel": item.distance_label,
        "defaultLongRunDay": item.default_long_run_day,
        "hasRaceWeek": item.has_race_week,
        "source": item.source,
    }


__all__ = [
    "copy_template_dict_response",
    "copy_template_response",
    "get_template_response",
    "list_templates_response",
    "parse_template_yaml",
]
