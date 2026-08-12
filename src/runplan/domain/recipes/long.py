"""Long-run recipes.

Every long-run recipe is explicitly labelled :data:`LONG_RUN` because
"long" is relational to the runner and the rest of the week, so the form
cannot be inferred from structure alone.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...generation.workouts import (
    build_long_steady,
    build_long_with_finish,
    build_long_with_hill_surges,
    build_long_with_kickouts,
)
from ...parsing.yaml_models import build_step
from ..models import Step
from ..workout_form import LONG_RUN
from .base import RecipeParameters, WorkoutRecipe, recipe


def _parse_steps(raw: list[dict]) -> tuple[Step, ...]:
    return tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))


def _format_pace(pace: tuple[str, str] | None) -> list[str] | None:
    if pace is None:
        return None
    return list(pace)


@dataclass(frozen=True, slots=True)
class LongSteadyParameters(RecipeParameters):
    target_km: float = 10.0
    pace: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.target_km <= 0:
            raise ValueError("target_km must be greater than 0")
        if self.pace is not None and len(self.pace) != 2:
            raise ValueError("pace must be a pair of min/km strings or None")


@recipe(
    key="long.steady",
    form=LONG_RUN,
    label="Steady long run",
    description=(
        "Continuous long run at a steady aerobic effort. Pair with an "
        "optional effort-based pace range when known."
    ),
    parameters_type=LongSteadyParameters,
)
def _long_steady(params: LongSteadyParameters) -> tuple[Step, ...]:
    return _parse_steps(build_long_steady(params.target_km, _format_pace(params.pace)))


@dataclass(frozen=True, slots=True)
class LongWithFinishParameters(RecipeParameters):
    target_km: float = 12.0
    pace: tuple[str, str] | None = None

    def __post_init__(self) -> None:
        if self.target_km <= 0:
            raise ValueError("target_km must be greater than 0")
        if self.pace is not None and len(self.pace) != 2:
            raise ValueError("pace must be a pair of min/km strings or None")


@recipe(
    key="long.with_finish",
    form=LONG_RUN,
    label="Long run with finish",
    description=(
        "Easy long run followed by a moderate-paced finish segment. "
        "Useful for race-specific strength late in the plan."
    ),
    parameters_type=LongWithFinishParameters,
)
def _long_with_finish(params: LongWithFinishParameters) -> tuple[Step, ...]:
    finish_km = max(1.5, round(params.target_km * 0.20, 1))
    easy_km = max(2.0, round(params.target_km - finish_km, 1))
    return _parse_steps(build_long_with_finish(easy_km, finish_km, _format_pace(params.pace)))


@dataclass(frozen=True, slots=True)
class LongWithHillSurgesParameters(RecipeParameters):
    target_km: float = 10.0
    surge_count: int = 6

    def __post_init__(self) -> None:
        if self.target_km <= 0:
            raise ValueError("target_km must be greater than 0")
        if self.surge_count <= 0:
            raise ValueError("surge_count must be greater than 0")


@recipe(
    key="long.with_hill_surges",
    form=LONG_RUN,
    label="Long run with hill surges",
    description=(
        "Easy long run with short hill surges inserted throughout. The "
        "count scales with the target distance."
    ),
    parameters_type=LongWithHillSurgesParameters,
)
def _long_with_hill_surges(params: LongWithHillSurgesParameters) -> tuple[Step, ...]:
    surge_count = params.surge_count
    if surge_count <= 0:
        surge_count = 6 if params.target_km >= 8 else 4
    return _parse_steps(build_long_with_hill_surges(params.target_km, surge_count))


@dataclass(frozen=True, slots=True)
class LongWithKickoutsParameters(RecipeParameters):
    target_km: float = 10.0
    kick_count: int = 4
    kick_minutes: int = 2

    def __post_init__(self) -> None:
        if self.target_km <= 0:
            raise ValueError("target_km must be greater than 0")
        if self.kick_count <= 0:
            raise ValueError("kick_count must be greater than 0")
        if self.kick_minutes <= 0:
            raise ValueError("kick_minutes must be greater than 0")


@recipe(
    key="long.with_kickouts",
    form=LONG_RUN,
    label="Long run with kickouts",
    description=(
        "Easy long run with steady kickouts embedded to develop late-run "
        "strength without breaking the aerobic intent."
    ),
    parameters_type=LongWithKickoutsParameters,
)
def _long_with_kickouts(params: LongWithKickoutsParameters) -> tuple[Step, ...]:
    kick_count = params.kick_count
    kick_minutes = params.kick_minutes
    if kick_count <= 0:
        kick_count = 4 if params.target_km >= 8 else 3
    if kick_minutes <= 0:
        kick_minutes = 2 if params.target_km >= 8 else 1
    return _parse_steps(build_long_with_kickouts(params.target_km, kick_count, kick_minutes))


LONG_RECIPES: tuple[WorkoutRecipe, ...] = (
    _long_steady,
    _long_with_finish,
    _long_with_hill_surges,
    _long_with_kickouts,
)


__all__ = [
    "LONG_RECIPES",
    "LongSteadyParameters",
    "LongWithFinishParameters",
    "LongWithHillSurgesParameters",
    "LongWithKickoutsParameters",
]
