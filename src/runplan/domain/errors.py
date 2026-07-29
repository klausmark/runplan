"""Domain-level errors."""


class WorkoutDefinitionError(ValueError):
    """A precise error in a human-authored workout definition."""


__all__ = ["WorkoutDefinitionError"]
