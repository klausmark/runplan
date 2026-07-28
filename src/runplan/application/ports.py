"""Ports consumed by Runplan application use cases."""

from __future__ import annotations

from typing import Any, Protocol


class GarminClient(Protocol):
    """Minimal Garmin operations required by synchronization."""

    def get_workouts(self, start: int, limit: int) -> list[dict[str, Any]]: ...

    def get_scheduled_workouts(self, year: int, month: int) -> dict[str, Any]: ...

    def get_activity(self, activity_id: str) -> dict[str, Any]: ...

    def upload_running_workout(self, workout: Any) -> dict[str, Any]: ...

    def schedule_workout(self, workout_id: int, scheduled_date: str) -> dict[str, Any]: ...

    def unschedule_workout(self, schedule_id: int) -> Any: ...

    def delete_workout(self, workout_id: int) -> Any: ...


class StateRepository(Protocol):
    """Persistence contract for program synchronization state."""

    def load(self, program_id: str) -> dict[str, Any]: ...

    def save(self, program_id: str, state: dict[str, Any]) -> None: ...

    def delete(self, program_id: str) -> None: ...


__all__ = ["GarminClient", "StateRepository"]
