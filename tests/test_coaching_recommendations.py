"""Coaching recommendation engine (Step 5).

The recommender is a pure function that turns a
:class:`~runplan.domain.recommendations.CoachingContext` plus a target
date into a structured
:class:`~runplan.domain.recommendations.WorkoutRecommendation`. The
tests cover the contract, the seven scenarios listed in the plan, the
boundary behaviour at exactly the eligibility thresholds, and the
deterministic ordering of the output.
"""

from __future__ import annotations

from datetime import date, timedelta

from runplan import (
    EASY_RUN,
    INTERVAL_WORKOUT,
    KEY_WORKOUT_FORMS,
    LONG_RUN,
    RECIPE_CATALOG,
    RUN_WALK,
    TEMPO_RUN,
    CoachingContext,
    CompletedWorkout,
    Readiness,
    RunnerPace,
    WorkoutRequestKind,
    recipes_by_form,
    recommend_workouts,
)
from runplan.application.coaching.recommend import _classify_load
from runplan.domain.recipes import (
    RecoveryRunParameters,
)
from runplan.domain.recommendations import (
    RecipeSuggestion,
    WorkoutRecommendation,
)
from runplan.domain.workout_form import WorkoutForm

_TARGET_DAY = date(2026, 8, 12)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _completed(
    on: date, form: WorkoutForm, *, km: float = 5.0, minutes: int = 30
) -> CompletedWorkout:
    return CompletedWorkout(
        date=on,
        form=form,
        distance_meters=km * 1000,
        duration_seconds=minutes * 60,
    )


def _baseline_only(
    target: date,
    *,
    weeks: int = 4,
    km_per_week: float = 22.5,
    minutes_per_session: int = 35,
    sessions_per_week: int = 3,
) -> tuple[CompletedWorkout, ...]:
    """Build a steady baseline that does NOT touch the last seven days.

    Three sessions per week land on days 1, 4, and 7 of every week,
    ending at ``target - 8`` so the baseline window covers days 8 to
    29 with no workouts in days 1 to 7. The session length is long
    enough that adding a few short recent workouts does not push the
    duration ratio past 125 percent.
    """
    out: list[CompletedWorkout] = []
    end = target - timedelta(days=8)
    for week in range(weeks):
        for session in range(sessions_per_week):
            day_offset = session * 3 + 1
            out.append(
                _completed(
                    end - timedelta(days=week * 7 + day_offset),
                    EASY_RUN,
                    km=km_per_week / sessions_per_week,
                    minutes=minutes_per_session,
                )
            )
    return tuple(sorted(out, key=lambda w: w.date))


def _baseline_history(
    target: date,
    *,
    weeks: int = 4,
    km_per_week: float = 30.0,
    minutes_per_session: int = 25,
    sessions_per_week: int = 4,
) -> tuple[CompletedWorkout, ...]:
    """Build a steady baseline plus a few recent sessions.

    Four sessions per week land on days 2, 4, 6, and 8 of every week,
    giving the last seven days three workouts and the last 14 days
    seven workouts — comfortably above the 90-minute and
    three-workout eligibility gates. Density is uniform so recent
    load is classified as normal.
    """
    out: list[CompletedWorkout] = []
    for week in range(weeks):
        week_end = target - timedelta(days=1 + 7 * week)
        for session in range(sessions_per_week):
            day_offset = session * 2 + 2
            out.append(
                _completed(
                    week_end - timedelta(days=day_offset),
                    EASY_RUN,
                    km=km_per_week / sessions_per_week,
                    minutes=minutes_per_session,
                )
            )
    return tuple(sorted(out, key=lambda w: w.date))


# ---------------------------------------------------------------------------
# Contract — KEY_WORKOUT_FORMS constant
# ---------------------------------------------------------------------------


def test_key_workout_forms_includes_long_tempo_interval() -> None:
    assert KEY_WORKOUT_FORMS == frozenset({LONG_RUN, TEMPO_RUN, INTERVAL_WORKOUT})


# ---------------------------------------------------------------------------
# Contract — recommend_workouts signature
# ---------------------------------------------------------------------------


def test_recommend_workouts_is_pure_and_deterministic() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        pace=RunnerPace(five_k_seconds=20 * 60),
        readiness=Readiness.NORMAL,
        request_kind=WorkoutRequestKind.DEFAULT,
        recent_completed_workouts=history,
    )

    first = recommend_workouts(ctx, _TARGET_DAY)
    second = recommend_workouts(ctx, _TARGET_DAY)

    assert first == second


def test_recommend_workouts_returns_workout_recommendation() -> None:
    result = recommend_workouts(CoachingContext(), _TARGET_DAY)

    assert isinstance(result, WorkoutRecommendation)
    assert isinstance(result.primary, RecipeSuggestion)
    assert isinstance(result.alternatives, tuple)
    assert all(isinstance(alt, RecipeSuggestion) for alt in result.alternatives)
    assert all(isinstance(line, str) for line in result.reasoning)
    assert all(isinstance(line, str) for line in result.warnings)


def test_recommend_workouts_primary_and_alternatives_use_recipe_keys() -> None:
    result = recommend_workouts(CoachingContext(), _TARGET_DAY)

    keys = {result.primary.recipe_key, *(alt.recipe_key for alt in result.alternatives)}
    catalog_keys = {recipe.key for recipe in RECIPE_CATALOG}
    assert keys <= catalog_keys


def test_recommend_workouts_alternatives_exclude_primary() -> None:
    result = recommend_workouts(CoachingContext(), _TARGET_DAY)

    alternative_keys = [alt.recipe_key for alt in result.alternatives]
    assert result.primary.recipe_key not in alternative_keys


def test_recommend_workouts_alternatives_have_stable_order() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(recent_completed_workouts=history)

    first = recommend_workouts(ctx, _TARGET_DAY)
    second = recommend_workouts(ctx, _TARGET_DAY)

    assert [alt.recipe_key for alt in first.alternatives] == [
        alt.recipe_key for alt in second.alternatives
    ]


def test_recommend_workouts_primary_parameters_use_recipe_defaults() -> None:
    result = recommend_workouts(
        CoachingContext(request_kind=WorkoutRequestKind.RECOVERY),
        _TARGET_DAY,
    )

    assert isinstance(result.primary.parameters, RecoveryRunParameters)


def test_long_run_form_is_never_auto_selected() -> None:
    history = _baseline_history(_TARGET_DAY)
    for kind in WorkoutRequestKind:
        result = recommend_workouts(
            CoachingContext(
                recent_completed_workouts=history,
                request_kind=kind,
            ),
            _TARGET_DAY,
        )
        from runplan import get_recipe

        form = get_recipe(result.primary.recipe_key).form
        assert form is not LONG_RUN, f"recommender picked LONG_RUN for request_kind={kind}"


# ---------------------------------------------------------------------------
# Scenarios from the plan
# ---------------------------------------------------------------------------


def test_scenario_low_load_eligible_default_picks_key_workout() -> None:
    """Default request with healthy baseline and no recent key picks a key
    workout; without pace data, the recommender chooses interval.fartlek
    (effort-based)."""
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(recent_completed_workouts=history)

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "interval.fartlek"


def test_scenario_low_load_eligible_default_with_pace_picks_tempo() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        pace=RunnerPace(five_k_seconds=20 * 60),
        recent_completed_workouts=history,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "tempo.continuous"


def test_scenario_high_load_default_picks_recovery() -> None:
    baseline = _baseline_history(_TARGET_DAY, km_per_week=20.0)
    recent = tuple(
        _completed(_TARGET_DAY - timedelta(days=days_back), EASY_RUN, km=8.0, minutes=50)
        for days_back in (1, 2, 3, 4)
    )
    ctx = CoachingContext(
        recent_completed_workouts=baseline + recent,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"
    assert any("above your usual range" in line for line in result.reasoning)


def test_scenario_recent_key_workout_default_picks_easy() -> None:
    baseline = _baseline_only(_TARGET_DAY, km_per_week=24.0)
    recent = (
        _completed(_TARGET_DAY - timedelta(days=2), EASY_RUN, km=6, minutes=30),
        _completed(_TARGET_DAY - timedelta(days=4), EASY_RUN, km=6, minutes=30),
        _completed(_TARGET_DAY - timedelta(days=6), EASY_RUN, km=6, minutes=30),
    )
    yesterday_key = (_completed(_TARGET_DAY - timedelta(days=2), TEMPO_RUN, km=8, minutes=45),)
    ctx = CoachingContext(
        recent_completed_workouts=baseline + recent + yesterday_key,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "easy.continuous"
    assert any("key workout" in line.lower() for line in result.reasoning)


def test_scenario_recovery_request_always_picks_recovery() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        recent_completed_workouts=history,
        request_kind=WorkoutRequestKind.RECOVERY,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"


def test_scenario_no_history_default_picks_easy() -> None:
    ctx = CoachingContext()  # no recent_completed_workouts

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "easy.continuous"
    assert any("not enough recent" in line for line in result.reasoning)


def test_scenario_key_request_without_pace_uses_fartlek_and_explains() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        recent_completed_workouts=history,
        request_kind=WorkoutRequestKind.KEY,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "interval.fartlek"
    assert any("pace" in line.lower() for line in result.reasoning)


def test_scenario_low_readiness_default_picks_recovery() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        recent_completed_workouts=history,
        readiness=Readiness.LOW,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"
    assert any("readiness is low" in line.lower() for line in result.reasoning)


def test_scenario_eight_days_since_key_without_separator_picks_easy() -> None:
    baseline = _baseline_only(_TARGET_DAY)
    recent_run_walk = (
        _completed(_TARGET_DAY - timedelta(days=2), RUN_WALK, km=6, minutes=30),
        _completed(_TARGET_DAY - timedelta(days=4), RUN_WALK, km=6, minutes=30),
        _completed(_TARGET_DAY - timedelta(days=6), RUN_WALK, km=6, minutes=30),
    )
    old_key = (
        _completed(_TARGET_DAY - timedelta(days=8), INTERVAL_WORKOUT, km=8, minutes=45),
        _completed(_TARGET_DAY - timedelta(days=15), LONG_RUN, km=12, minutes=70),
    )
    ctx = CoachingContext(
        recent_completed_workouts=baseline + recent_run_walk + old_key,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "easy.continuous"
    assert any("easy run after" in line for line in result.reasoning)


def test_scenario_key_request_blocked_by_low_readiness_returns_recovery() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        recent_completed_workouts=history,
        readiness=Readiness.LOW,
        request_kind=WorkoutRequestKind.KEY,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"
    assert any("readiness is low" in line.lower() for line in result.reasoning)


def test_scenario_already_completed_target_day_emits_warning() -> None:
    completed_today = (_completed(_TARGET_DAY, EASY_RUN, km=5, minutes=30),)
    ctx = CoachingContext(
        recent_completed_workouts=completed_today,
        request_kind=WorkoutRequestKind.RECOVERY,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"
    assert any("already recorded" in line.lower() for line in result.warnings)


# ---------------------------------------------------------------------------
# Request precedence
# ---------------------------------------------------------------------------


def test_request_kind_easy_with_low_readiness_downgrades_to_recovery() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        recent_completed_workouts=history,
        readiness=Readiness.LOW,
        request_kind=WorkoutRequestKind.EASY,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"


def test_request_kind_easy_with_normal_readiness_picks_easy() -> None:
    history = _baseline_history(_TARGET_DAY)
    ctx = CoachingContext(
        recent_completed_workouts=history,
        readiness=Readiness.NORMAL,
        request_kind=WorkoutRequestKind.EASY,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "easy.continuous"


def test_readiness_high_does_not_override_high_load() -> None:
    baseline = _baseline_history(_TARGET_DAY, km_per_week=20.0)
    recent = tuple(
        _completed(_TARGET_DAY - timedelta(days=days_back), EASY_RUN, km=9.0, minutes=55)
        for days_back in (1, 2, 3, 4)
    )
    ctx = CoachingContext(
        recent_completed_workouts=baseline + recent,
        readiness=Readiness.HIGH,
    )

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "recovery.run"


# ---------------------------------------------------------------------------
# Boundary tests — load classification
# ---------------------------------------------------------------------------


def test_classify_load_low_at_exactly_80_percent_with_5km_margin() -> None:
    baseline = _baseline_only(_TARGET_DAY, km_per_week=25.0)
    low_recent = (_completed(_TARGET_DAY - timedelta(days=2), EASY_RUN, km=4.0, minutes=25),)

    assert _classify_load(baseline + low_recent, _TARGET_DAY).value == "low"


def test_classify_load_normal_at_81_percent_of_baseline() -> None:
    baseline = _baseline_only(_TARGET_DAY, km_per_week=25.0)
    mild_recent = (
        _completed(_TARGET_DAY - timedelta(days=2), EASY_RUN, km=7.0, minutes=35),
        _completed(_TARGET_DAY - timedelta(days=4), EASY_RUN, km=7.0, minutes=35),
        _completed(_TARGET_DAY - timedelta(days=6), EASY_RUN, km=7.0, minutes=35),
    )

    assert _classify_load(baseline + mild_recent, _TARGET_DAY).value == "normal"


def test_classify_load_high_at_exactly_125_percent_with_5km_margin() -> None:
    baseline = _baseline_only(_TARGET_DAY, km_per_week=20.0)
    high_recent = (
        _completed(_TARGET_DAY - timedelta(days=1), EASY_RUN, km=12.0, minutes=70),
        _completed(_TARGET_DAY - timedelta(days=3), EASY_RUN, km=13.0, minutes=75),
    )

    assert _classify_load(baseline + high_recent, _TARGET_DAY).value == "high"


def test_classify_load_normal_at_124_percent_of_baseline() -> None:
    baseline = _baseline_only(_TARGET_DAY, km_per_week=20.0)
    mild_recent = (
        _completed(_TARGET_DAY - timedelta(days=1), EASY_RUN, km=10.0, minutes=60),
        _completed(_TARGET_DAY - timedelta(days=3), EASY_RUN, km=9.0, minutes=55),
    )

    assert _classify_load(baseline + mild_recent, _TARGET_DAY).value == "normal"


def test_classify_load_unknown_when_baseline_has_few_weeks() -> None:
    sparse = (_completed(_TARGET_DAY - timedelta(days=10), EASY_RUN, km=5, minutes=30),)

    assert _classify_load(sparse, _TARGET_DAY).value == "unknown"


def test_classify_load_high_when_two_recent_key_workouts() -> None:
    history = (
        _completed(_TARGET_DAY - timedelta(days=2), INTERVAL_WORKOUT, km=8, minutes=45),
        _completed(_TARGET_DAY - timedelta(days=4), TEMPO_RUN, km=8, minutes=45),
    )

    assert _classify_load(history, _TARGET_DAY).value == "high"


# ---------------------------------------------------------------------------
# Boundary tests — key eligibility
# ---------------------------------------------------------------------------


def test_seven_days_since_last_key_blocks_eligibility() -> None:
    history = _baseline_history(_TARGET_DAY)
    history_with_key = history + (
        _completed(_TARGET_DAY - timedelta(days=7), INTERVAL_WORKOUT, km=8, minutes=45),
    )
    ctx = CoachingContext(recent_completed_workouts=history_with_key)

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key != "interval.fartlek"
    assert result.primary.recipe_key != "tempo.continuous"


def test_eight_days_since_key_with_separator_passes_eligibility() -> None:
    history = _baseline_history(_TARGET_DAY)
    history_with_key = history + (
        _completed(_TARGET_DAY - timedelta(days=8), INTERVAL_WORKOUT, km=8, minutes=45),
        _completed(_TARGET_DAY - timedelta(days=2), EASY_RUN, km=5, minutes=30),
    )
    ctx = CoachingContext(recent_completed_workouts=history_with_key)

    result = recommend_workouts(ctx, _TARGET_DAY)

    assert result.primary.recipe_key == "interval.fartlek"


def test_unknown_load_does_not_block_but_does_not_enable_key() -> None:
    sparse = (_completed(_TARGET_DAY - timedelta(days=10), EASY_RUN, km=5, minutes=30),)

    assert _classify_load(sparse, _TARGET_DAY).value == "unknown"

    result = recommend_workouts(
        CoachingContext(recent_completed_workouts=sparse),
        _TARGET_DAY,
    )
    assert result.primary.recipe_key == "easy.continuous"


# ---------------------------------------------------------------------------
# Coverage — every catalogue recipe can be returned as the primary
# ---------------------------------------------------------------------------


def test_every_form_has_at_least_one_recommendable_primary() -> None:
    grouped = recipes_by_form()
    for form_name, recipes_in_form in grouped.items():
        keys = {recipe.key for recipe in recipes_in_form}
        assert keys, f"form {form_name} has no recipes"

        assert recipes_in_form, f"no recipes for form {form_name}"
