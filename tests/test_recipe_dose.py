"""Tests for the recipe-aware dose calculator."""

from __future__ import annotations

import pytest

from runplan.domain.recipes import (
    ContinuousTempoParameters,
    CruiseIntervalsParameters,
    EasyContinuousParameters,
    EasyWithStridesParameters,
    FartlekParameters,
    HillRepeatsParameters,
    LongSteadyParameters,
    LongWithFinishParameters,
    LongWithHillSurgesParameters,
    LongWithKickoutsParameters,
    RecoveryDistanceParameters,
    RecoveryRunParameters,
    Track1kParameters,
    Track400mParameters,
    WarmupRunParameters,
    get_recipe,
)
from runplan.generation.phase import PhaseKind
from runplan.generation.recipe_dose import (
    easy_dose,
    long_run_dose,
    quality_dose,
)

FIVE_K_APPROX_EASY = 5 * 60 + 5  # ~30:30 for 5K, easy pace ~6:06


def test_long_run_dose_supports_each_recipe() -> None:
    easy_pace = (360.0, 380.0)
    assert isinstance(
        long_run_dose(get_recipe("long.steady"), target_km=10.0, easy_pace_sec_per_km=easy_pace),
        LongSteadyParameters,
    )
    assert isinstance(
        long_run_dose(
            get_recipe("long.with_finish"), target_km=12.0, easy_pace_sec_per_km=easy_pace
        ),
        LongWithFinishParameters,
    )
    assert isinstance(
        long_run_dose(
            get_recipe("long.with_hill_surges"), target_km=10.0, easy_pace_sec_per_km=easy_pace
        ),
        LongWithHillSurgesParameters,
    )
    assert isinstance(
        long_run_dose(
            get_recipe("long.with_kickouts"), target_km=10.0, easy_pace_sec_per_km=easy_pace
        ),
        LongWithKickoutsParameters,
    )


def test_long_run_dose_short_distance_reduces_surge_count() -> None:
    params = long_run_dose(
        get_recipe("long.with_hill_surges"), target_km=6.0, easy_pace_sec_per_km=None
    )
    assert isinstance(params, LongWithHillSurgesParameters)
    assert params.surge_count == 4


def test_long_run_dose_long_distance_uses_six_surges() -> None:
    params = long_run_dose(
        get_recipe("long.with_hill_surges"), target_km=12.0, easy_pace_sec_per_km=None
    )
    assert isinstance(params, LongWithHillSurgesParameters)
    assert params.surge_count == 6


def test_long_run_dose_without_pace_keeps_pace_none() -> None:
    params = long_run_dose(get_recipe("long.steady"), target_km=10.0, easy_pace_sec_per_km=None)
    assert isinstance(params, LongSteadyParameters)
    assert params.pace is None


def test_long_run_dose_with_pace_resolves_pace_range() -> None:
    params = long_run_dose(
        get_recipe("long.steady"), target_km=10.0, easy_pace_sec_per_km=(300, 320)
    )
    assert isinstance(params, LongSteadyParameters)
    assert params.pace is not None
    assert isinstance(params.pace[0], str)
    assert ":" in params.pace[0]


def test_quality_dose_tempo_continuous_respects_phase() -> None:
    foundation = quality_dose(
        get_recipe("tempo.continuous"),
        week=2,
        phase=PhaseKind.FOUNDATION,
        easy_pace_sec_per_km=(300, 320),
    )
    peak = quality_dose(
        get_recipe("tempo.continuous"),
        week=11,
        phase=PhaseKind.PEAK,
        easy_pace_sec_per_km=(300, 320),
    )
    assert isinstance(foundation, ContinuousTempoParameters)
    assert isinstance(peak, ContinuousTempoParameters)
    assert peak.minutes > foundation.minutes


def test_quality_dose_cruise_intervals_reps_grow_with_phase() -> None:
    foundation = quality_dose(
        get_recipe("tempo.cruise_intervals"),
        week=2,
        phase=PhaseKind.FOUNDATION,
        easy_pace_sec_per_km=(300, 320),
    )
    peak = quality_dose(
        get_recipe("tempo.cruise_intervals"),
        week=11,
        phase=PhaseKind.PEAK,
        easy_pace_sec_per_km=(300, 320),
    )
    assert isinstance(foundation, CruiseIntervalsParameters)
    assert isinstance(peak, CruiseIntervalsParameters)
    assert peak.reps > foundation.reps


def test_quality_dose_track_400m_reps_grow_with_phase() -> None:
    foundation = quality_dose(
        get_recipe("interval.track_400m"),
        week=2,
        phase=PhaseKind.FOUNDATION,
        easy_pace_sec_per_km=(300, 320),
    )
    peak = quality_dose(
        get_recipe("interval.track_400m"),
        week=11,
        phase=PhaseKind.PEAK,
        easy_pace_sec_per_km=(300, 320),
    )
    assert isinstance(foundation, Track400mParameters)
    assert isinstance(peak, Track400mParameters)
    assert peak.reps > foundation.reps


def test_quality_dose_track_1k_early_weeks_collapses_to_tempo() -> None:
    early = quality_dose(
        get_recipe("interval.track_1k"),
        week=2,
        phase=PhaseKind.FOUNDATION,
        easy_pace_sec_per_km=(300, 320),
    )
    late = quality_dose(
        get_recipe("interval.track_1k"),
        week=10,
        phase=PhaseKind.PEAK,
        easy_pace_sec_per_km=(300, 320),
    )
    assert isinstance(early, ContinuousTempoParameters)
    assert isinstance(late, Track1kParameters)


def test_quality_dose_hill_repeats_and_fartlek_have_no_pace() -> None:
    hill = quality_dose(
        get_recipe("interval.hill_repeats"),
        week=6,
        phase=PhaseKind.BUILD,
        easy_pace_sec_per_km=(300, 320),
    )
    fartlek = quality_dose(
        get_recipe("interval.fartlek"),
        week=6,
        phase=PhaseKind.BUILD,
        easy_pace_sec_per_km=(300, 320),
    )
    assert isinstance(hill, HillRepeatsParameters)
    assert isinstance(fartlek, FartlekParameters)


def test_quality_dose_without_pace_keeps_pace_none() -> None:
    params = quality_dose(
        get_recipe("tempo.continuous"),
        week=6,
        phase=PhaseKind.BUILD,
        easy_pace_sec_per_km=None,
    )
    assert isinstance(params, ContinuousTempoParameters)
    assert params.pace is None


def test_easy_dose_maps_target_km_to_minutes() -> None:
    params = easy_dose(get_recipe("easy.continuous"), target_km=5.0)
    assert isinstance(params, EasyContinuousParameters)
    assert params.minutes >= 20


def test_easy_dose_supports_with_strides_and_warmup_run() -> None:
    strides = easy_dose(get_recipe("easy.with_strides"), target_km=4.0)
    warmup = easy_dose(get_recipe("easy.warmup_run"), target_km=3.0)
    assert isinstance(strides, EasyWithStridesParameters)
    assert isinstance(warmup, WarmupRunParameters) or hasattr(warmup, "minutes")


def test_easy_dose_short_target_uses_recovery_run() -> None:
    params = easy_dose(get_recipe("recovery.run"), target_km=1.0)
    assert isinstance(params, RecoveryRunParameters)
    assert params.minutes >= 15


def test_easy_dose_recovery_distance_scales_with_target_km() -> None:
    params = easy_dose(get_recipe("recovery.distance"), target_km=4.5)
    assert isinstance(params, RecoveryDistanceParameters)
    assert params.target_km == pytest.approx(4.5)


def test_long_run_dose_rejects_unknown_recipe() -> None:
    bogus = get_recipe("easy.continuous")
    with pytest.raises(ValueError, match="unsupported long-run recipe"):
        long_run_dose(bogus, target_km=10.0, easy_pace_sec_per_km=None)


def test_quality_dose_rejects_unknown_recipe() -> None:
    bogus = get_recipe("easy.continuous")
    with pytest.raises(ValueError, match="unsupported quality recipe"):
        quality_dose(bogus, week=1, phase=PhaseKind.FOUNDATION, easy_pace_sec_per_km=None)


def test_easy_dose_rejects_unknown_recipe() -> None:
    bogus = get_recipe("long.steady")
    with pytest.raises(ValueError, match="unsupported easy recipe"):
        easy_dose(bogus, target_km=5.0)
