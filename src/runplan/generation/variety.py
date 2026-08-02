"""Workout variety selection.

The generator composes a program by picking a workout type per slot. The
variety board records the last type used in each role so consecutive weeks
stay different. The pick is deterministic and seeded through the request.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .workouts import EASY_TEMPLATES, LONG_RUN_TEMPLATES, QUALITY_TEMPLATES


@dataclass(frozen=True, slots=True)
class VarietyBoard:
    """The last workout type used in each role plus slot counts."""

    last_long: str | None = None
    last_quality: str | None = None
    last_easy: str | None = None
    long_used: tuple[str, ...] = ()
    quality_used: tuple[str, ...] = ()
    easy_used: tuple[str, ...] = ()

    def with_long(self, kind: str) -> VarietyBoard:
        return VarietyBoard(
            last_long=kind,
            last_quality=self.last_quality,
            last_easy=self.last_easy,
            long_used=self.long_used + (kind,),
            quality_used=self.quality_used,
            easy_used=self.easy_used,
        )

    def with_quality(self, kind: str) -> VarietyBoard:
        return VarietyBoard(
            last_long=self.last_long,
            last_quality=kind,
            last_easy=self.last_easy,
            long_used=self.long_used,
            quality_used=self.quality_used + (kind,),
            easy_used=self.easy_used,
        )

    def with_easy(self, kind: str) -> VarietyBoard:
        return VarietyBoard(
            last_long=self.last_long,
            last_quality=self.last_quality,
            last_easy=kind,
            long_used=self.long_used,
            quality_used=self.quality_used,
            easy_used=self.easy_used + (kind,),
        )


def pick_long_run_kind(board: VarietyBoard, week: int) -> tuple[str, VarietyBoard]:
    """Pick a long-run style that avoids repeating the previous week."""
    return _pick(board, "long", LONG_RUN_TEMPLATES, week)


def pick_quality_kind(board: VarietyBoard, week: int) -> tuple[str, VarietyBoard]:
    """Pick a quality workout type that avoids repeating the previous week."""
    return _pick(board, "quality", QUALITY_TEMPLATES, week)


def pick_easy_kind(board: VarietyBoard, week: int) -> tuple[str, VarietyBoard]:
    """Pick an easy workout style that avoids repeating the previous week."""
    return _pick(board, "easy", EASY_TEMPLATES, week)


def _pick(
    board: VarietyBoard,
    role: str,
    options: tuple[str, ...],
    week: int,
) -> tuple[str, VarietyBoard]:
    """Pick a workout type for ``role`` that is not the previous one."""
    last = _last_for_role(board, role)
    if last is None:
        kind = options[week % len(options)]
    else:
        candidates = [opt for opt in options if opt != last]
        if not candidates:
            candidates = list(options)
        kind = candidates[week % len(candidates)]
    if role == "long":
        return kind, board.with_long(kind)
    if role == "quality":
        return kind, board.with_quality(kind)
    return kind, board.with_easy(kind)


def _last_for_role(board: VarietyBoard, role: str) -> str | None:
    if role == "long":
        return board.last_long
    if role == "quality":
        return board.last_quality
    return board.last_easy


def summary_stats(board: VarietyBoard) -> dict[str, Any]:
    """Return a dictionary of variety diagnostics for the generated plan."""
    return {
        "long_run_types_used": len(set(board.long_used)),
        "quality_types_used": len(set(board.quality_used)),
        "easy_types_used": len(set(board.easy_used)),
        "long_run_history": list(board.long_used),
        "quality_history": list(board.quality_used),
        "easy_history": list(board.easy_used),
    }


__all__ = [
    "VarietyBoard",
    "pick_easy_kind",
    "pick_long_run_kind",
    "pick_quality_kind",
    "summary_stats",
]
