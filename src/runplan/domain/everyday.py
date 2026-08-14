"""Domain types for the rolling everyday plan.

Step 10 introduces an always-on plan that proposes the next 14 days
based on the runner profile, a broad goal, completed workouts, and
recent load. The types in this module are the slim input and output
value objects the generator and the application use cases exchange.

Step 12 will add a fuller ``domain/preferences.py``; this module is the
minimum Step 10 needs (no ``RunplanUser`` filesystem paths, no Garmin
state).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, get_args

from .recipes import RecipeParameters
from .workout_form import WorkoutForm

EverydayGoal = Literal["maintain", "base", "build", "peak"]
"""Broad goal that tunes how many key workouts appear in the horizon.

``maintain`` keeps at most one key workout per 14 days, ``base`` keeps
zero, ``build`` keeps at most one per 7 days, and ``peak`` keeps at most
two per 14 days. The recommender still chooses the day; the goal only
caps the count.
"""


def _everyday_goal_values() -> tuple[str, ...]:
    return get_args(EverydayGoal)


@dataclass(frozen=True, slots=True)
class EverydayProfile:
    """Slim profile for the everyday horizon.

    Deliberately lighter than :class:`runplan.users.RunplanUser` so the
    generator never touches filesystem paths or credentials. ``training_days``
    is normalised on construction: weekdays must be in 1..7, deduplicated,
    and sorted ascending.
    """

    five_k_seconds: float
    weekly_km_target: float
    training_days: tuple[int, ...]
    preferred_long_run_day: int | None = None

    def __post_init__(self) -> None:
        if self.five_k_seconds < 0:
            raise ValueError("five_k_seconds must be greater than or equal to 0")
        if self.weekly_km_target < 0:
            raise ValueError("weekly_km_target must be greater than or equal to 0")
        if not self.training_days:
            raise ValueError("training_days must contain at least one weekday")
        normalised: list[int] = []
        for day in self.training_days:
            if not 1 <= day <= 7:
                raise ValueError(f"training_days entries must be in 1..7; got {day!r}")
            if day not in normalised:
                normalised.append(day)
        normalised.sort()
        if tuple(normalised) != self.training_days:
            object.__setattr__(self, "training_days", tuple(normalised))
        if self.preferred_long_run_day is not None and not 1 <= self.preferred_long_run_day <= 7:
            raise ValueError(
                f"preferred_long_run_day must be in 1..7; got {self.preferred_long_run_day!r}"
            )

    def has_pace(self) -> bool:
        return self.five_k_seconds > 0


@dataclass(frozen=True, slots=True)
class EverydayRequest:
    """Input for the rolling everyday horizon generator.

    ``history`` carries the completed workouts the recommender reasons
    about. The application use case fills it from the runner's program
    YAML before calling the generator; the generator itself never reads
    the filesystem.
    """

    profile: EverydayProfile
    goal: EverydayGoal
    start_date: date
    horizon_days: int = 14
    history: tuple = ()

    def __post_init__(self) -> None:
        if self.horizon_days <= 0:
            raise ValueError("horizon_days must be greater than 0")
        if self.goal not in _everyday_goal_values():
            raise ValueError(f"goal must be one of {_everyday_goal_values()}; got {self.goal!r}")
        if not isinstance(self.history, tuple):
            raise ValueError("history must be a tuple")


@dataclass(frozen=True, slots=True)
class ProposedDay:
    """One day in the rolling everyday horizon.

    The pairing of ``recipe_key`` and ``parameters`` is the minimum needed
    to instantiate the workout through
    :func:`runplan.application.recipes.instantiate_recipe`. ``reasoning``
    and ``warnings`` are surfaced in the CLI preview and in the future
    Studio UI.
    """

    date: date
    form: WorkoutForm
    recipe_key: str
    parameters: RecipeParameters
    reasoning: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class EverydayHorizon:
    """Output of the rolling everyday horizon generator.

    The horizon is rendered as one extra working week for the CLI preview
    (the seven days starting at ``start_date``); the optional second
    week appears when ``horizon_days`` exceeds seven. ``profile``,
    ``goal``, ``start_date``, and ``horizon_days`` are echoed so the
    acceptance use case can rebuild the request without re-reading the
    program YAML.
    """

    profile: EverydayProfile
    goal: EverydayGoal
    start_date: date
    horizon_days: int
    days: tuple[ProposedDay, ...]

    def as_request(self) -> EverydayRequest:
        """Return an :class:`EverydayRequest` that reproduces this horizon.

        ``history`` is dropped because the rolling horizon is the
        persisted artefact; the next proposal re-reads the runner's
        program to rebuild history.
        """
        return EverydayRequest(
            profile=self.profile,
            goal=self.goal,
            start_date=self.start_date,
            horizon_days=self.horizon_days,
        )


__all__ = [
    "EverydayGoal",
    "EverydayHorizon",
    "EverydayProfile",
    "EverydayRequest",
    "ProposedDay",
]
