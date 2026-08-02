"""Deterministic first 10K running program generator.

The generator turns a typed request into a validated Runplan program without
consulting an external model. The coaching rules are encoded in pure
functions and reference the peer-reviewed sources collected in
``docs/generation-first-10k-evidence.md``.
"""

from .errors import GenerationError, GenerationWarning
from .inputs import (
    BRace,
    ClubSession,
    ClubSessionType,
    GeneratorRequest,
    GoalRace,
    ProgressionProfile,
    TrainingDays,
    as_dict,
    race_date_window,
    suggest_start_week,
)
from .plan import compose_program
from .serialize import (
    GeneratorResult,
    plan_to_yaml,
    suggested_filename,
    validate_yaml,
)

__all__ = [
    "BRace",
    "ClubSession",
    "ClubSessionType",
    "GenerationError",
    "GenerationWarning",
    "GeneratorRequest",
    "GeneratorResult",
    "GoalRace",
    "ProgressionProfile",
    "TrainingDays",
    "as_dict",
    "compose_program",
    "plan_to_yaml",
    "race_date_window",
    "suggest_start_week",
    "suggested_filename",
    "validate_yaml",
]
