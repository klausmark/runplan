"""Phase boundaries for the first 10K generator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import GenerationError


class PhaseKind(Enum):
    """The four adaptation phases of a 10K program."""

    FOUNDATION = "foundation"
    BUILD = "build"
    PEAK = "peak"
    TAPER = "taper"


@dataclass(frozen=True, slots=True)
class Phase:
    """A single labelled phase covering one or more weeks.

    The phase covers weeks 1-indexed from program start. A program with
    Multiple phases partitions ``1..duration_weeks`` without gaps or overlaps.
    """

    kind: PhaseKind
    start_week: int
    end_week: int

    @property
    def length(self) -> int:
        return self.end_week - self.start_week + 1

    def contains(self, week: int) -> bool:
        return self.start_week <= week <= self.end_week


def phase_split(duration_weeks: int) -> tuple[int, int, int, int]:
    """Return the (foundation, build, peak, taper) week counts for a program.

    The taper is at least one week and never more than three. The three
    non-taper phases split 40%/30%/15% of the remaining weeks, rounded
    towards the long phases so the program leans on aerobic development.
    """
    if not 8 <= duration_weeks <= 16:
        raise GenerationError(f"duration_weeks must be 8-16, got {duration_weeks}")
    if duration_weeks <= 9:
        taper = 1
    elif duration_weeks <= 12:
        taper = 2
    else:
        taper = 2
    body = duration_weeks - taper
    foundation = max(2, round(body * 0.40))
    remaining = body - foundation
    build = max(2, round(remaining * (2 / 3)))
    peak = max(1, body - foundation - build)
    return foundation, build, peak, taper


def phase_plan(duration_weeks: int) -> tuple[Phase, ...]:
    """Return the ordered phases for a program of ``duration_weeks`` weeks."""
    foundation, build, peak, taper = phase_split(duration_weeks)
    cursor = 1
    plans: list[Phase] = []
    for kind, length in (
        (PhaseKind.FOUNDATION, foundation),
        (PhaseKind.BUILD, build),
        (PhaseKind.PEAK, peak),
        (PhaseKind.TAPER, taper),
    ):
        plans.append(Phase(kind, cursor, cursor + length - 1))
        cursor += length
    return tuple(plans)


def phase_for(plan: tuple[Phase, ...], week: int) -> Phase:
    """Return the phase that owns ``week`` (1-indexed)."""
    for phase in plan:
        if phase.contains(week):
            return phase
    raise GenerationError(f"week {week} is not covered by the phase plan")


__all__ = ["Phase", "PhaseKind", "phase_for", "phase_plan", "phase_split"]
