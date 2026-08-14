"""Rolling everyday plan use cases (Step 10).

This module group connects the rolling everyday horizon generator to
program editing. ``propose_horizon`` loads the runner's program, builds
the completed-workout history, and returns the proposed next 14 days.
``accept_horizon`` writes the proposed days into the program YAML,
inserting new weeks as needed and revalidating the complete program.

The use cases are web-agnostic: callers inject a
:class:`~runplan.application.ports.ProgramRepository` so the CLI and
the future Studio share the same persistence and validation rules.
"""

from __future__ import annotations

from .acceptance import AcceptedDay, AcceptedHorizon, accept_horizon
from .errors import (
    DAY_CONFLICT,
    DUPLICATE_WORKOUT_ID,
    INVALID_REQUEST,
    KEY_RULE_VIOLATION,
    PERSISTENCE_FAILED,
    UNKNOWN_PROGRAM,
    EverydayError,
)
from .horizon_io import horizon_from_payload, horizon_to_payload
from .proposal import propose_horizon

__all__ = [
    "AcceptedDay",
    "AcceptedHorizon",
    "DAY_CONFLICT",
    "DUPLICATE_WORKOUT_ID",
    "EverydayError",
    "INVALID_REQUEST",
    "KEY_RULE_VIOLATION",
    "PERSISTENCE_FAILED",
    "UNKNOWN_PROGRAM",
    "accept_horizon",
    "horizon_from_payload",
    "horizon_to_payload",
    "propose_horizon",
]
