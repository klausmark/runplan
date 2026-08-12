"""Coaching context, recommendation types, and the key-workout rule.

Step 5 introduces the pure recommendation engine. This module owns the
input and output value objects; the recommendation logic lives in
:mod:`runplan.application.coaching.recommend` so the rules remain
testable in isolation. The key-workout rule is a small constant set;
the easy-default rule is implemented as a pure function next to the
recommender.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from .recipes import RecipeParameters, WorkoutRecipe
from .workout_form import INTERVAL_WORKOUT, LONG_RUN, TEMPO_RUN, WorkoutForm

KEY_WORKOUT_FORMS: frozenset[WorkoutForm] = frozenset({LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT})
"""Forms that count as a key workout under the key-workout rule.

The rule comes from ``docs/program-prompt.md``: a long run, interval
workout, or tempo run is a key workout and must not be placed next to
another key workout.
"""


@dataclass(frozen=True, slots=True)
class RunnerPace:
    """Runner pace baseline used to fill pace targets on key workouts."""

    five_k_seconds: float

    def __post_init__(self) -> None:
        if self.five_k_seconds <= 0:
            raise ValueError("five_k_seconds must be greater than 0")


@dataclass(frozen=True, slots=True)
class CompletedWorkout:
    """A workout the runner has already finished, used as context for the
    recommender. The form is the workout's category (one of the six
    canonical forms); the recommender treats it as authoritative."""

    date: date
    form: WorkoutForm
    distance_meters: float = 0.0
    duration_seconds: int = 0


class Readiness(Enum):
    """Self-reported readiness the runner brings to a session.

    ``LOW`` suppresses key workouts. ``HIGH`` allows them when other
    gates pass. ``None`` is treated as unknown and never overrides
    the rules.
    """

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"


class WorkoutRequestKind(Enum):
    """What the runner (or the caller) is asking the recommender to do."""

    EASY = "easy"
    RECOVERY = "recovery"
    KEY = "key"
    DEFAULT = "default"


@dataclass(frozen=True, slots=True)
class CoachingContext:
    """Snapshot of the runner's state, passed to ``recommend_workouts``.

    Every field is optional so callers can provide as little or as much
    as they have. The recommender treats absent data as neutral; for
    example, ``readiness=None`` is not the same as ``readiness=LOW``.
    """

    pace: RunnerPace | None = None
    readiness: Readiness | None = None
    request_kind: WorkoutRequestKind = WorkoutRequestKind.DEFAULT
    recent_completed_workouts: tuple[CompletedWorkout, ...] = ()


@dataclass(frozen=True, slots=True)
class RecipeSuggestion:
    """One recipe the runner could pick, paired with parameters ready for
    :class:`WorkoutRecipe.instantiate`. Step 6 takes the recommendation's
    primary suggestion and writes it into a program."""

    recipe_key: str
    parameters: RecipeParameters

    def resolve(self) -> tuple[WorkoutRecipe, RecipeParameters]:
        """Return the catalogue recipe plus the parameters to instantiate."""
        from .recipes import get_recipe

        return get_recipe(self.recipe_key), self.parameters


@dataclass(frozen=True, slots=True)
class WorkoutRecommendation:
    """The result of a recommendation request: a primary suggestion, a
    small set of alternatives in stable order, reasoning strings for
    the UI, and any warnings the runner should see."""

    primary: RecipeSuggestion
    alternatives: tuple[RecipeSuggestion, ...]
    reasoning: tuple[str, ...]
    warnings: tuple[str, ...] = ()


__all__ = [
    "CoachingContext",
    "CompletedWorkout",
    "KEY_WORKOUT_FORMS",
    "Readiness",
    "RecipeSuggestion",
    "RunnerPace",
    "WorkoutRecommendation",
    "WorkoutRequestKind",
]
