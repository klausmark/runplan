"""Errors raised by the rolling everyday plan use cases.

The use cases raise :class:`EverydayError` for any failure mode the
runner should see. ``kind`` identifies the failure so the CLI and the
future Studio UI can map it to a localised message.
"""

from __future__ import annotations

from ...domain.errors import WorkoutDefinitionError


class EverydayError(WorkoutDefinitionError):
    """Raised when an everyday-plan use case cannot complete.

    ``kind`` identifies the failure mode so callers can map it to a
    user-facing error. ``message`` is the human-readable explanation.
    """

    def __init__(self, kind: str, message: str) -> None:
        super().__init__(message)
        self.kind = kind
        self.message = message

    def __str__(self) -> str:
        return self.message


UNKNOWN_PROGRAM = "unknown_program"
INVALID_REQUEST = "invalid_request"
DAY_CONFLICT = "day_conflict"
KEY_RULE_VIOLATION = "key_rule_violation"
DUPLICATE_WORKOUT_ID = "duplicate_workout_id"
PERSISTENCE_FAILED = "persistence_failed"


__all__ = [
    "DAY_CONFLICT",
    "DUPLICATE_WORKOUT_ID",
    "EverydayError",
    "INVALID_REQUEST",
    "KEY_RULE_VIOLATION",
    "PERSISTENCE_FAILED",
    "UNKNOWN_PROGRAM",
]
