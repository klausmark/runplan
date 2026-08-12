"""Recipe domain contract and catalogue.

Step 3 introduces the recipe domain contract. A recipe is a
schedule-independent workout shape with typed parameters and a builder
that produces an explicit :class:`~runplan.domain.models.Workout` paired
with a :class:`~runplan.domain.workout_form.WorkoutForm`.

Usage::

    from runplan.domain.recipes import RECIPE_CATALOG, long_steady
    from runplan.domain.recipes import LongSteadyParameters

    recipe = next(r for r in RECIPE_CATALOG if r.key == "long.steady")
    pair = recipe.instantiate(LongSteadyParameters(target_km=12.0))

Recipes are authoring concepts. The ``RECIPE_CATALOG`` tuple is built
from the per-category modules below and is the single source of truth
that the recommendation engine and the ``instantiate_recipe`` use case
will consume.
"""

from __future__ import annotations

from .base import (
    RecipeInstantiationError,
    RecipeParameters,
    WorkoutRecipe,
    recipe,
)
from .easy import (
    EASY_RECIPES,
    EasyContinuousParameters,
    EasyWithStridesParameters,
    RecoveryDistanceParameters,
    RecoveryRunParameters,
    RunWalkBridgeParameters,
    RunWalkIntervalsParameters,
    RunWalkPyramidParameters,
    WarmupRunParameters,
)
from .intervals import (
    INTERVAL_RECIPES,
    FartlekParameters,
    HillRepeatsParameters,
    Track1kParameters,
    Track400mParameters,
)
from .long import (
    LONG_RECIPES,
    LongSteadyParameters,
    LongWithFinishParameters,
    LongWithHillSurgesParameters,
    LongWithKickoutsParameters,
)
from .tempo import (
    TEMPO_RECIPES,
    ContinuousTempoParameters,
    CruiseIntervalsParameters,
)

RECIPE_CATALOG: tuple[WorkoutRecipe, ...] = (
    *EASY_RECIPES,
    *LONG_RECIPES,
    *TEMPO_RECIPES,
    *INTERVAL_RECIPES,
)


def get_recipe(key: str) -> WorkoutRecipe:
    """Return the recipe with the given key or raise :class:`KeyError`."""
    for entry in RECIPE_CATALOG:
        if entry.key == key:
            return entry
    raise KeyError(f"unknown recipe key {key!r}")


def recipes_by_form() -> dict[str, tuple[WorkoutRecipe, ...]]:
    """Group every catalogue recipe by its canonical form name."""
    grouped: dict[str, list[WorkoutRecipe]] = {}
    for entry in RECIPE_CATALOG:
        grouped.setdefault(entry.form.name, []).append(entry)
    return {name: tuple(items) for name, items in grouped.items()}


__all__ = [
    "ContinuousTempoParameters",
    "CruiseIntervalsParameters",
    "EASY_RECIPES",
    "EasyContinuousParameters",
    "EasyWithStridesParameters",
    "FartlekParameters",
    "HillRepeatsParameters",
    "INTERVAL_RECIPES",
    "LONG_RECIPES",
    "LongSteadyParameters",
    "LongWithFinishParameters",
    "LongWithHillSurgesParameters",
    "LongWithKickoutsParameters",
    "RECIPE_CATALOG",
    "RecoveryDistanceParameters",
    "RecoveryRunParameters",
    "RunWalkBridgeParameters",
    "RunWalkIntervalsParameters",
    "RunWalkPyramidParameters",
    "Track1kParameters",
    "Track400mParameters",
    "WarmupRunParameters",
    "WorkoutRecipe",
    "RecipeInstantiationError",
    "RecipeParameters",
    "get_recipe",
    "recipe",
    "recipes_by_form",
]
