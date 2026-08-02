"""Safe HTTP serialization for background program generation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from typing import Any


def diagnostic(value: Any) -> dict[str, Any]:
    result = {"severity": value.severity, "code": value.code, "message": value.message[:1000]}
    if value.occurrence is not None:
        occurrence = asdict(value.occurrence)
        result["occurrence"] = {
            key: item.isoformat() if isinstance(item, date) else item
            for key, item in occurrence.items()
            if item is not None
        }
    return result


def generation_draft(draft: Any) -> dict[str, Any]:
    return {
        "filename": draft.filename,
        "content": draft.content,
        "warnings": [diagnostic(item) for item in draft.warnings],
        "summary": {"weeks": draft.summary.weeks, "workouts": draft.summary.workouts},
        "attemptCount": draft.attempt_count,
    }


def invalid_generation(exc: Any) -> dict[str, Any]:
    candidate = exc.candidate.encode("utf-8")[: 128 * 1024].decode("utf-8", errors="ignore")
    return {
        "error": str(exc),
        "candidate": candidate,
        "diagnostics": [diagnostic(item) for item in exc.diagnostics[:100]],
        "attemptCount": exc.attempt_count,
    }


__all__ = [
    "generation_draft",
    "invalid_generation",
]
