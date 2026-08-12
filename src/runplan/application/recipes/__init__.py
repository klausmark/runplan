"""Recipe-driven program editing use cases.

Step 6 introduces :func:`instantiate_recipe`, which turns a recipe and
its parameters into a new explicit workout placed inside a program
YAML document. The use case is web-agnostic: callers inject a
:class:`~runplan.application.ports.ProgramRepository` port so the
Studio, the CLI, and tests can all share the same validation and
persistence rules.
"""

from __future__ import annotations

from ..ports import ProgramRepository
from .instantiate import (
    InstantiateRecipeError,
    InstantiateRecipeResult,
    instantiate_recipe,
)

__all__ = [
    "InstantiateRecipeError",
    "InstantiateRecipeResult",
    "ProgramRepository",
    "instantiate_recipe",
]
