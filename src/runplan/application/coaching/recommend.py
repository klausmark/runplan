"""Pure recommendation logic for the coaching engine.

The recommender is a single pure function that takes a
:class:`~runplan.domain.recommendations.CoachingContext` and a
``target_day`` and returns a structured
:class:`~runplan.domain.recommendations.WorkoutRecommendation`. It
uses the recipe catalogue as the source of truth for what it can pick,
applies the key-workout rule from ``docs/program-prompt.md`` and the
easy-default rule, and never reads from the filesystem or the clock.

The function is intentionally conservative: easy running is the
default; a key workout must earn its place. Step 6 (``instantiate_recipe``)
takes the recommendation's primary suggestion and writes it into a
program.

Recent-load classification lives in :mod:`runplan.domain.load` so the
rolling everyday horizon in :mod:`runplan.generation.everyday` can share
the same constants and helpers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ...domain.load import (
    MIN_HISTORY_MINUTES,
    MIN_HISTORY_WORKOUTS,
    RECENT_HISTORY_DAYS,
    RECENT_KEY_DAYS,
    LoadLevel,
    classify_load,
)
from ...domain.recipes import get_recipe, recipes_by_form
from ...domain.recommendations import (
    KEY_WORKOUT_FORMS,
    CoachingContext,
    CompletedWorkout,
    Readiness,
    RecipeSuggestion,
    WorkoutRecommendation,
    WorkoutRequestKind,
)
from ...domain.workout_form import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    LONG_RUN,
    RECOVERY_RUN,
    RUN_WALK,
    TEMPO_RUN,
    WorkoutForm,
)

__all__ = ["recommend_workouts"]


@dataclass(frozen=True, slots=True)
class _FormDecision:
    form: WorkoutForm
    reasoning: tuple[str, ...]


def recommend_workouts(
    context: CoachingContext,
    target_day: date,
) -> WorkoutRecommendation:
    """Return a recommendation for the workout to do on ``target_day``.

    The function is pure: it inspects ``context.recent_completed_workouts``
    only, never reads the clock, and never touches the filesystem. The
    returned :class:`WorkoutRecommendation` carries a primary suggestion,
    a small set of alternatives in stable order, reasoning strings for
    the UI, and any warnings the runner should see.
    """
    warnings: list[str] = []
    if _has_completed_workout_on(context.recent_completed_workouts, target_day):
        warnings.append(
            "A workout is already recorded for this day — consider this for the next planned run."
        )

    decision = _decide_form(context, target_day)
    primary_key = _primary_recipe_key(decision.form, has_pace=context.pace is not None)
    primary = RecipeSuggestion(primary_key, _default_parameters_for(primary_key))
    alternatives = _alternatives_for(decision.form, primary_key)

    return WorkoutRecommendation(
        primary=primary,
        alternatives=alternatives,
        reasoning=decision.reasoning,
        warnings=tuple(warnings),
    )


def _decide_form(context: CoachingContext, target_day: date) -> _FormDecision:
    kind = context.request_kind

    if kind is WorkoutRequestKind.RECOVERY:
        return _FormDecision(
            RECOVERY_RUN,
            ("You asked for recovery, so this is intentionally short and very easy.",),
        )

    if kind is WorkoutRequestKind.EASY:
        if context.readiness is Readiness.LOW:
            return _FormDecision(
                RECOVERY_RUN,
                (
                    "Readiness is low today, so choose a short recovery run "
                    "rather than forcing intensity.",
                ),
            )
        return _FormDecision(EASY_RUN, ("You asked for an easy run.",))

    if kind is WorkoutRequestKind.KEY:
        if _is_key_eligible(context, target_day):
            return _FormDecision(
                _key_form(has_pace=context.pace is not None),
                _key_eligible_reasoning(context, target_day),
            )
        blocked = _blocked_key_reasoning(context, target_day)
        fallback = _fallback_form_after_blocked_key(context, target_day)
        return _FormDecision(fallback, (blocked,))

    return _decide_default_form(context, target_day)


def _decide_default_form(context: CoachingContext, target_day: date) -> _FormDecision:
    if context.readiness is Readiness.LOW:
        return _FormDecision(
            RECOVERY_RUN,
            (
                "Readiness is low today, so choose a short recovery run "
                "rather than forcing intensity.",
            ),
        )

    load = classify_load(context.recent_completed_workouts, target_day)
    if load is LoadLevel.HIGH:
        return _FormDecision(
            RECOVERY_RUN,
            (
                "Your recent running load is above your usual range, so a "
                "recovery run is the better choice today.",
            ),
        )

    if _is_key_eligible(context, target_day):
        return _FormDecision(
            _key_form(has_pace=context.pace is not None),
            _key_eligible_reasoning(context, target_day),
        )

    return _FormDecision(EASY_RUN, (_default_easy_reasoning(context, target_day),))


def _fallback_form_after_blocked_key(context: CoachingContext, target_day: date) -> WorkoutForm:
    if context.readiness is Readiness.LOW:
        return RECOVERY_RUN
    if classify_load(context.recent_completed_workouts, target_day) is LoadLevel.HIGH:
        return RECOVERY_RUN
    return EASY_RUN


def _blocked_key_reasoning(context: CoachingContext, target_day: date) -> str:
    if context.readiness is Readiness.LOW:
        return (
            "Readiness is low today, so choose a short recovery run rather than forcing intensity."
        )
    load = classify_load(context.recent_completed_workouts, target_day)
    if load is LoadLevel.HIGH:
        return (
            "Your recent running load is above your usual range, so a "
            "recovery run is the better choice today."
        )
    return "Your last key workout still needs an easy run after it, so keep this one easy."


def _default_easy_reasoning(context: CoachingContext, target_day: date) -> str:
    history = _recent_history(context.recent_completed_workouts, target_day)
    if len(history) < MIN_HISTORY_WORKOUTS or _total_minutes(history) < MIN_HISTORY_MINUTES:
        return (
            "There is not enough recent running history to prescribe a key "
            "workout confidently, so start easy."
        )
    return "Your last key workout still needs an easy run after it, so keep this one easy."


def _key_eligible_reasoning(context: CoachingContext, target_day: date) -> tuple[str, ...]:
    if context.pace is None:
        return (
            "Your recent load is manageable and you have had at least seven "
            "days without a key workout.",
            "No current pace data is available, so this workout uses effort "
            "rather than an invented pace target.",
        )
    return (
        "Your recent load is manageable and you have had at least seven "
        "days without a key workout.",
    )


def _is_key_eligible(context: CoachingContext, target_day: date) -> bool:
    if context.readiness is Readiness.LOW:
        return False

    history = _recent_history(context.recent_completed_workouts, target_day)
    if len(history) < MIN_HISTORY_WORKOUTS:
        return False
    if _total_minutes(history) < MIN_HISTORY_MINUTES:
        return False

    if _has_key_in_last_n_days(context.recent_completed_workouts, target_day, RECENT_KEY_DAYS):
        return False

    if not _has_key_separator(context.recent_completed_workouts, target_day):
        return False

    load = classify_load(context.recent_completed_workouts, target_day)
    if load is LoadLevel.HIGH:
        return False

    return True


def _recent_history(
    workouts: tuple[CompletedWorkout, ...], target_day: date
) -> tuple[CompletedWorkout, ...]:
    return tuple(w for w in workouts if 0 < (target_day - w.date).days <= RECENT_HISTORY_DAYS)


def _has_key_in_last_n_days(
    workouts: tuple[CompletedWorkout, ...], target_day: date, days: int
) -> bool:
    return any(
        w.form in KEY_WORKOUT_FORMS and 0 < (target_day - w.date).days <= days for w in workouts
    )


def _has_key_separator(workouts: tuple[CompletedWorkout, ...], target_day: date) -> bool:
    before = tuple(w for w in workouts if w.date < target_day)
    if not before:
        return True
    sorted_workouts = tuple(sorted(before, key=lambda w: w.date))
    last_key = None
    for workout in reversed(sorted_workouts):
        if workout.form in KEY_WORKOUT_FORMS:
            last_key = workout
            break
    if last_key is None:
        return True
    return any(
        w.form in {EASY_RUN, RECOVERY_RUN} and w.date > last_key.date for w in sorted_workouts
    )


def _total_minutes(workouts: tuple[CompletedWorkout, ...]) -> float:
    return sum(w.duration_seconds for w in workouts) / 60.0


def _has_completed_workout_on(workouts: tuple[CompletedWorkout, ...], target_day: date) -> bool:
    return any(w.date == target_day for w in workouts)


def _key_form(has_pace: bool) -> WorkoutForm:
    return TEMPO_RUN if has_pace else INTERVAL_WORKOUT


def _primary_recipe_key(form: WorkoutForm, *, has_pace: bool) -> str:
    if form is TEMPO_RUN and not has_pace:
        return "interval.fartlek"
    if form is INTERVAL_WORKOUT:
        return "interval.fartlek"
    if form is EASY_RUN:
        return "easy.continuous"
    if form is RECOVERY_RUN:
        return "recovery.run"
    if form is RUN_WALK:
        return "run_walk.intervals"
    if form is LONG_RUN:
        return "long.steady"
    if form is TEMPO_RUN:
        return "tempo.continuous"
    raise ValueError(f"unknown workout form {form!r}")


def _default_parameters_for(recipe_key: str):
    return get_recipe(recipe_key).parameters_type()


def _alternatives_for(form: WorkoutForm, primary_key: str) -> tuple[RecipeSuggestion, ...]:
    grouped = recipes_by_form()
    candidates = grouped[form.name]
    return tuple(
        RecipeSuggestion(recipe.key, _default_parameters_for(recipe.key))
        for recipe in candidates
        if recipe.key != primary_key
    )
