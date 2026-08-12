"""Workout forms: the authoring taxonomy used for UI labels and export headings.

Forms are authoring concepts. They never enter program YAML. A recipe
instantiates a workout and pairs it with a form via :class:`WorkoutWithForm`;
the parser infers a form from a workout's step structure when no recipe is
involved.

Long runs are not inferred structurally: "long" is relational to the runner
and the rest of the week, so an ad-hoc single-run workout defaults to
:data:`EASY_RUN` and must be assigned :data:`LONG_RUN` explicitly.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .models import Step, Workout

WorkoutFormName = Literal[
    "easy_run",
    "run_walk",
    "recovery_run",
    "long_run",
    "tempo_run",
    "interval_workout",
]

_CANONICAL_LABELS: dict[str, str] = {
    "easy_run": "Easy run",
    "run_walk": "Run/walk",
    "recovery_run": "Recovery run",
    "long_run": "Long run",
    "tempo_run": "Tempo run",
    "interval_workout": "Interval workout",
}


@dataclass(frozen=True, slots=True)
class WorkoutForm:
    """One of the six canonical workout forms used for UI and export labels."""

    name: WorkoutFormName
    label: str

    def __post_init__(self) -> None:
        expected = _CANONICAL_LABELS.get(self.name)
        if expected is None:
            raise ValueError(f"unknown workout form {self.name!r}")
        if self.label != expected:
            raise ValueError(f"workout form {self.name!r} requires label {expected!r}")


EASY_RUN = WorkoutForm("easy_run", "Easy run")
RUN_WALK = WorkoutForm("run_walk", "Run/walk")
RECOVERY_RUN = WorkoutForm("recovery_run", "Recovery run")
LONG_RUN = WorkoutForm("long_run", "Long run")
TEMPO_RUN = WorkoutForm("tempo_run", "Tempo run")
INTERVAL_WORKOUT = WorkoutForm("interval_workout", "Interval workout")

FORM_BY_NAME: dict[str, WorkoutForm] = {
    "easy_run": EASY_RUN,
    "run_walk": RUN_WALK,
    "recovery_run": RECOVERY_RUN,
    "long_run": LONG_RUN,
    "tempo_run": TEMPO_RUN,
    "interval_workout": INTERVAL_WORKOUT,
}


@dataclass(frozen=True, slots=True)
class WorkoutWithForm:
    """A workout paired with its authoring form.

    Recipes instantiate workouts and attach the form explicitly. The pair
    travels through the application layer; the form is not stored inside the
    program YAML.
    """

    workout: Workout
    form: WorkoutForm


_RECOVERY_LIKE = frozenset({"recovery", "rest"})
_MAX_RECOVERY_RUN_SECONDS = 30 * 60


def infer_workout_form(workout: Workout) -> WorkoutForm:
    """Infer the form of a workout from its step structure.

    The order of checks reflects specificity: walk-driven patterns are the
    most distinctive, structured intervals next, then paced tempo work,
    short solo runs last. Anything else is an easy run, including long
    runs because "long" is not derivable from structure alone.
    """
    steps = workout.steps
    if _has_action(steps, "walk"):
        return RUN_WALK
    if _has_run_with_recovery_repeat(steps):
        return INTERVAL_WORKOUT
    if _has_paced_run_outside_repeat(steps):
        return TEMPO_RUN
    if _is_short_solo_run(steps):
        return RECOVERY_RUN
    return EASY_RUN


def _has_action(steps: tuple[Step, ...], action: str) -> bool:
    for step in steps:
        if step.action == action:
            return True
        if step.action == "repeat" and _has_action(step.steps, action):
            return True
    return False


def _has_run_with_recovery_repeat(steps: tuple[Step, ...]) -> bool:
    for step in steps:
        if step.action != "repeat":
            continue
        actions = {child.action for child in step.steps}
        if "run" in actions and actions & _RECOVERY_LIKE:
            return True
        if _has_run_with_recovery_repeat(step.steps):
            return True
    return False


def _has_paced_run_outside_repeat(steps: tuple[Step, ...]) -> bool:
    for step in steps:
        if step.action == "run" and step.pace is not None:
            return True
        if step.action == "repeat" and _has_paced_run_outside_repeat(step.steps):
            return True
    return False


def _is_short_solo_run(steps: tuple[Step, ...]) -> bool:
    if len(steps) != 1:
        return False
    only = steps[0]
    if only.action != "run" or only.end_kind != "time":
        return False
    if only.pace is not None:
        return False
    return (only.end_value or 0) <= _MAX_RECOVERY_RUN_SECONDS


__all__ = [
    "EASY_RUN",
    "FORM_BY_NAME",
    "INTERVAL_WORKOUT",
    "LONG_RUN",
    "RECOVERY_RUN",
    "RUN_WALK",
    "TEMPO_RUN",
    "WorkoutForm",
    "WorkoutFormName",
    "WorkoutWithForm",
    "infer_workout_form",
]
