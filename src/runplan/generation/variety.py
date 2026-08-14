"""Variety selection over the recipe catalogue.

Step 9 moves variety from a string vocabulary (``"steady"``,
``"continuous_tempo"``, …) onto :class:`WorkoutRecipe` keys. The pickers
filter the recipe catalogue by form so the generator consumes the same
vocabulary as the rest of the application. The
:class:`VarietyBoard` records the last recipe used in each role and a
history of picks for the post-run variety summary.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..domain.workout_form import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    TEMPO_RUN,
    WorkoutForm,
)

if TYPE_CHECKING:
    from ..domain.recipes import WorkoutRecipe

__all__ = [
    "VarietyBoard",
    "pick_easy_recipe",
    "pick_long_run_recipe",
    "pick_quality_recipe",
    "summary_stats",
]


_KEY_FORMS: frozenset[WorkoutForm] = frozenset({LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT})


def _recipes_for_form(form: WorkoutForm) -> tuple[WorkoutRecipe, ...]:
    """Return every recipe in the catalogue whose form matches ``form``."""
    from ..domain.recipes import RECIPE_CATALOG

    return tuple(recipe for recipe in RECIPE_CATALOG if recipe.form is form)


def _filter(catalogue: Iterable[WorkoutRecipe], last_key: str | None) -> tuple[WorkoutRecipe, ...]:
    """Return ``catalogue`` minus the last picked recipe, when possible."""
    options = tuple(catalogue)
    if last_key is None or len(options) <= 1:
        return options
    filtered = tuple(option for option in options if option.key != last_key)
    return filtered or options


@dataclass(frozen=True, slots=True)
class VarietyBoard:
    """The last recipe used in each role plus slot counts.

    The board stores the recipe key (not the full recipe) to keep the
    type hashable and to match the variety summary's history list.
    History counters track every pick so the summary can count unique
    recipes used over the program.
    """

    last_long: str | None = None
    last_quality: str | None = None
    last_easy: str | None = None
    long_history: tuple[str, ...] = ()
    quality_history: tuple[str, ...] = ()
    easy_history: tuple[str, ...] = ()

    def with_long(self, key: str) -> VarietyBoard:
        return replace(self, last_long=key, long_history=self.long_history + (key,))

    def with_quality(self, key: str) -> VarietyBoard:
        return replace(self, last_quality=key, quality_history=self.quality_history + (key,))

    def with_easy(self, key: str) -> VarietyBoard:
        return replace(self, last_easy=key, easy_history=self.easy_history + (key,))


def replace(board: VarietyBoard, **changes: Any) -> VarietyBoard:
    """Return a copy of ``board`` with the given fields replaced."""
    return VarietyBoard(
        last_long=changes.get("last_long", board.last_long),
        last_quality=changes.get("last_quality", board.last_quality),
        last_easy=changes.get("last_easy", board.last_easy),
        long_history=changes.get("long_history", board.long_history),
        quality_history=changes.get("quality_history", board.quality_history),
        easy_history=changes.get("easy_history", board.easy_history),
    )


def pick_long_run_recipe(board: VarietyBoard, week: int) -> tuple[WorkoutRecipe, VarietyBoard]:
    """Pick a long-run recipe that avoids repeating the previous week."""
    options = _filter(_recipes_for_form(LONG_RUN), board.last_long)
    recipe = options[week % len(options)]
    return recipe, board.with_long(recipe.key)


def pick_quality_recipe(board: VarietyBoard, week: int) -> tuple[WorkoutRecipe, VarietyBoard]:
    """Pick a quality workout recipe (tempo or interval) that varies."""
    catalogue = _recipes_for_form(TEMPO_RUN) + _recipes_for_form(INTERVAL_WORKOUT)
    options = _filter(catalogue, board.last_quality)
    recipe = options[week % len(options)]
    return recipe, board.with_quality(recipe.key)


_EASY_RECIPE_KEYS: frozenset[str] = frozenset({"easy.continuous", "easy.with_strides"})


def pick_easy_recipe(
    board: VarietyBoard, week: int, *, short_target: bool = False
) -> tuple[WorkoutRecipe, VarietyBoard]:
    """Pick an easy workout recipe (or recovery) that varies.

    The picker filters the catalogue so the variety rotates between the
    pre-existing two easy recipes (``easy.continuous`` and
    ``easy.with_strides``); the run/walk and recovery recipes stay on
    their dedicated pickers.
    """
    form = RECOVERY_RUN if short_target else EASY_RUN
    if form is EASY_RUN:
        catalogue = tuple(
            recipe for recipe in _recipes_for_form(EASY_RUN) if recipe.key in _EASY_RECIPE_KEYS
        )
    else:
        catalogue = _recipes_for_form(RECOVERY_RUN)
    options = _filter(catalogue, board.last_easy)
    recipe = options[week % len(options)]
    return recipe, board.with_easy(recipe.key)


def summary_stats(board: VarietyBoard) -> dict[str, Any]:
    """Return a dictionary of variety diagnostics for the generated plan."""
    return {
        "long_run_types_used": len(set(board.long_history)),
        "quality_types_used": len(set(board.quality_history)),
        "easy_types_used": len(set(board.easy_history)),
        "long_run_history": list(board.long_history),
        "quality_history": list(board.quality_history),
        "easy_history": list(board.easy_history),
    }
