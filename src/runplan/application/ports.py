"""Ports consumed by Runplan application use cases."""

from __future__ import annotations

from typing import Any, Protocol


class GarminClient(Protocol):
    """Minimal Garmin operations required by synchronization."""

    def get_workouts(self, start: int, limit: int) -> list[dict[str, Any]]: ...

    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]: ...

    def get_activity(self, activity_id: str) -> dict[str, Any]: ...

    def get_activities_by_date(
        self,
        startdate: str,
        enddate: str | None = None,
        activitytype: str | None = None,
    ) -> list[dict[str, Any]]: ...

    def upload_running_workout(self, workout: Any) -> dict[str, Any]: ...

    def schedule_workout(self, workout_id: int, scheduled_date: str) -> dict[str, Any]: ...

    def unschedule_workout(self, schedule_id: int) -> Any: ...

    def delete_workout(self, workout_id: int) -> Any: ...


class StateRepository(Protocol):
    """Persistence contract for program synchronization state."""

    def load(self, program_id: str) -> dict[str, Any]: ...

    def save(self, program_id: str, state: dict[str, Any]) -> None: ...

    def delete(self, program_id: str) -> None: ...


class ProgramRepository(Protocol):
    """Persistence contract for program YAML documents.

    Implementations read and write the raw YAML document so callers can
    validate and edit it through the same pipeline used by the web layer.
    The Step 6 ``instantiate_recipe`` use case consumes this port.
    """

    def load(self, program_id: str) -> dict[str, Any]:
        """Return the raw YAML document for ``program_id``.

        Raises ``KeyError`` when the document does not exist.
        """
        ...

    def save(self, program_id: str, raw: dict[str, Any]) -> None:
        """Persist the updated raw YAML document."""
        ...


__all__ = ["GarminClient", "ProgramRepository", "StateRepository"]
