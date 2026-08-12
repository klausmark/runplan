"""Recipe domain contract.

A :class:`WorkoutRecipe` is a schedule-independent workout shape that
instantiates into an explicit :class:`~runplan.domain.models.Workout` paired
with a :class:`~runplan.domain.workout_form.WorkoutForm`. Recipes are
authoring concepts and never enter program YAML. The instantiation function
leaves scheduling fields (:attr:`Workout.id`, :attr:`Workout.day`,
:attr:`Workout.schedule_date`, and the Garmin fields) at their defaults; the
``instantiate_recipe`` use case (planned for step 6) is responsible for
assigning them when a recipe lands in a program.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..errors import WorkoutDefinitionError
from ..models import Step, Workout
from ..workout_form import FORM_BY_NAME, WorkoutForm, WorkoutWithForm

__all__ = [
    "RecipeInstantiationError",
    "RecipeParameters",
    "WorkoutRecipe",
    "recipe",
]


@dataclass(frozen=True, slots=True)
class RecipeParameters:
    """Marker base class for recipe parameter dataclasses.

    Each recipe declares a concrete subclass with the typed fields it
    accepts. The dataclass's ``__post_init__`` is the natural place to
    validate ranges (positive minutes, sensible distances, non-empty pace
    ranges, and so on). Recipes never accept keyword arguments directly;
    callers must construct the parameter dataclass and pass it to
    :meth:`WorkoutRecipe.instantiate`.
    """


class RecipeInstantiationError(WorkoutDefinitionError):
    """Raised when a recipe is asked to instantiate with invalid parameters."""


def _validate_form(form: WorkoutForm) -> None:
    if form not in FORM_BY_NAME.values():
        raise ValueError(f"unknown workout form {form!r}; use one of {sorted(FORM_BY_NAME)}")


def _validate_parameters_type(parameters_type: type[RecipeParameters]) -> None:
    if not isinstance(parameters_type, type) or not issubclass(parameters_type, RecipeParameters):
        raise ValueError(
            f"parameters_type must be a RecipeParameters subclass, got {parameters_type!r}"
        )


def _validate_callable(
    name: str,
    value: Callable[..., Any] | None,
) -> None:
    if value is not None and not callable(value):
        raise ValueError(f"{name} must be callable or None")


@dataclass(frozen=True, slots=True)
class WorkoutRecipe:
    """A schedule-independent workout shape with parameters and a builder.

    The fields are:

    - ``key``: stable identifier; the recipe catalogue groups recipes by
      ``form`` and exposes them by key for the recommendation engine.
    - ``form``: the canonical workout form the recipe belongs to. Declared
      explicitly so long runs and other relational forms are not inferred
      from a single-run structure.
    - ``label``: human-readable name used in the UI selector and on
      instantiated workout titles.
    - ``description``: short paragraph used by the UI.
    - ``parameters_type``: the typed dataclass callers must pass to
      :meth:`instantiate`.
    - ``build_steps``: typed callable that turns the parameters into a
      tuple of :class:`Step` instances.
    - ``build_name``: optional callable that builds a customised workout
      name from the parameters; defaults to ``label``.
    - ``build_description``: optional callable that builds a customised
      description from the parameters; defaults to ``description``.
    """

    key: str
    form: WorkoutForm
    label: str
    description: str
    parameters_type: type[RecipeParameters]
    build_steps: Callable[..., tuple[Step, ...]]
    build_name: Callable[..., str] | None = None
    build_description: Callable[..., str] | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.key, str) or not self.key.strip():
            raise ValueError("recipe key must be a non-empty string")
        if not isinstance(self.label, str) or not self.label.strip():
            raise ValueError("recipe label must be a non-empty string")
        if not isinstance(self.description, str):
            raise ValueError("recipe description must be a string")
        _validate_form(self.form)
        _validate_parameters_type(self.parameters_type)
        _validate_callable("build_steps", self.build_steps)
        _validate_callable("build_name", self.build_name)
        _validate_callable("build_description", self.build_description)

    def instantiate(self, params: RecipeParameters) -> WorkoutWithForm:
        """Validate the parameters and build a schedule-free workout.

        The returned :class:`~runplan.domain.workout_form.WorkoutWithForm`
        carries the recipe's form and a :class:`Workout` whose scheduling
        and Garmin fields are left at their defaults.
        """
        if not isinstance(params, self.parameters_type):
            raise RecipeInstantiationError(
                f"recipe {self.key!r} expects "
                f"{self.parameters_type.__name__}, got {type(params).__name__}"
            )
        steps = self.build_steps(params)
        if not isinstance(steps, tuple):
            steps = tuple(steps)
        for index, step in enumerate(steps, start=1):
            if not isinstance(step, Step):
                raise RecipeInstantiationError(
                    f"recipe {self.key!r} produced {type(step).__name__!r} at steps[{index}]"
                )
        name = self.build_name(params) if self.build_name else self.label
        description = self.build_description(params) if self.build_description else self.description
        workout = Workout(
            name=name,
            description=description,
            steps=steps,
        )
        return WorkoutWithForm(workout=workout, form=self.form)


def recipe(
    *,
    key: str,
    form: WorkoutForm,
    label: str,
    description: str,
    parameters_type: type[RecipeParameters],
    build_name: Callable[..., str] | None = None,
    build_description: Callable[..., str] | None = None,
) -> Callable[[Callable[..., tuple[Step, ...]]], WorkoutRecipe]:
    """Bind a typed step builder to a :class:`WorkoutRecipe`.

    The decorator receives the recipe metadata and returns a small factory
    that pairs ``build_steps`` with the metadata into a complete
    :class:`WorkoutRecipe`. It keeps the recipe definition on one screen and
    removes the dataclass ceremony from each module.
    """

    def bind(build_steps: Callable[..., tuple[Step, ...]]) -> WorkoutRecipe:
        return WorkoutRecipe(
            key=key,
            form=form,
            label=label,
            description=description,
            parameters_type=parameters_type,
            build_steps=build_steps,
            build_name=build_name,
            build_description=build_description,
        )

    return bind
