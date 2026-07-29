"""Execute a previously confirmed web synchronization request."""

from __future__ import annotations

import logging
from collections.abc import Callable
from http import HTTPStatus
from time import perf_counter
from typing import Any

from .users import WebError

logger = logging.getLogger("runplan.web")


def execute_confirmed_sync(
    service: Any,
    name: str,
    request: dict[str, Any],
    synchronize: Callable[..., Any],
) -> dict[str, Any]:
    """Validate a preview token, execute its sync, and map the response."""
    user = service.users.get(request.get("userId") or service.users.default_id)
    preview = _confirmed_preview(service, name, request, user.id)
    selections = service._selections(name, user.id)
    weeks = [program["week"] for program, _ in selections]
    started = perf_counter()
    logger.info(
        "Garmin sync started user=%s file=%s program_id=%s weeks=%s",
        user.id,
        name,
        preview["plan"]["programId"],
        _week_list(weeks),
    )
    results = _run_sync(service, synchronize, user.id, name, selections, started)
    _log_completion(user.id, name, preview, weeks, results, started)
    return {
        "userId": user.id,
        "programId": preview["plan"]["programId"],
        "weeks": preview["plan"]["weeks"],
        "results": [result.to_dict() for result in results],
    }


def _confirmed_preview(
    service: Any, name: str, request: dict[str, Any], user_id: str
) -> dict[str, Any]:
    if not isinstance(request.get("confirmationToken"), str):
        raise WebError(HTTPStatus.BAD_REQUEST, "Sync requires a preview confirmation token")
    preview = service.preview(name, user_id)
    if request["confirmationToken"] != preview["confirmationToken"]:
        raise WebError(
            HTTPStatus.CONFLICT,
            "The plan or sync state changed; review the sync preview again",
        )
    return preview


def _run_sync(
    service: Any,
    synchronize: Callable[..., Any],
    user_id: str,
    name: str,
    selections: Any,
    started: float,
) -> Any:
    try:
        return synchronize(
            service.client_for(user_id),
            service.repository_for(user_id, name),
            selections,
            today=service.today(),
        )
    except SystemExit as exc:
        logger.error(
            "Garmin sync failed user=%s file=%s exception=%s message=%s",
            user_id,
            name,
            type(exc).__name__,
            exc,
        )
        raise WebError(HTTPStatus.BAD_GATEWAY, str(exc)) from exc
    except Exception as exc:
        log_method = logger.error if getattr(exc, "_runplan_logged", False) else logger.exception
        log_method(
            "Garmin sync failed user=%s file=%s exception=%s message=%s duration_ms=%d",
            user_id,
            name,
            type(exc).__name__,
            exc,
            round((perf_counter() - started) * 1000),
        )
        raise WebError(
            HTTPStatus.BAD_GATEWAY,
            f"Garmin sync failed: {type(exc).__name__}: {exc}",
        ) from exc


def _log_completion(
    user_id: str, name: str, preview: dict[str, Any], weeks: list[Any], results: Any, started: float
) -> None:
    counts: dict[str, int] = {}
    for result in results:
        for action in result.actions:
            counts[action.kind] = counts.get(action.kind, 0) + 1
    actions = ",".join(f"{kind}:{count}" for kind, count in sorted(counts.items())) or "none"
    logger.info(
        "Garmin sync completed user=%s file=%s program_id=%s weeks=%s actions=%s duration_ms=%d",
        user_id,
        name,
        preview["plan"]["programId"],
        _week_list(weeks),
        actions,
        round((perf_counter() - started) * 1000),
    )


def _week_list(weeks: list[Any]) -> str:
    return ",".join(str(week) for week in weeks)
