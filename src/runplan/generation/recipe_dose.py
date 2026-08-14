"""Recipe-aware dose calculator for the first 10K generator.

Step 9 turns the dispatch wrappers in :mod:`runplan.generation.workouts`
into typed recipe parameters. Each dose function is a pure mapping
from a recipe plus the generator's per-slot inputs to a concrete
:class:`~runplan.domain.recipes.RecipeParameters` instance. The
placement module then instantiates the recipe with the produced
parameters.

Phase-and-week rules (the tempo minute count, the cruise rep count, and
so on) live here in the form of small helper functions so the
underlying recipes stay focused on step shapes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from ..domain.workout_form import WorkoutForm
from .effort_pace import effort_to_pace_range, five_k_from_easy_pace_seconds
from .phase import PhaseKind

if TYPE_CHECKING:
    from ..domain.recipes import WorkoutRecipe
    from ..domain.recipes.base import RecipeParameters


_MIN_EASY_MINUTES = 20
_TEMPO_MIN_PER_KM = 6.0
_FIVE_K_EFFORT_FOR_TEMPO = "tempo"
_FIVE_K_EFFORT_FOR_INTERVAL = "1k"
_LONG_RUN_PACE_TOLERANCE = 10.0


def _easy_minutes_from_km(target_km: float) -> int:
    """Convert a target distance to an easy-run duration in minutes."""
    return max(_MIN_EASY_MINUTES, round(target_km * _TEMPO_MIN_PER_KM))


def _tempo_minutes(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 15
    if phase is PhaseKind.BUILD:
        return 20 if week <= 8 else 25
    return 25 if phase is PhaseKind.PEAK else 20


def _cruise_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 3
    if phase is PhaseKind.BUILD:
        return 4
    return 5 if phase is PhaseKind.PEAK else 3


def _cruise_minutes(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 4
    if phase is PhaseKind.BUILD:
        return 5
    return 6 if phase is PhaseKind.PEAK else 5


def _track_400_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 5
    if phase is PhaseKind.BUILD:
        return 7
    return 8 if phase is PhaseKind.PEAK else 5


def _track_1k_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.BUILD:
        return 4
    return 5 if phase is PhaseKind.PEAK else 4


def _hill_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 5
    if phase is PhaseKind.BUILD:
        return 7
    return 8 if phase is PhaseKind.PEAK else 6


def _fartlek_cycles(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 5
    if phase is PhaseKind.BUILD:
        return 7
    return 8 if phase is PhaseKind.PEAK else 6


def _format_pace(pair: tuple[str, str] | None) -> tuple[str, str] | None:
    if pair is None:
        return None
    return (pair[0], pair[1])


def long_run_dose(
    recipe: WorkoutRecipe,
    *,
    target_km: float,
    easy_pace_sec_per_km: tuple[float, float] | None,
) -> RecipeParameters:
    """Return the parameters for a long-run recipe.

    Long-run recipes take a distance plus an optional pace range. When
    no easy pace is known, the parameter pace stays ``None`` and the
    recipe produces effort-only descriptions.
    """
    from ..domain.recipes import (
        LongSteadyParameters,
        LongWithFinishParameters,
        LongWithHillSurgesParameters,
        LongWithKickoutsParameters,
    )

    five_k = five_k_from_easy_pace_seconds(easy_pace_sec_per_km)
    if recipe.key == "long.steady":
        return LongSteadyParameters(
            target_km=target_km,
            pace=_format_pace(
                effort_to_pace_range(
                    "10k", five_k, tolerance_seconds_per_km=_LONG_RUN_PACE_TOLERANCE
                )
            ),
        )
    if recipe.key == "long.with_finish":
        return LongWithFinishParameters(
            target_km=target_km,
            pace=_format_pace(
                effort_to_pace_range(
                    "10k", five_k, tolerance_seconds_per_km=_LONG_RUN_PACE_TOLERANCE
                )
            ),
        )
    if recipe.key == "long.with_hill_surges":
        surge_count = 6 if target_km >= 8 else 4
        return LongWithHillSurgesParameters(target_km=target_km, surge_count=surge_count)
    if recipe.key == "long.with_kickouts":
        kick_count = 4 if target_km >= 8 else 3
        kick_minutes = 2 if target_km >= 8 else 1
        return LongWithKickoutsParameters(
            target_km=target_km, kick_count=kick_count, kick_minutes=kick_minutes
        )
    raise ValueError(f"unsupported long-run recipe {recipe.key!r}")


def quality_dose(
    recipe: WorkoutRecipe,
    *,
    week: int,
    phase: PhaseKind,
    easy_pace_sec_per_km: tuple[float, float] | None,
) -> RecipeParameters:
    """Return the parameters for a quality recipe.

    Quality recipes take a rep/minute count plus a pace range derived
    from the easy pace via the effort converter. When no easy pace is
    known, the parameter pace is ``None`` and the underlying step
    builder is expected to drop the pace field.
    """
    from ..domain.recipes import (
        ContinuousTempoParameters,
        CruiseIntervalsParameters,
        FartlekParameters,
        HillRepeatsParameters,
        Track1kParameters,
        Track400mParameters,
    )

    five_k = five_k_from_easy_pace_seconds(easy_pace_sec_per_km)
    tempo_pace = _format_pace(effort_to_pace_range(_FIVE_K_EFFORT_FOR_TEMPO, five_k))
    interval_pace = _format_pace(effort_to_pace_range(_FIVE_K_EFFORT_FOR_INTERVAL, five_k))

    if recipe.key == "tempo.continuous":
        return ContinuousTempoParameters(minutes=_tempo_minutes(week, phase), pace=tempo_pace)
    if recipe.key == "tempo.cruise_intervals":
        return CruiseIntervalsParameters(
            reps=_cruise_reps(week, phase),
            rep_minutes=_cruise_minutes(week, phase),
            pace=tempo_pace,
        )
    if recipe.key == "interval.track_400m":
        return Track400mParameters(reps=_track_400_reps(week, phase), pace=interval_pace)
    if recipe.key == "interval.track_1k":
        if week <= 3:
            return ContinuousTempoParameters(
                minutes=_tempo_minutes(week, phase),
                pace=tempo_pace,
            )
        return Track1kParameters(reps=_track_1k_reps(week, phase), pace=interval_pace)
    if recipe.key == "interval.hill_repeats":
        return HillRepeatsParameters(reps=_hill_reps(week, phase), effort_seconds=60)
    if recipe.key == "interval.fartlek":
        return FartlekParameters(
            cycles=_fartlek_cycles(week, phase), hard_minutes=2, easy_minutes=1
        )
    raise ValueError(f"unsupported quality recipe {recipe.key!r}")


def easy_dose(
    recipe: WorkoutRecipe,
    *,
    target_km: float,
) -> RecipeParameters:
    """Return the parameters for an easy recipe.

    Easy recipes that target a very short distance collapse to a
    recovery run; longer distances stay aerobic. The ``target_km`` cap
    matches the placement branch that previously distinguished a
    recovery run from an easy run.
    """
    from ..domain.recipes import (
        EasyContinuousParameters,
        EasyWithStridesParameters,
        RecoveryDistanceParameters,
        RecoveryRunParameters,
        WarmupRunParameters,
    )

    if recipe.key == "easy.continuous":
        return EasyContinuousParameters(minutes=_easy_minutes_from_km(target_km))
    if recipe.key == "easy.with_strides":
        return EasyWithStridesParameters(minutes=_easy_minutes_from_km(target_km))
    if recipe.key == "easy.warmup_run":
        return WarmupRunParameters(minutes=_easy_minutes_from_km(target_km))
    if recipe.key == "recovery.run":
        minutes = max(15, _easy_minutes_from_km(target_km))
        return RecoveryRunParameters(minutes=minutes)
    if recipe.key == "recovery.distance":
        return RecoveryDistanceParameters(target_km=target_km)
    raise ValueError(f"unsupported easy recipe {recipe.key!r}")


def build_dose(
    recipe: WorkoutRecipe,
    *,
    form: WorkoutForm,
    week: int,
    phase: PhaseKind,
    target_km: float,
    easy_pace_sec_per_km: tuple[float, float] | None,
    **_unused: Any,
) -> RecipeParameters:
    """Dispatch to the correct dose helper based on the recipe's form."""
    if form.name == "long_run":
        return long_run_dose(recipe, target_km=target_km, easy_pace_sec_per_km=easy_pace_sec_per_km)
    if form.name in {"tempo_run", "interval_workout"}:
        return quality_dose(
            recipe,
            week=week,
            phase=phase,
            easy_pace_sec_per_km=easy_pace_sec_per_km,
        )
    if form.name == "easy_run":
        return easy_dose(recipe, target_km=target_km)
    if form.name == "recovery_run":
        return easy_dose(recipe, target_km=target_km)
    raise ValueError(f"no dose helper for form {form.name!r}")
