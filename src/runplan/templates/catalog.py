"""Load the bundled Nike Run Club training templates."""

from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from typing import Any

import yaml

from ..domain.models import Program
from ..parsing.yaml_loader import load_program_model

PACKAGE = "runplan.templates.programs"
TEMPLATE_FILENAMES: tuple[str, ...] = (
    "nike-5k.yaml",
    "nike-10k.yaml",
    "nike-half-marathon.yaml",
    "nike-marathon.yaml",
)


@dataclass(frozen=True, slots=True)
class TemplateMetadata:
    """Public description of one bundled template."""

    id: str
    name: str
    short_name: str
    description: str | None
    duration_weeks: int
    sessions_per_week: int
    goal_distance_km: float
    distance_label: str
    default_long_run_day: int
    has_race_week: bool
    source: str


def _program_distance(metadata_id: str) -> tuple[float, str]:
    return {
        "nike-5k": (5.0, "5K"),
        "nike-10k": (10.0, "10K"),
        "nike-half-marathon": (21.1, "Half Marathon"),
        "nike-marathon": (42.2, "Marathon"),
    }[metadata_id]


def _load_template_document(filename: str) -> dict[str, Any]:
    package_files = resources.files(PACKAGE)
    text = (package_files / filename).read_text(encoding="utf-8")
    raw = yaml.safe_load(text)
    if not isinstance(raw, dict):
        raise ValueError(f"Template {filename!r} did not load as a YAML object")
    return raw


def _load_template_program(filename: str) -> Program:
    raw = _load_template_document(filename)
    return load_program_model(raw)


def metadata_from(raw: dict[str, Any]) -> TemplateMetadata:
    """Build a TemplateMetadata value from a raw YAML template document."""
    program = load_program_model(raw)
    sessions = {len(week.workouts) for week in program.weeks}
    sessions_per_week = max(sessions) if sessions else 0
    long_run_day = _first_long_run_day(program)
    has_race_week = any(
        workout.id.startswith("race") for week in program.weeks for workout in week.workouts
    )
    goal_distance_km, label = _program_distance(program.id)
    return TemplateMetadata(
        id=program.id,
        name=program.name,
        short_name=program.short_name,
        description=program.description,
        duration_weeks=len(program.weeks),
        sessions_per_week=sessions_per_week,
        goal_distance_km=goal_distance_km,
        distance_label=label,
        default_long_run_day=long_run_day,
        has_race_week=has_race_week,
        source="Nike Run Club",
    )


def _first_long_run_day(program: Program) -> int:
    if not program.weeks:
        return 6
    first_week = program.weeks[0]
    candidates = [w for w in first_week.workouts if w.steps]
    if not candidates:
        return 6
    best = max(candidates, key=_workout_longest_step_meters)
    return best.day


def _workout_longest_step_meters(workout: Any) -> float:
    best = 0.0
    for step in workout.steps:
        best = max(best, _step_meters(step))
    return best


def _step_meters(step: Any) -> float:
    if step.action == "repeat" and step.steps:
        return max((_step_meters(child) for child in step.steps), default=0.0)
    if step.end_kind == "distance" and step.end_value:
        return float(step.end_value)
    return 0.0


def list_templates() -> list[TemplateMetadata]:
    """Return every bundled template, sorted by goal distance ascending."""
    items = [metadata_from(_load_template_document(filename)) for filename in TEMPLATE_FILENAMES]
    items.sort(key=lambda item: item.goal_distance_km)
    return items


def get_template(template_id: str) -> TemplateMetadata:
    """Return one bundled template by id."""
    for item in list_templates():
        if item.id == template_id:
            return item
    available = ", ".join(item.id for item in list_templates())
    raise KeyError(f"Unknown template {template_id!r}; available templates: {available}")


def load_template_document(template_id: str) -> dict[str, Any]:
    """Return the raw YAML dictionary for one bundled template."""
    for filename in TEMPLATE_FILENAMES:
        raw = _load_template_document(filename)
        if raw.get("program", {}).get("id") == template_id:
            return raw
    available = ", ".join(item.id for item in list_templates())
    raise KeyError(f"Unknown template {template_id!r}; available templates: {available}")


def load_template_program(template_id: str) -> Program:
    """Return the typed Program for one bundled template."""
    return load_program_model(load_template_document(template_id))


TEMPLATE_CATALOG: tuple[TemplateMetadata, ...] = tuple(list_templates())
