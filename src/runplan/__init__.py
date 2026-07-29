"""Public Python API for Runplan."""

import logging

from .application.export import ProgramExport, build_program_export
from .application.sync import delete_all_managed, reconcile_program, sync_program_week
from .cli import run_sync
from .domain.errors import WorkoutDefinitionError
from .domain.models import Program, Step, Week, Workout, WorkoutStatus
from .domain.selectors import WeekSelection, WeekSelectionError
from .exporters.html import export_html, format_program_html
from .exporters.markdown import export_markdown, format_program_markdown
from .exporters.pdf import export_pdf
from .integrations.garmin.mapper import build_workout, compile_steps
from .parsing.values import (
    parse_distance,
    parse_duration,
    parse_pace,
    parse_step_end,
)
from .parsing.yaml_loader import (
    load_definition,
    load_definition_model,
    load_program,
    load_program_model,
)
from .presentation.text import (
    estimate_duration,
    estimate_totals,
    format_totals,
    step_summary,
)
from .state.json_repository import load_state, save_state, state_path

logging.getLogger("runplan").addHandler(logging.NullHandler())

__all__ = [
    "WorkoutDefinitionError",
    "Program",
    "ProgramExport",
    "Step",
    "Week",
    "WeekSelection",
    "WeekSelectionError",
    "Workout",
    "WorkoutStatus",
    "build_workout",
    "build_program_export",
    "compile_steps",
    "delete_all_managed",
    "estimate_duration",
    "estimate_totals",
    "export_pdf",
    "export_html",
    "export_markdown",
    "format_program_html",
    "format_program_markdown",
    "format_totals",
    "load_definition",
    "load_definition_model",
    "load_program",
    "load_program_model",
    "load_state",
    "parse_distance",
    "parse_duration",
    "parse_pace",
    "parse_step_end",
    "reconcile_program",
    "save_state",
    "state_path",
    "step_summary",
    "sync_program_week",
    "run_sync",
]
