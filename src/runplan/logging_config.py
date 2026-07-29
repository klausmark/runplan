"""Logging configuration for the long-running Runplan server."""

from __future__ import annotations

import logging
import re
import sys
from typing import TextIO

LOGGER_NAME = "runplan"
LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL")

_REDACTIONS = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "<redacted-email>"),
    (
        re.compile(
            r"(?i)\b(password|token|authorization|confirmation[_-]?token)\b"
            r"(\s*[:=]\s*|\s+)([^\s,;]+)"
        ),
        r"\1\2<redacted>",
    ),
    (
        re.compile(r"(?i)(?:/[^\s:]+)*/(?:credentials[^/\s]*|tokens?)(?:/[^\s:]*)?"),
        "<redacted-secret-path>",
    ),
)


def _redact(value: str) -> str:
    for pattern, replacement in _REDACTIONS:
        value = pattern.sub(replacement, value)
    return value


class SafeFormatter(logging.Formatter):
    """Format and redact the complete record, including exception tracebacks."""

    def format(self, record: logging.LogRecord) -> str:
        return _redact(super().format(record))


def configure_server_logging(level: str, *, stream: TextIO | None = None) -> logging.Logger:
    """Configure one stdout handler for all Runplan module loggers."""
    normalized = level.upper()
    if normalized not in LOG_LEVELS:
        raise ValueError(f"Unsupported log level {level!r}")
    logger = logging.getLogger(LOGGER_NAME)
    logger.handlers.clear()
    handler = logging.StreamHandler(stream or sys.stdout)
    handler.setFormatter(
        SafeFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
    )
    logger.addHandler(handler)
    logger.setLevel(normalized)
    logger.propagate = False
    return logger


__all__ = ["LOG_LEVELS", "configure_server_logging"]
