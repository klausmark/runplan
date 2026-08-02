"""Domain-specific errors for the first 10K generator."""

from __future__ import annotations


class GenerationError(ValueError):
    """The generator request cannot produce a valid program."""


class GenerationWarning:
    """A non-fatal diagnostic surfaced in the generator result."""

    __slots__ = ("code", "message")

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message

    def __repr__(self) -> str:
        return f"GenerationWarning(code={self.code!r}, message={self.message!r})"

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, GenerationWarning):
            return NotImplemented
        return self.code == other.code and self.message == other.message

    def __hash__(self) -> int:
        return hash((self.code, self.message))


__all__ = ["GenerationError", "GenerationWarning"]
