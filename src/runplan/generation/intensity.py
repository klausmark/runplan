"""Intensity target calculation.

The generator uses a soft pyramidal distribution inspired by the 92-plan
analysis by Knopp et al. (2024, PMID 38695978). The exact share per week
fluctuates with the workload profile, but the share of Zone 1-2 work stays
between 70% and 85% of the total weekly volume.
"""

from __future__ import annotations

from dataclasses import dataclass

from .phase import PhaseKind


@dataclass(frozen=True, slots=True)
class IntensityTarget:
    """The expected zone distribution for a single week."""

    zone1_pct: float
    zone2_pct: float
    zone3_pct: float
    zone4_pct: float
    zone5_pct: float

    def as_dict(self) -> dict[str, float]:
        return {
            "zone1": self.zone1_pct,
            "zone2": self.zone2_pct,
            "zone3": self.zone3_pct,
            "zone4": self.zone4_pct,
            "zone5": self.zone5_pct,
        }


def target_for_phase(phase: PhaseKind, recovery_week: bool) -> IntensityTarget:
    """Return the intensity target for a week in a given phase."""
    if recovery_week:
        return IntensityTarget(0.18, 0.70, 0.10, 0.01, 0.01)
    if phase is PhaseKind.FOUNDATION:
        return IntensityTarget(0.17, 0.66, 0.14, 0.02, 0.01)
    if phase is PhaseKind.BUILD:
        return IntensityTarget(0.14, 0.62, 0.18, 0.04, 0.02)
    if phase is PhaseKind.PEAK:
        return IntensityTarget(0.13, 0.58, 0.20, 0.06, 0.03)
    return IntensityTarget(0.20, 0.65, 0.12, 0.02, 0.01)


def summarise_targets(targets: tuple[IntensityTarget, ...]) -> IntensityTarget:
    """Return the average across all weekly targets."""
    if not targets:
        return IntensityTarget(0.0, 0.0, 0.0, 0.0, 0.0)
    n = len(targets)
    return IntensityTarget(
        zone1_pct=sum(t.zone1_pct for t in targets) / n,
        zone2_pct=sum(t.zone2_pct for t in targets) / n,
        zone3_pct=sum(t.zone3_pct for t in targets) / n,
        zone4_pct=sum(t.zone4_pct for t in targets) / n,
        zone5_pct=sum(t.zone5_pct for t in targets) / n,
    )


__all__ = ["IntensityTarget", "summarise_targets", "target_for_phase"]
