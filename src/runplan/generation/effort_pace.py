"""Effort-to-pace conversion for the first 10K generator.

Step 9 introduces a converter between the symbolic effort/intensity
vocabulary (for example ``tempo`` or ``1k``) and the numeric pace ranges
used by the recipe catalogue. The forward direction builds a
``(fast, slow)`` pace range in ``M:SS`` strings from a known 5K time; the
reverse direction maps a resolved pace range back to the closest effort
symbol so the UI can render the runner-facing label.

The converter is the single bridge between the central pace model in
``runplan.domain.pace`` and the recipe-aware generator. Keeping it in
``generation/`` reflects its role as a generator adapter; the underlying
table lives in the domain.
"""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.pace import (
    PACE_INTENSITIES,
    TRAINING_INTENSITY_OFFSETS,
    easy_pace_to_five_k_seconds,
    format_pace_seconds,
    intensity_pace_seconds,
    pace_zone,
)

__all__ = [
    "EFFORT_LABELS",
    "ZERO_PACE",
    "effort_to_pace_range",
    "five_k_from_easy_pace_seconds",
    "pace_range_to_effort",
]


EFFORT_LABELS: tuple[str, ...] = (
    *TRAINING_INTENSITY_OFFSETS.keys(),
    *PACE_INTENSITIES.keys(),
)
"""All effort symbols the converter understands, in stable order.

Training-intensity offsets come first so a tempo or recovery workout does
not collide with a nearby race-distance symbol in reverse lookups.
"""

_DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM = 10.0
_EFFORT_MATCH_TOLERANCE_SECONDS_PER_KM = 4.0

ZERO_PACE = "0:00"
"""Sentinel pace string used when the converter has no data to produce one."""


def five_k_from_easy_pace_seconds(easy_pace_sec_per_km: float | None) -> float | None:
    """Return the implied 5K time from a known easy pace, or None.

    The bridge lets callers supply an ``(fast, slow)`` easy pace pair
    (matching the CLI's ``--known-easy-pace`` semantics). When the slow
    endpoint is unknown only the fast endpoint is used; when both are
    absent, no 5K time is computed.
    """
    if easy_pace_sec_per_km is None:
        return None
    if isinstance(easy_pace_sec_per_km, (tuple, list)):
        if not easy_pace_sec_per_km:
            return None
        first = easy_pace_sec_per_km[0]
    else:
        first = easy_pace_sec_per_km
    if first is None or first <= 0:
        return None
    return easy_pace_to_five_k_seconds(first)


def effort_to_pace_range(
    effort: str,
    known_5k_seconds: float | None,
    *,
    tolerance_seconds_per_km: float = _DEFAULT_PACE_TOLERANCE_SECONDS_PER_KM,
) -> tuple[str, str] | None:
    """Return a ``(fast, slow)`` pace range for ``effort`` in ``M:SS`` strings.

    ``effort`` is any label accepted by ``runplan.domain.pace``:
    ``1k``, ``5k``, ``10k``, ``half-marathon``, ``marathon``, ``tempo``,
    ``recovery``. ``known_5k_seconds`` is the runner's reference 5K
    race time; when absent the function returns ``None`` so the caller
    can fall back to effort-only descriptions.

    ``tolerance_seconds_per_km`` widens or narrows the produced range
    symmetrically around the target pace. The default of ten seconds
    matches the chart's display granularity.
    """
    if known_5k_seconds is None or known_5k_seconds <= 0:
        return None
    if effort not in EFFORT_LABELS:
        return None
    fast, slow = pace_zone(
        known_5k_seconds, effort, tolerance_seconds_per_km=tolerance_seconds_per_km
    )
    return format_pace_seconds(fast), format_pace_seconds(slow)


def pace_range_to_effort(
    fast_seconds: float,
    slow_seconds: float,
    known_5k_seconds: float,
    *,
    tolerance_seconds_per_km: float = _EFFORT_MATCH_TOLERANCE_SECONDS_PER_KM,
) -> str | None:
    """Return the effort symbol closest to ``(fast, slow)`` pace seconds.

    The reverse lookup is useful when the UI shows a resolved pace range
    alongside the runner-facing effort label. ``known_5k_seconds``
    anchors the comparison so the same pace range always maps back to
    the same symbol; the tolerance matches the default forward-zone
    width so a pace produced by :func:`effort_to_pace_range` round-trips
    back to the same symbol.
    """
    if (
        known_5k_seconds <= 0
        or fast_seconds <= 0
        or slow_seconds <= 0
        or slow_seconds < fast_seconds
    ):
        return None
    mid_seconds = (fast_seconds + slow_seconds) / 2
    best: tuple[float, str] | None = None
    for label in EFFORT_LABELS:
        target = intensity_pace_seconds(known_5k_seconds, label)
        diff = abs(target - mid_seconds)
        if best is None or diff < best[0]:
            best = (diff, label)
        if diff <= tolerance_seconds_per_km:
            return label
    return best[1] if best is not None else None


def _candidate_efforts() -> Iterable[str]:
    """Order effort candidates for reverse lookup.

    Training-intensity offsets come first because the generator uses
    ``tempo`` and ``recovery`` more often than the race distances.
    """
    yield from TRAINING_INTENSITY_OFFSETS
    yield from PACE_INTENSITIES
