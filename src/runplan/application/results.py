"""Serializable results returned by application use cases."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Literal


SyncActionKind = Literal[
    "create",
    "update",
    "reuse",
    "schedule",
    "already_scheduled",
    "unschedule",
    "delete",
    "completed",
    "missed",
    "retired",
]


@dataclass(frozen=True, slots=True)
class SyncAction:
    kind: SyncActionKind
    name: str
    workout_id: int | None = None
    schedule_id: int | None = None
    date: str | None = None
    activity_id: int | None = None
    completed_at: str | None = None
    actual_distance_meters: float | None = None
    actual_duration_seconds: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {key: value for key, value in asdict(self).items() if value is not None}


@dataclass(slots=True)
class SyncResult:
    program_id: str
    week: int
    actions: list[SyncAction] = field(default_factory=list)

    def add(self, kind: SyncActionKind, name: str, **values: Any) -> None:
        self.actions.append(SyncAction(kind=kind, name=name, **values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "programId": self.program_id,
            "week": self.week,
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(slots=True)
class SyncPlan:
    """Read-only synchronization diff for selected program weeks."""

    program_id: str
    weeks: tuple[int, ...]
    actions: list[SyncAction] = field(default_factory=list)

    def add(self, kind: SyncActionKind, name: str, **values: Any) -> None:
        self.actions.append(SyncAction(kind=kind, name=name, **values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "programId": self.program_id,
            "weeks": list(self.weeks),
            "actions": [action.to_dict() for action in self.actions],
        }


@dataclass(slots=True)
class ReconcileResult:
    """Lifecycle changes discovered from Garmin calendar history."""

    program_id: str
    actions: list[SyncAction] = field(default_factory=list)

    def add(self, kind: SyncActionKind, name: str, **values: Any) -> None:
        self.actions.append(SyncAction(kind=kind, name=name, **values))

    def to_dict(self) -> dict[str, Any]:
        return {
            "programId": self.program_id,
            "actions": [action.to_dict() for action in self.actions],
        }


__all__ = [
    "ReconcileResult",
    "SyncAction",
    "SyncActionKind",
    "SyncPlan",
    "SyncResult",
]
