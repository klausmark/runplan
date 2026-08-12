"""Tempo-style recipes.

These recipes carry the :data:`TEMPO_RUN` form. The paces are expressed
in min/km strings to match the existing pace input format.
"""

from __future__ import annotations

from dataclasses import dataclass

from ...generation.workouts import build_continuous_tempo, build_cruise_intervals
from ...parsing.yaml_models import build_step
from ..models import Step
from ..workout_form import TEMPO_RUN
from .base import RecipeParameters, WorkoutRecipe, recipe


def _parse_steps(raw: list[dict]) -> tuple[Step, ...]:
    return tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))


def _format_pace(pace: tuple[str, str]) -> list[str]:
    return list(pace)


@dataclass(frozen=True, slots=True)
class ContinuousTempoParameters(RecipeParameters):
    minutes: int = 20
    pace: tuple[str, str] = ("5:00", "5:00")

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be greater than 0")
        if len(self.pace) != 2:
            raise ValueError("pace must be a pair of min/km strings")


@recipe(
    key="tempo.continuous",
    form=TEMPO_RUN,
    label="Continuous tempo",
    description=(
        "Sustained controlled effort at tempo pace. Tempo work sits "
        "between the easy aerobic zone and the faster interval work."
    ),
    parameters_type=ContinuousTempoParameters,
)
def _continuous_tempo(params: ContinuousTempoParameters) -> tuple[Step, ...]:
    return _parse_steps(build_continuous_tempo(params.minutes, _format_pace(params.pace)))


@dataclass(frozen=True, slots=True)
class CruiseIntervalsParameters(RecipeParameters):
    reps: int = 4
    rep_minutes: int = 5
    pace: tuple[str, str] = ("5:00", "5:00")

    def __post_init__(self) -> None:
        if self.reps <= 0:
            raise ValueError("reps must be greater than 0")
        if self.rep_minutes <= 0:
            raise ValueError("rep_minutes must be greater than 0")
        if len(self.pace) != 2:
            raise ValueError("pace must be a pair of min/km strings")


@recipe(
    key="tempo.cruise_intervals",
    form=TEMPO_RUN,
    label="Cruise intervals",
    description=(
        "Repeated tempo-pace efforts with short jog recoveries. Useful "
        "for building sustained tempo-pace volume."
    ),
    parameters_type=CruiseIntervalsParameters,
)
def _cruise_intervals(params: CruiseIntervalsParameters) -> tuple[Step, ...]:
    return _parse_steps(
        build_cruise_intervals(params.reps, params.rep_minutes, _format_pace(params.pace))
    )


TEMPO_RECIPES: tuple[WorkoutRecipe, ...] = (
    _continuous_tempo,
    _cruise_intervals,
)


__all__ = [
    "ContinuousTempoParameters",
    "CruiseIntervalsParameters",
    "TEMPO_RECIPES",
]
