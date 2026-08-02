"""Safe HTTP serialization for background program generation."""

from __future__ import annotations

from dataclasses import asdict
from datetime import date
from http import HTTPStatus
from typing import Any

from .application.generate_first_10k import InvalidGeneratedProgramError
from .integrations.minimax import MiniMaxRateLimitError, MiniMaxTimeoutError
from .integrations.minimax.client import MiniMaxError, MiniMaxProtocolError


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


def minimax_protocol_message(exc: MiniMaxProtocolError) -> str:
    if exc.reason == "output_limit":
        return "MiniMax reached its output limit before completing the program"
    if exc.reason == "content_filtered":
        return "MiniMax filtered the generated program"
    if exc.reason in {
        "missing_choices",
        "missing_message",
        "missing_content",
        "invalid_json",
    }:
        return "MiniMax returned an incomplete response; try generating again"
    return "Program generation is unavailable"


def generation_job_error(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, InvalidGeneratedProgramError):
        return {"httpStatus": HTTPStatus.UNPROCESSABLE_ENTITY, **invalid_generation(exc)}
    if isinstance(exc, MiniMaxRateLimitError):
        return {
            "httpStatus": HTTPStatus.TOO_MANY_REQUESTS,
            "error": "Program generation quota or rate limit reached",
        }
    if isinstance(exc, MiniMaxTimeoutError):
        return {
            "httpStatus": HTTPStatus.GATEWAY_TIMEOUT,
            "error": "Program generation timed out",
        }
    if isinstance(exc, MiniMaxProtocolError):
        return {
            "httpStatus": HTTPStatus.SERVICE_UNAVAILABLE,
            "error": minimax_protocol_message(exc),
        }
    if isinstance(exc, MiniMaxError):
        return {
            "httpStatus": HTTPStatus.SERVICE_UNAVAILABLE,
            "error": "Program generation is unavailable",
        }
    return {
        "httpStatus": HTTPStatus.INTERNAL_SERVER_ERROR,
        "error": "Program generation failed",
    }


def generation_job(job: Any) -> dict[str, Any]:
    result = {
        "jobId": job.id,
        "status": job.status,
        "phase": job.phase,
        "message": job.message,
        "elapsedSeconds": job.elapsed_seconds,
    }
    if job.draft is not None:
        result["draft"] = generation_draft(job.draft)
    if job.error is not None:
        result["error"] = generation_job_error(job.error)
    return result


__all__ = [
    "generation_draft",
    "generation_job",
    "invalid_generation",
    "minimax_protocol_message",
]
