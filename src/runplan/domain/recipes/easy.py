"""Easy-workout recipes.

These cover the most frequent prescriptions: a steady aerobic run, easy
runs with strides, a recovery jog, a run/walk pattern, and a minimal
warmup-only session. Everyone of them carries the :data:`EASY_RUN` form,
except the recovery run (:data:`RECOVERY_RUN`) and the run/walk
(:data:`RUN_WALK`).
"""

from __future__ import annotations

from dataclasses import dataclass

from ...generation.workouts import (
    build_easy_continuous,
    build_easy_with_strides,
    build_recovery_run,
    build_warmup_run,
)
from ...parsing.yaml_models import build_step
from ..models import Step
from ..workout_form import EASY_RUN, RECOVERY_RUN, RUN_WALK
from .base import RecipeParameters, WorkoutRecipe, recipe


def _parse_steps(raw: list[dict]) -> tuple[Step, ...]:
    return tuple(build_step(item, f"steps[{index}]") for index, item in enumerate(raw, start=1))


def _build_run_walk_intervals(
    *,
    run_minutes: int,
    walk_minutes: int,
    cycles: int,
) -> tuple[Step, ...]:
    """Return run/walk intervals suitable for first-mile run/walk starts."""
    return _parse_steps(
        [
            {"warmup": f"{max(5, run_minutes)}m"},
            {
                "repeat": {
                    "count": cycles,
                    "steps": [
                        {"run": {"time": f"{run_minutes}m"}},
                        {"walk": {"time": f"{walk_minutes}m"}},
                    ],
                }
            },
            {"cooldown": "5m"},
        ]
    )


# ---------------------------------------------------------------------------
# Easy continuous
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EasyContinuousParameters(RecipeParameters):
    minutes: int = 30

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be greater than 0")


@recipe(
    key="easy.continuous",
    form=EASY_RUN,
    label="Easy continuous run",
    description=(
        "Steady aerobic effort for the prescribed time. Warm up and cool down frame the main run."
    ),
    parameters_type=EasyContinuousParameters,
)
def _easy_continuous(params: EasyContinuousParameters) -> tuple[Step, ...]:
    return _parse_steps(build_easy_continuous(params.minutes))


# ---------------------------------------------------------------------------
# Easy with strides
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class EasyWithStridesParameters(RecipeParameters):
    minutes: int = 30

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be greater than 0")


@recipe(
    key="easy.with_strides",
    form=EASY_RUN,
    label="Easy run with strides",
    description=(
        "Steady aerobic run followed by four short strides to keep the neuromuscular system sharp."
    ),
    parameters_type=EasyWithStridesParameters,
)
def _easy_with_strides(params: EasyWithStridesParameters) -> tuple[Step, ...]:
    return _parse_steps(build_easy_with_strides(params.minutes))


# ---------------------------------------------------------------------------
# Recovery run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RecoveryRunParameters(RecipeParameters):
    minutes: int = 20

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be greater than 0")


@recipe(
    key="recovery.run",
    form=RECOVERY_RUN,
    label="Recovery run",
    description=(
        "Very short, very easy jog to keep the legs moving without adding training stress."
    ),
    parameters_type=RecoveryRunParameters,
)
def _recovery_run(params: RecoveryRunParameters) -> tuple[Step, ...]:
    return _parse_steps(build_recovery_run(params.minutes))


# ---------------------------------------------------------------------------
# Run/walk intervals
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class RunWalkIntervalsParameters(RecipeParameters):
    run_minutes: int = 1
    walk_minutes: int = 2
    cycles: int = 6

    def __post_init__(self) -> None:
        if self.run_minutes <= 0:
            raise ValueError("run_minutes must be greater than 0")
        if self.walk_minutes <= 0:
            raise ValueError("walk_minutes must be greater than 0")
        if self.cycles <= 0:
            raise ValueError("cycles must be greater than 0")


@recipe(
    key="run_walk.intervals",
    form=RUN_WALK,
    label="Run/walk intervals",
    description=(
        "Alternate short running efforts with planned walking breaks. "
        "Useful for new runners returning to running or for return-to-run "
        "weeks after a break."
    ),
    parameters_type=RunWalkIntervalsParameters,
)
def _run_walk_intervals(params: RunWalkIntervalsParameters) -> tuple[Step, ...]:
    return _build_run_walk_intervals(
        run_minutes=params.run_minutes,
        walk_minutes=params.walk_minutes,
        cycles=params.cycles,
    )


# ---------------------------------------------------------------------------
# Warmup + run
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WarmupRunParameters(RecipeParameters):
    minutes: int = 20

    def __post_init__(self) -> None:
        if self.minutes <= 0:
            raise ValueError("minutes must be greater than 0")


@recipe(
    key="easy.warmup_run",
    form=EASY_RUN,
    label="Warmup — short run",
    description=(
        "Default warmup and cooldown around a short run for very short or unstructured sessions."
    ),
    parameters_type=WarmupRunParameters,
)
def _warmup_run(params: WarmupRunParameters) -> tuple[Step, ...]:
    return _parse_steps(build_warmup_run(params.minutes))


EASY_RECIPES: tuple[WorkoutRecipe, ...] = (
    _easy_continuous,
    _easy_with_strides,
    _recovery_run,
    _run_walk_intervals,
    _warmup_run,
)


__all__ = [
    "EASY_RECIPES",
    "EasyContinuousParameters",
    "EasyWithStridesParameters",
    "RecoveryRunParameters",
    "RunWalkIntervalsParameters",
    "WarmupRunParameters",
]
