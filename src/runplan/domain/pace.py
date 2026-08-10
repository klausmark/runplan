"""Race pace calculations derived from a 5K best time.

The model is a single source of truth for pace-chart values, training
intensities, and Garmin target zones. It encodes Riegel's formula with the
commonly accepted exponent of 1.07 plus two training-intensity rules from
Nike Run Club coaching:

* Tempo pace is roughly 20 seconds per kilometer slower than 5K pace.
* Recovery pace is roughly 60 seconds per kilometer slower than 5K pace.

All public functions return seconds per kilometer. Display formatting lives
in ``format_pace_seconds``.
"""

from __future__ import annotations

import math
from collections.abc import Mapping

# Riegel's fatigue exponent. 1.06 is the historical Riegel value; 1.07 is
# the empirically observed average across modern runners and matches the
# Nike Run Club pace chart within a few seconds per kilometer.
RIEGEL_EXPONENT = 1.07

# Reference distances in kilometers.
ONE_KM = 1.0
FIVE_KM = 5.0
TEN_KM = 10.0
HALF_MARATHON_KM = 21.0975
MARATHON_KM = 42.195

# Fixed offsets (seconds per kilometer) above 5K pace for the standard
# training intensities defined in the Nike Run Club pace types.
TEMPO_OFFSET_SECONDS_PER_KM = 20
RECOVERY_OFFSET_SECONDS_PER_KM = 60

PACE_INTENSITIES: Mapping[str, float] = {
    "1k": ONE_KM,
    "5k": FIVE_KM,
    "10k": TEN_KM,
    "half-marathon": HALF_MARATHON_KM,
    "marathon": MARATHON_KM,
}

TRAINING_INTENSITY_OFFSETS: Mapping[str, int] = {
    "tempo": TEMPO_OFFSET_SECONDS_PER_KM,
    "recovery": RECOVERY_OFFSET_SECONDS_PER_KM,
}

KM_PER_MILE = 1.609344


def five_k_pace_seconds(five_k_seconds: float) -> float:
    """Return the average 5K pace in seconds per kilometer."""
    if five_k_seconds <= 0:
        raise ValueError("five_k_seconds must be greater than 0")
    return five_k_seconds / FIVE_KM


def race_pace_seconds(five_k_seconds: float, distance_km: float) -> float:
    """Predict the average race pace for ``distance_km`` from a 5K time.

    Uses Riegel's formula with exponent 1.07 and rounds to the nearest
    five seconds to match the precision of Nike Run Club pace charts.
    """
    if distance_km <= 0:
        raise ValueError("distance_km must be greater than 0")
    ratio = distance_km / FIVE_KM
    time = five_k_seconds * math.pow(ratio, RIEGEL_EXPONENT)
    return round5(time / distance_km)


def intensity_pace_seconds(five_k_seconds: float, intensity: str) -> float:
    """Return the pace in seconds per kilometer for a symbolic intensity.

    Supported symbolic intensities: ``1k``, ``5k``, ``10k``, ``tempo``,
    ``half-marathon``, ``marathon``, ``recovery``. The race-paced
    intensities use Riegel's formula; tempo and recovery add a fixed offset
    to the 5K pace.
    """
    if intensity in PACE_INTENSITIES:
        return race_pace_seconds(five_k_seconds, PACE_INTENSITIES[intensity])
    if intensity in TRAINING_INTENSITY_OFFSETS:
        base = five_k_pace_seconds(five_k_seconds)
        return round5(base + TRAINING_INTENSITY_OFFSETS[intensity])
    raise ValueError(f"unknown pace intensity: {intensity!r}")


def pace_zone(
    five_k_seconds: float,
    intensity: str,
    *,
    tolerance_seconds_per_km: float = 5.0,
) -> tuple[float, float]:
    """Return a (fast, slow) Garmin-style pace zone for an intensity.

    ``tolerance_seconds_per_km`` widens or narrows the zone symmetrically
    around the target pace. A value of zero produces a fixed target; a
    negative value is treated as zero.
    """
    target = intensity_pace_seconds(five_k_seconds, intensity)
    width = max(0.0, float(tolerance_seconds_per_km))
    fast = round5(target - width)
    slow = round5(target + width)
    if fast <= 0:
        fast = round5(target)
        slow = round5(target + width * 2)
    return fast, slow


def round5(seconds: float) -> int:
    """Round seconds to the nearest five, the chart's display granularity."""
    return int(round(seconds / 5.0) * 5)


def format_pace_seconds(seconds: float) -> str:
    """Render seconds per kilometer as ``M:SS``."""
    total = int(round(seconds))
    minutes, remainder = divmod(total, 60)
    return f"{minutes}:{remainder:02d}"


def parse_total_seconds(value: str) -> int:
    """Parse ``H:MM:SS`` or ``M:SS`` race totals into seconds."""
    parts = value.strip().split(":")
    if not parts or not all(part.isdigit() for part in parts):
        raise ValueError(f"invalid total time {value!r}; use H:MM:SS or M:SS")
    numbers = [int(part) for part in parts]
    if len(numbers) == 2:
        minutes, seconds = numbers
        if seconds >= 60:
            raise ValueError(f"invalid total time {value!r}; seconds must be < 60")
        total = minutes * 60 + seconds
    elif len(numbers) == 3:
        hours, minutes, seconds = numbers
        if minutes >= 60 or seconds >= 60:
            raise ValueError(f"invalid total time {value!r}; minutes/seconds must be < 60")
        total = hours * 3600 + minutes * 60 + seconds
    else:
        raise ValueError(f"invalid total time {value!r}; use H:MM:SS or M:SS")
    if total <= 0:
        raise ValueError(f"invalid total time {value!r}; must be greater than 0")
    return total


def total_from_pace(pace_seconds_per_km: float, distance_km: float) -> int:
    """Return a race total in seconds for the given pace and distance."""
    if distance_km <= 0:
        raise ValueError("distance_km must be greater than 0")
    return int(round(pace_seconds_per_km * distance_km))


__all__ = [
    "FIVE_KM",
    "HALF_MARATHON_KM",
    "KM_PER_MILE",
    "MARATHON_KM",
    "ONE_KM",
    "PACE_INTENSITIES",
    "RECOVERY_OFFSET_SECONDS_PER_KM",
    "RIEGEL_EXPONENT",
    "TEMPO_OFFSET_SECONDS_PER_KM",
    "TEN_KM",
    "TRAINING_INTENSITY_OFFSETS",
    "five_k_pace_seconds",
    "format_pace_seconds",
    "intensity_pace_seconds",
    "pace_zone",
    "parse_total_seconds",
    "race_pace_seconds",
    "round5",
    "total_from_pace",
]
