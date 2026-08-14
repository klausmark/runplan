"""Interval-workout recipes.

These recipes carry the :data:`INTERVAL_WORKOUT` form: repeated faster
work with structured recoveries. Each recipe declares its pace range so
the runner can supply their own interval pace before syncing.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...generation.workouts import (
    build_fartlek,
    build_hill_repeats,
    build_track_1k,
    build_track_400m,
)
from ...parsing.yaml_models import build_step
from ..models import Step
from ..workout_form import INTERVAL_WORKOUT
from .base import RecipeParameters, WorkoutRecipe, recipe


def _parse_steps(raw: list[dict]) -> tuple[Step, ...]:
    return tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))


def _format_pace(pace: tuple[str, str] | None) -> list[str] | None:
    if pace is None:
        return None
    return list(pace)


@dataclass(frozen=True, slots=True)
class Track400mParameters(RecipeParameters):
    reps: int = 6
    pace: tuple[str, str] | None = ("4:30", "4:30")

    def __post_init__(self) -> None:
        if self.reps <= 0:
            raise ValueError("reps must be greater than 0")
        if self.pace is not None and len(self.pace) != 2:
            raise ValueError("pace must be a pair of min/km strings or None")


@recipe(
    key="interval.track_400m",
    form=INTERVAL_WORKOUT,
    label="400m repeats",
    description=(
        "Short 400m repeats at fast pace with jog recoveries. Builds "
        "top-end speed and leg turnover."
    ),
    parameters_type=Track400mParameters,
)
def _track_400m(params: Track400mParameters) -> tuple[Step, ...]:
    return _parse_steps(build_track_400m(params.reps, _format_pace(params.pace)))


@dataclass(frozen=True, slots=True)
class Track1kParameters(RecipeParameters):
    reps: int = 5
    pace: tuple[str, str] | None = ("4:45", "4:45")

    def __post_init__(self) -> None:
        if self.reps <= 0:
            raise ValueError("reps must be greater than 0")
        if self.pace is not None and len(self.pace) != 2:
            raise ValueError("pace must be a pair of min/km strings or None")


@recipe(
    key="interval.track_1k",
    form=INTERVAL_WORKOUT,
    label="1km repeats",
    description=(
        "Steady 1km repeats at threshold pace with jog recoveries. "
        "Foundational session for sustained faster efforts."
    ),
    parameters_type=Track1kParameters,
)
def _track_1k(params: Track1kParameters) -> tuple[Step, ...]:
    return _parse_steps(build_track_1k(params.reps, _format_pace(params.pace)))


@dataclass(frozen=True, slots=True)
class HillRepeatsParameters(RecipeParameters):
    reps: int = 6
    effort_seconds: int = 60

    def __post_init__(self) -> None:
        if self.reps <= 0:
            raise ValueError("reps must be greater than 0")
        if self.effort_seconds <= 0:
            raise ValueError("effort_seconds must be greater than 0")


@recipe(
    key="interval.hill_repeats",
    form=INTERVAL_WORKOUT,
    label="Hill repeats",
    description=(
        "Short hill efforts with jog-down recovery. Builds strength and "
        "running form without requiring a track."
    ),
    parameters_type=HillRepeatsParameters,
)
def _hill_repeats(params: HillRepeatsParameters) -> tuple[Step, ...]:
    return _parse_steps(build_hill_repeats(params.reps, params.effort_seconds))


@dataclass(frozen=True, slots=True)
class FartlekParameters(RecipeParameters):
    cycles: int = 6
    hard_minutes: int = 2
    easy_minutes: int = 1

    def __post_init__(self) -> None:
        if self.cycles <= 0:
            raise ValueError("cycles must be greater than 0")
        if self.hard_minutes <= 0:
            raise ValueError("hard_minutes must be greater than 0")
        if self.easy_minutes <= 0:
            raise ValueError("easy_minutes must be greater than 0")


@recipe(
    key="interval.fartlek",
    form=INTERVAL_WORKOUT,
    label="Fartlek",
    description=(
        "Alternating hard and easy running cycles. Lighter than track "
        "intervals and easy to scale by terrain."
    ),
    parameters_type=FartlekParameters,
)
def _fartlek(params: FartlekParameters) -> tuple[Step, ...]:
    return _parse_steps(build_fartlek(params.cycles, params.hard_minutes, params.easy_minutes))


INTERVAL_RECIPES: tuple[WorkoutRecipe, ...] = (
    _track_400m,
    _track_1k,
    _hill_repeats,
    _fartlek,
)


__all__ = [
    "FartlekParameters",
    "HillRepeatsParameters",
    "INTERVAL_RECIPES",
    "Track1kParameters",
    "Track400mParameters",
]
