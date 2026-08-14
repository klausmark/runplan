"""Human-readable formatter for the rolling everyday horizon.

The CLI uses this formatter to render ``everyday propose`` output. The
format is intentionally simpler than
:func:`runplan.presentation.overview.format_overview` because the
horizon carries recipe-level abstractions rather than compiled
workouts; the formatter focuses on the day, the form, the recipe key,
and the recommendations the runner should see.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..domain.everyday import EverydayHorizon


def format_everyday_horizon(horizon: EverydayHorizon) -> str:
    """Return a human-readable text rendering of ``horizon``."""
    lines = [
        f"Everyday plan ({horizon.goal}) starting {horizon.start_date.isoformat()}",
        f"Horizon: {horizon.horizon_days} days",
        "",
        "Workouts:",
    ]
    if not horizon.days:
        lines.append("  (no training days scheduled)")
    else:
        for day in horizon.days:
            weekday = day.date.strftime("%a")
            reasoning = ""
            if day.reasoning:
                reasoning = f"  — {day.reasoning[0]}"
            lines.append(
                f"  {day.date.isoformat()} ({weekday}) {day.form.label}: {day.recipe_key}{reasoning}"
            )
            if day.warnings:
                for warning in day.warnings:
                    lines.append(f"    ! {warning}")
    return "\n".join(lines)


def format_everyday_horizon_one_week(horizon: EverydayHorizon) -> str:
    """Return the first seven training days of the horizon as a preview.

    The Step 10 plan frames the horizon as "one extra working week" the
    runner can accept at a time. This formatter trims the horizon to
    the first seven calendar days starting at ``start_date``.
    """
    cutoff = horizon.start_date.toordinal() + 7
    preview_days = tuple(day for day in horizon.days if day.date.toordinal() < cutoff)
    preview = _replace_days(horizon, preview_days)
    return format_everyday_horizon(preview)


def _replace_days(horizon: EverydayHorizon, days: tuple) -> EverydayHorizon:
    from dataclasses import replace

    return replace(horizon, days=days)


__all__ = ["format_everyday_horizon", "format_everyday_horizon_one_week"]
