"""Recipe catalogue and dose-form projection used by the Studio add-workout flow.

Step 7 connects the recipe catalogue to the Studio. The HTTP endpoints
serve two responses:

- :func:`list_recipes_response` returns every recipe grouped by form,
  each with a JSON-friendly parameter schema the frontend can render
  without bundling the dataclasses.
- :func:`preview_recipe_response` turns a parameter dictionary into the
  typed dataclass instance the recipe expects, runs the recipe's
  instantiator, and returns the resulting steps plus estimated totals.
  No persistence happens here; the Studio still saves through the
  existing ``add_workout`` transaction so the optimistic-revision
  contract is unchanged.

Structural rationale: this module is one web adapter with a single
reason to change (the recipe HTTP surface); the recipe catalogue itself
lives in :mod:`runplan.domain.recipes`.
"""

from __future__ import annotations

from dataclasses import fields, is_dataclass
from http import HTTPStatus
from typing import Any, get_type_hints

from .domain.errors import WorkoutDefinitionError
from .domain.estimates import DEFAULT_PACE_SECONDS_PER_KM, estimate_steps
from .domain.recipes import RECIPE_CATALOG, WorkoutRecipe
from .domain.recipes.base import RecipeInstantiationError
from .domain.workout_form import FORM_BY_NAME
from .presentation.text import step_view
from .users import WebError

__all__ = [
    "FORM_ORDER",
    "list_recipes_response",
    "preview_recipe_response",
]


FORM_ORDER: tuple[str, ...] = (
    "easy_run",
    "run_walk",
    "recovery_run",
    "long_run",
    "tempo_run",
    "interval_workout",
)


def _field_default(field: Any) -> Any:
    """Return the default value for a dataclass field, or :data:`None`."""
    if field.default is not None:
        return field.default
    factory = getattr(field, "default_factory", None)
    if factory is None:
        return None
    try:
        return factory()
    except TypeError:
        return None


def _is_pace_range(annotation: Any) -> bool:
    origin = getattr(annotation, "__origin__", None)
    if origin is tuple:
        args = annotation.__args__
        if len(args) != 2:
            return False
        return all(arg in (str, float, int) for arg in args)
    return False


def _unwrap_optional(annotation: Any) -> Any:
    args = getattr(annotation, "__args__", ())
    if len(args) == 2 and type(None) in args:
        return next(arg for arg in args if arg is not type(None))
    return annotation


def _field_spec(name: str, field: Any, annotation: Any) -> dict[str, Any]:
    """Return a JSON-friendly description of one dataclass field."""
    spec: dict[str, Any] = {"name": name, "label": name.replace("_", " ")}
    annotation = _unwrap_optional(annotation)
    if annotation is int:
        spec["type"] = "integer"
    elif annotation is float:
        spec["type"] = "number"
    elif annotation is bool:
        spec["type"] = "boolean"
    elif _is_pace_range(annotation):
        spec["type"] = "pace_range"
        spec["item_type"] = "string" if annotation.__args__[0] is str else "string"
    else:
        spec["type"] = "string"
    default = _field_default(field)
    spec["default"] = default
    spec["required"] = default is None
    return spec


def _recipe_spec(recipe: WorkoutRecipe) -> dict[str, Any]:
    params_type = recipe.parameters_type
    parameters: list[dict[str, Any]] = []
    if is_dataclass(params_type):
        hints = get_type_hints(params_type)
        for field in fields(params_type):
            if field.name.startswith("_"):
                continue
            parameters.append(_field_spec(field.name, field, hints.get(field.name, field.type)))
    return {
        "key": recipe.key,
        "label": recipe.label,
        "description": recipe.description,
        "form": recipe.form.name,
        "form_label": recipe.form.label,
        "parameters": parameters,
    }


def list_recipes_response() -> dict[str, Any]:
    """Return the catalogue grouped by form for the Studio selector."""
    grouped: dict[str, list[dict[str, Any]]] = {form: [] for form in FORM_ORDER}
    for recipe in RECIPE_CATALOG:
        grouped.setdefault(recipe.form.name, []).append(_recipe_spec(recipe))
    return {
        "forms": [
            {
                "name": form,
                "label": FORM_BY_NAME[form].label,
                "recipes": grouped.get(form, []),
            }
            for form in FORM_ORDER
        ],
    }


def _coerce_parameters(recipe: WorkoutRecipe, raw: dict[str, Any]) -> Any:
    """Turn a JSON dict into the typed parameter instance the recipe expects."""
    params_type = recipe.parameters_type
    if not is_dataclass(params_type):
        raise WebError(HTTPStatus.BAD_REQUEST, "Recipe does not expose a parameter dataclass")
    field_map = {field.name: field for field in fields(params_type)}
    hints = get_type_hints(params_type)
    kwargs: dict[str, Any] = {}
    for name, field in field_map.items():
        annotation = _unwrap_optional(hints.get(name, field.type))
        if name in raw:
            value = raw[name]
            if _is_pace_range(annotation) and value is not None:
                kwargs[name] = tuple(value)
            else:
                kwargs[name] = value
            continue
        default = _field_default(field)
        if (
            default is None
            and not getattr(field, "default_factory", None)
            and field.default is None
        ):
            continue
        kwargs[name] = default
    try:
        return params_type(**kwargs)
    except TypeError as exc:
        raise WebError(HTTPStatus.BAD_REQUEST, f"Invalid parameters: {exc}") from exc
    except ValueError as exc:
        raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc


def preview_recipe_response(payload: dict[str, Any]) -> dict[str, Any]:
    """Return the steps and totals for ``recipe_key`` with ``parameters``."""
    recipe_key = payload.get("recipe_key")
    if not isinstance(recipe_key, str) or not recipe_key:
        raise WebError(HTTPStatus.BAD_REQUEST, "recipe_key is required")
    recipe = next((item for item in RECIPE_CATALOG if item.key == recipe_key), None)
    if recipe is None:
        raise WebError(HTTPStatus.NOT_FOUND, f"unknown recipe key {recipe_key!r}")
    raw_parameters = payload.get("parameters")
    if not isinstance(raw_parameters, dict):
        raise WebError(HTTPStatus.BAD_REQUEST, "parameters must be an object")
    params = _coerce_parameters(recipe, raw_parameters)
    try:
        pair = recipe.instantiate(params)
    except RecipeInstantiationError as exc:
        raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
    except WorkoutDefinitionError as exc:
        raise WebError(HTTPStatus.UNPROCESSABLE_ENTITY, str(exc)) from exc
    except (TypeError, ValueError) as exc:
        raise WebError(HTTPStatus.BAD_REQUEST, f"Invalid parameters: {exc}") from exc
    estimate = estimate_steps(pair.workout.steps, DEFAULT_PACE_SECONDS_PER_KM)
    return {
        "recipe_key": recipe.key,
        "form": pair.form.name,
        "form_label": pair.form.label,
        "name": pair.workout.name,
        "description": pair.workout.description,
        "steps": step_view(pair.workout.steps),
        "estimated_duration_seconds": estimate.duration_seconds,
        "estimated_distance_meters": estimate.distance_meters,
        "distance_is_approximate": estimate.distance_is_approximate,
        "duration_is_approximate": estimate.duration_is_approximate,
    }
