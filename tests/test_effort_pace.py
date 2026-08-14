"""Tests for the effort-to-pace converter used by the recipe-aware generator."""

from __future__ import annotations

import pytest

from runplan.domain.pace import (
    PACE_INTENSITIES,
    TRAINING_INTENSITY_OFFSETS,
    intensity_pace_seconds,
    race_pace_seconds,
)
from runplan.generation.effort_pace import (
    EFFORT_LABELS,
    effort_to_pace_range,
    five_k_from_easy_pace_seconds,
    pace_range_to_effort,
)


def test_effort_labels_cover_all_supported_intensities() -> None:
    assert set(EFFORT_LABELS) == set(PACE_INTENSITIES) | set(TRAINING_INTENSITY_OFFSETS)


def test_effort_to_pace_range_uses_intensity_table_for_race_distances() -> None:
    five_k = 25 * 60
    pair = effort_to_pace_range("5k", five_k)
    assert pair is not None
    target = race_pace_seconds(five_k, 5.0)
    assert _parse(pair[0]) <= target <= _parse(pair[1])


def test_effort_to_pace_range_uses_intensity_table_for_training_offsets() -> None:
    five_k = 25 * 60
    pair = effort_to_pace_range("tempo", five_k)
    assert pair is not None
    target = intensity_pace_seconds(five_k, "tempo")
    assert _parse(pair[0]) <= target <= _parse(pair[1])


def test_effort_to_pace_range_returns_none_without_5k_time() -> None:
    assert effort_to_pace_range("tempo", None) is None
    assert effort_to_pace_range("tempo", 0) is None
    assert effort_to_pace_range("tempo", -1) is None


def test_effort_to_pace_range_returns_none_for_unknown_label() -> None:
    assert effort_to_pace_range("sprint", 1500) is None


def test_effort_to_pace_range_tolerance_widens_zone() -> None:
    narrow = effort_to_pace_range("tempo", 1500, tolerance_seconds_per_km=0)
    wide = effort_to_pace_range("tempo", 1500, tolerance_seconds_per_km=60)
    assert narrow is not None and wide is not None
    assert _parse(narrow[1]) - _parse(narrow[0]) < _parse(wide[1]) - _parse(wide[0])


def test_effort_to_pace_range_writes_mmss_strings() -> None:
    fast, slow = effort_to_pace_range("10k", 25 * 60)
    assert fast is not None and slow is not None
    assert ":" in fast and ":" in slow
    assert fast.startswith("4:") or fast.startswith("5:")


def test_pace_range_round_trips_to_same_effort() -> None:
    five_k = 25 * 60
    for label in EFFORT_LABELS:
        pair = effort_to_pace_range(label, five_k)
        assert pair is not None, f"no range for {label}"
        back = pace_range_to_effort(_parse(pair[0]), _parse(pair[1]), five_k)
        assert back == label, f"{label} -> {pair} -> {back}"


def test_pace_range_to_effort_rejects_invalid_inputs() -> None:
    assert pace_range_to_effort(0, 300, 1500) is None
    assert pace_range_to_effort(300, 0, 1500) is None
    assert pace_range_to_effort(400, 300, 1500) is None
    assert pace_range_to_effort(300, 400, 0) is None


def test_pace_range_to_effort_prefers_training_intensity_offsets() -> None:
    five_k = 1500
    tempo_pair = effort_to_pace_range("tempo", five_k)
    assert tempo_pair is not None
    back = pace_range_to_effort(_parse(tempo_pair[0]), _parse(tempo_pair[1]), five_k)
    assert back == "tempo"


def test_five_k_from_easy_pace_seconds_handles_scalar_and_pair() -> None:
    assert five_k_from_easy_pace_seconds(None) is None
    assert five_k_from_easy_pace_seconds(0) is None
    assert five_k_from_easy_pace_seconds(-1) is None
    single = five_k_from_easy_pace_seconds(300)
    pair = five_k_from_easy_pace_seconds((300, 320))
    assert single is not None and pair is not None
    assert single == pytest.approx(pair)


def test_five_k_from_easy_pace_seconds_uses_first_endpoint_of_pair() -> None:
    fast_only = five_k_from_easy_pace_seconds(300)
    slow_only = five_k_from_easy_pace_seconds(360)
    assert fast_only is not None and slow_only is not None
    assert fast_only < slow_only


def _parse(value: str) -> int:
    minute, second = value.split(":")
    return int(minute) * 60 + int(second)
