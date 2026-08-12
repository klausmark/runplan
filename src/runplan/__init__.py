"""Public Python API for Runplan."""

import logging

from .application.export import ProgramExport, build_program_export
from .application.sync import delete_all_managed, reconcile_program, sync_program_week
from .cli import run_sync
from .domain.errors import WorkoutDefinitionError
from .domain.models import (
    CoachingGuide,
    CoachingSection,
    CoachingTip,
    GlossaryEntry,
    PaceChart,
    PaceColumn,
    PaceExample,
    PaceType,
    Program,
    Step,
    Week,
    Workout,
    WorkoutStatus,
)
from .domain.selectors import WeekSelection, WeekSelectionError
from .domain.workout_form import (
    EASY_RUN,
    FORM_BY_NAME,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    RUN_WALK,
    TEMPO_RUN,
    WorkoutForm,
    WorkoutFormName,
    WorkoutWithForm,
    infer_workout_form,
)
from .exporters.html import export_html, format_program_html
from .exporters.markdown import export_markdown, format_program_markdown
from .exporters.pdf import export_pdf
from .generation import (
    BRace,
    GeneratorRequest,
    GoalRace,
    TrainingDays,
    compose_program,
    plan_to_yaml,
    suggested_filename,
)
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
from .templates import (
    TEMPLATE_CATALOG,
    TemplateCopyError,
    TemplateMetadata,
    copy_template,
    default_start_week,
    get_template,
    list_templates,
    template_yaml,
)

logging.getLogger("runplan").addHandler(logging.NullHandler())

__all__ = [
    "BRace",
    "CoachingGuide",
    "CoachingSection",
    "CoachingTip",
    "EASY_RUN",
    "FORM_BY_NAME",
    "GeneratorRequest",
    "GlossaryEntry",
    "GoalRace",
    "INTERVAL_WORKOUT",
    "LONG_RUN",
    "PaceChart",
    "PaceColumn",
    "PaceExample",
    "PaceType",
    "Program",
    "ProgramExport",
    "RECOVERY_RUN",
    "RUN_WALK",
    "Step",
    "TEMPLATE_CATALOG",
    "TEMPO_RUN",
    "TemplateCopyError",
    "TemplateMetadata",
    "TrainingDays",
    "Week",
    "WeekSelection",
    "WeekSelectionError",
    "Workout",
    "WorkoutDefinitionError",
    "WorkoutForm",
    "WorkoutFormName",
    "WorkoutStatus",
    "WorkoutWithForm",
    "build_workout",
    "build_program_export",
    "compile_steps",
    "compose_program",
    "copy_template",
    "default_start_week",
    "delete_all_managed",
    "estimate_duration",
    "estimate_totals",
    "export_pdf",
    "export_html",
    "export_markdown",
    "format_program_html",
    "format_program_markdown",
    "format_totals",
    "get_template",
    "infer_workout_form",
    "list_templates",
    "load_definition",
    "load_definition_model",
    "load_program",
    "load_program_model",
    "load_state",
    "parse_distance",
    "parse_duration",
    "parse_pace",
    "parse_step_end",
    "plan_to_yaml",
    "reconcile_program",
    "run_sync",
    "save_state",
    "state_path",
    "step_summary",
    "suggested_filename",
    "sync_program_week",
    "template_yaml",
]
