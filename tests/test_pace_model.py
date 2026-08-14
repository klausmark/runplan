"""Tests for the central race pace model."""

from __future__ import annotations

import math

import pytest

from runplan.domain import (
    FIVE_KM,
    HALF_MARATHON_KM,
    MARATHON_KM,
    PACE_INTENSITIES,
    RECOVERY_OFFSET_SECONDS_PER_KM,
    RIEGEL_EXPONENT,
    TEMPO_OFFSET_SECONDS_PER_KM,
    TEN_KM,
    easy_pace_to_five_k_seconds,
    five_k_pace_seconds,
    format_pace_seconds,
    intensity_pace_seconds,
    one_k_pace_to_five_k_seconds,
    pace_zone,
    parse_total_seconds,
    race_pace_seconds,
    round5,
    total_from_pace,
)


def test_five_k_pace_seconds_returns_per_kilometer_average() -> None:
    assert five_k_pace_seconds(1500) == 300  # 25:00 5K -> 5:00 min/km


def test_race_pace_seconds_matches_riegel_for_5k() -> None:
    # Riegel with exponent 1.07 collapses to 5K pace at the 5K reference.
    assert race_pace_seconds(1500, FIVE_KM) == 300


def test_race_pace_seconds_slows_for_longer_distances() -> None:
    five_k = 1500  # 5:00 min/km
    p5k = race_pace_seconds(five_k, FIVE_KM)
    p10k = race_pace_seconds(five_k, TEN_KM)
    pHalf = race_pace_seconds(five_k, HALF_MARATHON_KM)
    pFull = race_pace_seconds(five_k, MARATHON_KM)
    assert p5k < p10k < pHalf < pFull


def test_race_pace_seconds_matches_expected_riegel_values() -> None:
    five_k = 25 * 60  # 25:00
    # 10K with Riegel 1.07 = 5K * (10/5)^1.07 / 10
    expected_10k = round5(five_k * math.pow(2.0, RIEGEL_EXPONENT) / 10.0)
    assert race_pace_seconds(five_k, TEN_KM) == expected_10k


def test_intensity_pace_uses_riegel_for_race_distances() -> None:
    five_k = 25 * 60
    for label in PACE_INTENSITIES:
        assert intensity_pace_seconds(five_k, label) == race_pace_seconds(
            five_k, PACE_INTENSITIES[label]
        )


def test_intensity_pace_adds_fixed_offset_for_tempo_and_recovery() -> None:
    five_k_seconds = 1500  # 5:00 min/km
    base = five_k_pace_seconds(five_k_seconds)
    assert intensity_pace_seconds(five_k_seconds, "tempo") == round5(
        base + TEMPO_OFFSET_SECONDS_PER_KM
    )
    assert intensity_pace_seconds(five_k_seconds, "recovery") == round5(
        base + RECOVERY_OFFSET_SECONDS_PER_KM
    )


def test_intensity_pace_rejects_unknown_intensity() -> None:
    with pytest.raises(ValueError, match="unknown pace intensity"):
        intensity_pace_seconds(1500, "sprint")


def test_pace_zone_default_tolerance_is_five_seconds_per_kilometer() -> None:
    fast, slow = pace_zone(1500, "5k")
    assert slow - fast == 10
    assert fast < slow


def test_pace_zone_zero_tolerance_returns_fixed_target() -> None:
    target = intensity_pace_seconds(1500, "5k")
    fast, slow = pace_zone(1500, "5k", tolerance_seconds_per_km=0)
    assert fast == target == slow


def test_pace_zone_floor_clamps_to_positive_pace() -> None:
    # A very large tolerance with a very fast 5K should not produce a
    # non-positive fast pace.
    fast, slow = pace_zone(900, "5k", tolerance_seconds_per_km=120)
    assert fast > 0
    assert slow >= fast


def test_round5_rounds_to_nearest_five_seconds() -> None:
    assert round5(0) == 0
    assert round5(2) == 0
    assert round5(3) == 5
    assert round5(297) == 295
    assert round5(298) == 300


def test_format_pace_seconds_renders_minutes_and_seconds() -> None:
    assert format_pace_seconds(60) == "1:00"
    assert format_pace_seconds(305) == "5:05"
    assert format_pace_seconds(5 * 60 + 25) == "5:25"


def test_parse_total_seconds_supports_minutes_and_hours() -> None:
    assert parse_total_seconds("25:00") == 1500
    assert parse_total_seconds("1:18:00") == 4680
    assert parse_total_seconds("1:05:30") == 3930


def test_parse_total_seconds_rejects_invalid_input() -> None:
    with pytest.raises(ValueError):
        parse_total_seconds("5:60")
    with pytest.raises(ValueError):
        parse_total_seconds("0:00")
    with pytest.raises(ValueError):
        parse_total_seconds("not a time")


def test_total_from_pace_round_trips_with_known_pace() -> None:
    pace = 5 * 60 + 25  # 5:25 min/km
    total = total_from_pace(pace, FIVE_KM)
    assert total == round(pace * 5)


def test_race_pace_seconds_rejects_non_positive_distance() -> None:
    with pytest.raises(ValueError):
        race_pace_seconds(1500, 0)
    with pytest.raises(ValueError):
        race_pace_seconds(1500, -1)


def test_five_k_pace_seconds_rejects_non_positive_input() -> None:
    with pytest.raises(ValueError):
        five_k_pace_seconds(0)
    with pytest.raises(ValueError):
        five_k_pace_seconds(-1)


def test_one_k_pace_to_five_k_seconds_matches_riegel() -> None:
    # A 3:00 min/km 1K best predicts a 5K time longer than 15:00 because the
    # runner cannot sustain 1K pace over the full 5K.
    assert one_k_pace_to_five_k_seconds(180) == pytest.approx(180 * math.pow(5.0, RIEGEL_EXPONENT))
    # Round-trip: a 1K best of 5:00 implies a 5K around 27:00 at Riegel 1.07.
    assert one_k_pace_to_five_k_seconds(300) == pytest.approx(300 * math.pow(5.0, RIEGEL_EXPONENT))


def test_one_k_pace_to_five_k_seconds_rejects_non_positive_input() -> None:
    with pytest.raises(ValueError):
        one_k_pace_to_five_k_seconds(0)
    with pytest.raises(ValueError):
        one_k_pace_to_five_k_seconds(-1)


def test_easy_pace_to_five_k_seconds_inverts_riegel_for_10k_assumption() -> None:
    # Easy pace ~ 10K race pace, so the implied 5K time should match the
    # Riegel inversion: five_k_time = (easy_pace * 10) / (10/5)^RIEGEL_EXPONENT
    easy_pace = 5 * 60 + 25  # 5:25 min/km
    expected = easy_pace * TEN_KM / math.pow(TEN_KM / FIVE_KM, RIEGEL_EXPONENT)
    assert easy_pace_to_five_k_seconds(easy_pace) == pytest.approx(expected)


def test_easy_pace_to_five_k_seconds_routes_through_riegel() -> None:
    # The resulting 5K time, fed back into race_pace_seconds for 10K, gives the
    # original easy pace within the chart's 5s granularity.
    easy_pace = 5 * 60 + 25
    five_k = easy_pace_to_five_k_seconds(easy_pace)
    ten_k_pace = race_pace_seconds(five_k, TEN_KM)
    assert abs(ten_k_pace - easy_pace) <= 5


def test_easy_pace_to_five_k_seconds_rejects_non_positive_input() -> None:
    with pytest.raises(ValueError):
        easy_pace_to_five_k_seconds(0)
    with pytest.raises(ValueError):
        easy_pace_to_five_k_seconds(-1)
