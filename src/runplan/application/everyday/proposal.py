"""Propose a rolling everyday horizon from a stored program.

The use case is the application-layer wrapper around the pure
:func:`runplan.generation.everyday.propose_everyday_horizon` generator.
It loads the runner's program through the injected repository, builds
the completed-workout history that the generator reasons about, and
returns the resulting horizon.

The use case never writes to the repository. Acceptance is a separate
use case (:func:`accept_horizon`) with its own persistence semantics.
"""

from __future__ import annotations

from datetime import date

from ...domain.everyday import EverydayHorizon, EverydayProfile, EverydayRequest
from ...generation.everyday import propose_everyday_horizon
from ..coaching.context import completed_workouts_from_program
from ..ports import ProgramRepository
from .errors import UNKNOWN_PROGRAM, EverydayError
from .horizon_io import horizon_to_payload

__all__ = ["horizon_to_payload", "propose_horizon"]


def propose_horizon(
    *,
    program_id: str,
    profile: EverydayProfile,
    goal: str,
    start_date: date,
    horizon_days: int = 14,
    repository: ProgramRepository,
    today: date | None = None,
) -> EverydayHorizon:
    """Return the proposed :class:`EverydayHorizon` for ``program_id``.

    The runner's completed workouts are read from the program YAML and
    passed to the generator as the history. ``today`` is forwarded for
    symmetry with other use cases; the generator itself does not read
    the clock.
    """
    try:
        raw = repository.load(program_id)
    except KeyError as exc:
        raise EverydayError(
            UNKNOWN_PROGRAM,
            f"program {program_id!r} does not exist",
        ) from exc
    history = completed_workouts_from_program(raw)
    request = EverydayRequest(
        profile=profile,
        goal=goal,
        start_date=start_date,
        horizon_days=horizon_days,
        history=history,
    )
    return propose_everyday_horizon(request, today=today)
