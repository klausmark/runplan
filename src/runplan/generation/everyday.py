"""Pure rolling everyday horizon generator.

The everyday plan is an always-on mode that proposes the next 14 days
based on the runner profile, a broad goal, completed workouts, and
recent load. ``propose_everyday_horizon`` is a pure function: it never
reads the clock, the filesystem, or the network. ``today`` is injected
so the tests can pin a deterministic anchor.

The generator reuses :func:`runplan.application.coaching.recommend.recommend_workouts`
once per day. To make the recommender honour the key-workout rule across
the horizon boundary, the generator feeds every earlier proposed day
back into the synthetic :class:`CoachingContext` as if it had been
completed. The goal then caps the total count of key workouts inside the
rolling window.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import date, timedelta

from ..application.coaching.recommend import recommend_workouts
from ..domain.everyday import (
    EverydayGoal,
    EverydayHorizon,
    EverydayRequest,
    ProposedDay,
)
from ..domain.recipes import EasyContinuousParameters, get_recipe
from ..domain.recommendations import (
    KEY_WORKOUT_FORMS,
    CoachingContext,
    CompletedWorkout,
    RunnerPace,
    WorkoutRequestKind,
)
from ..domain.workout_form import WorkoutForm


def _key_workout_forms() -> frozenset[WorkoutForm]:
    """Re-export the frozenset of forms that count as a key workout."""
    return KEY_WORKOUT_FORMS


__all__ = ["propose_everyday_horizon"]


_LOOKBACK_DAYS = 35
"""Maximum days of completed history consulted when building the
synthetic context. Matches :data:`runplan.domain.load.BASELINE_DAYS`."""


_GOAL_BUDGET: dict[str, tuple[int, int]] = {
    "base": (0, 14),
    "maintain": (1, 14),
    "build": (1, 7),
    "peak": (2, 14),
}
"""Per-goal ``(max_key_workouts, window_days)`` budget.

The recommender still picks the day; the budget only caps how many
key workouts the horizon may contain within the rolling window.
"""


def _goal_budget(goal: EverydayGoal) -> tuple[int, int]:
    return _GOAL_BUDGET[goal]


def _recent_history_window_for(
    request: EverydayRequest,
    target: date,
) -> tuple[CompletedWorkout, ...]:
    """Return the history subset visible to the recommender for ``target``."""
    return tuple(w for w in request.history if 0 < (target - w.date).days <= _LOOKBACK_DAYS)


def _build_synthetic_history(
    request: EverydayRequest,
    target: date,
    proposed_so_far: tuple[ProposedDay, ...],
) -> tuple[CompletedWorkout, ...]:
    """Combine the runner's history with the proposed days the recommender
    must treat as completed when judging ``target``.

    Each proposed day becomes a synthetic :class:`CompletedWorkout` with
    a one-kilometre, ten-minute placeholder so the load classifier does
    not invent extremes. The recommender cares about the form more than
    the volume for the key-workout rule.
    """
    base = _recent_history_window_for(request, target)
    synthetic: list[CompletedWorkout] = []
    for day in proposed_so_far:
        if day.date >= target:
            continue
        synthetic.append(
            CompletedWorkout(
                date=day.date,
                form=day.form,
                distance_meters=1_000.0,
                duration_seconds=10 * 60,
            )
        )
    return tuple(sorted(base + tuple(synthetic), key=lambda w: w.date))


def _build_context(
    request: EverydayRequest,
    target: date,
    history: tuple[CompletedWorkout, ...],
) -> CoachingContext:
    pace = (
        RunnerPace(five_k_seconds=request.profile.five_k_seconds)
        if request.profile.has_pace()
        else None
    )
    return CoachingContext(
        pace=pace,
        readiness=None,
        request_kind=WorkoutRequestKind.DEFAULT,
        recent_completed_workouts=history,
    )


def _downgrade_to_easy(reasoning: tuple[str, ...]) -> ProposedDay:
    """Return a proposed day that replaces a key workout with the easy
    default, matching the goal's cap. Reasoning is rewritten so the
    runner sees why the suggestion changed.
    """
    recipe = get_recipe("easy.continuous")
    return ProposedDay(
        date=date(1970, 1, 1),
        form=recipe.form,
        recipe_key=recipe.key,
        parameters=EasyContinuousParameters(),
        reasoning=reasoning
        + ("The broad goal caps how many key workouts this week allows, so this one stays easy.",),
    )


def _session_for(
    target: date,
    recommendation,
    form: WorkoutForm,
) -> ProposedDay:
    return ProposedDay(
        date=target,
        form=form,
        recipe_key=recommendation.primary.recipe_key,
        parameters=recommendation.primary.parameters,
        reasoning=recommendation.reasoning,
        warnings=recommendation.warnings,
    )


def _key_count_in_window(
    proposed_so_far: tuple[ProposedDay, ...],
    target: date,
    window_days: int,
) -> int:
    return sum(
        1
        for day in proposed_so_far
        if day.form in _key_workout_forms() and 0 < (target - day.date).days <= window_days
    )


def _goal_allows_key(
    request: EverydayRequest, target: date, proposed_so_far: tuple[ProposedDay, ...]
) -> bool:
    max_key, window_days = _goal_budget(request.goal)
    if max_key <= 0:
        return False
    return _key_count_in_window(proposed_so_far, target, window_days) < max_key


def propose_everyday_horizon(
    request: EverydayRequest,
    *,
    today: date | None = None,
) -> EverydayHorizon:
    """Return the proposed :class:`EverydayHorizon` for ``request``.

    The function is pure: it inspects ``request.history`` only, never
    reads the clock, and never touches the filesystem. ``today`` is
    accepted for interface symmetry with the first-10K generator but
    is not used. The returned horizon carries the request's profile,
    goal, start date, and horizon length so the acceptance use case can
    rebuild the request without re-reading the program YAML.
    """
    days: list[ProposedDay] = []
    for offset in range(request.horizon_days):
        target = request.start_date + timedelta(days=offset)
        if target.isoweekday() not in request.profile.training_days:
            continue
        synthetic_history = _build_synthetic_history(request, target, tuple(days))
        context = _build_context(request, target, synthetic_history)
        recommendation = recommend_workouts(context, target)
        recipe = get_recipe(recommendation.primary.recipe_key)
        form = recipe.form
        downgrade = form in _key_workout_forms() and not _goal_allows_key(
            request, target, tuple(days)
        )
        if downgrade:
            downgraded = _downgrade_to_easy(recommendation.reasoning)
            days.append(replace(downgraded, date=target))
        else:
            days.append(_session_for(target, recommendation, form))
    return EverydayHorizon(
        profile=request.profile,
        goal=request.goal,
        start_date=request.start_date,
        horizon_days=request.horizon_days,
        days=tuple(days),
    )
