"""JSON round-trip helpers for the rolling everyday horizon.

The CLI's ``everyday propose --format json`` writes a horizon to disk
and ``everyday accept --proposal FILE`` reads it back. Both helpers live
here so the CLI and the test suite share the exact same wire format.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from ...domain.everyday import EverydayHorizon, EverydayProfile, ProposedDay
from ...domain.recipes import get_recipe
from ...domain.workout_form import FORM_BY_NAME

__all__ = ["horizon_from_payload", "horizon_to_payload"]


@dataclass(frozen=True, slots=True)
class _ProfileShape:
    """Sentinel placeholder so the typing helpers import without circulars."""


def horizon_to_payload(horizon: EverydayHorizon) -> dict[str, Any]:
    """Serialise a horizon to a JSON-friendly dict."""
    return {
        "profile": _profile_to_payload(horizon.profile),
        "goal": horizon.goal,
        "start_date": horizon.start_date.isoformat(),
        "horizon_days": horizon.horizon_days,
        "days": [_day_to_payload(day) for day in horizon.days],
    }


def horizon_from_payload(payload: dict[str, Any]) -> EverydayHorizon:
    """Reconstruct an :class:`EverydayHorizon` from a JSON payload."""
    profile = _profile_from_payload(payload["profile"])
    days = [_day_from_payload(entry) for entry in payload["days"]]
    return EverydayHorizon(
        profile=profile,
        goal=payload["goal"],
        start_date=date.fromisoformat(payload["start_date"]),
        horizon_days=int(payload["horizon_days"]),
        days=tuple(days),
    )


def _profile_to_payload(profile: EverydayProfile) -> dict[str, Any]:
    return {
        "five_k_seconds": profile.five_k_seconds,
        "weekly_km_target": profile.weekly_km_target,
        "training_days": list(profile.training_days),
        "preferred_long_run_day": profile.preferred_long_run_day,
    }


def _profile_from_payload(payload: dict[str, Any]) -> EverydayProfile:
    return EverydayProfile(
        five_k_seconds=float(payload["five_k_seconds"]),
        weekly_km_target=float(payload["weekly_km_target"]),
        training_days=tuple(int(day) for day in payload["training_days"]),
        preferred_long_run_day=(
            int(payload["preferred_long_run_day"])
            if payload.get("preferred_long_run_day") is not None
            else None
        ),
    )


def _day_to_payload(day: ProposedDay) -> dict[str, Any]:
    return {
        "date": day.date.isoformat(),
        "form": day.form.name,
        "recipe_key": day.recipe_key,
        "parameters": {
            "type": type(day.parameters).__name__,
            "values": _parameters_to_payload(day.parameters),
        },
        "reasoning": list(day.reasoning),
        "warnings": list(day.warnings),
    }


def _parameters_to_payload(parameters: Any) -> dict[str, Any]:
    excluded = {"__post_init_validated"}
    values: dict[str, Any] = {}
    for field in getattr(parameters, "__dataclass_fields__", {}):
        if field in excluded:
            continue
        values[field] = getattr(parameters, field)
    return values


def _day_from_payload(payload: dict[str, Any]) -> ProposedDay:
    recipe = get_recipe(payload["recipe_key"])
    parameters_type = recipe.parameters_type
    parameters_values = dict(payload["parameters"]["values"])
    parameters = parameters_type(**parameters_values)
    return ProposedDay(
        date=date.fromisoformat(payload["date"]),
        form=FORM_BY_NAME[payload["form"]],
        recipe_key=payload["recipe_key"],
        parameters=parameters,
        reasoning=tuple(payload.get("reasoning", [])),
        warnings=tuple(payload.get("warnings", [])),
    )
