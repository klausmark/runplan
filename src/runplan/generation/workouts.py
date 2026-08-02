"""Workout templates for the first 10K generator.

Each template is a pure function from parameters to a list of step
dictionaries. The templates share a vocabulary with the existing Runplan YAML
format so the generated program round-trips through the existing parser.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .phase import PhaseKind


@dataclass(frozen=True, slots=True)
class WorkoutTemplate:
    """A reusable workout shape with an identifier and a builder."""

    name: str
    kind: str
    zone_label: str
    description: str
    build: Any  # callable returning list[dict] representing steps


def steps_pace_time(repeat: int, minutes: int, seconds: int, pace: list[str]) -> list[dict]:
    """Repeat ``pace`` blocks of ``minutes:seconds`` running steps."""
    return [
        {"run": {"time": f"{minutes}m{seconds}s", "pace": f"{pace[0]}-{pace[1]} min/km"}}
        for _ in range(repeat)
    ]


def steps_pace_distance(distance_m: int, pace: list[str]) -> dict:
    """Return a single distance step with a pace range."""
    if distance_m >= 1000 and distance_m % 1000 == 0:
        distance_str = f"{distance_m // 1000}km"
    else:
        distance_str = f"{distance_m}m"
    return {"run": {"distance": distance_str, "pace": f"{pace[0]}-{pace[1]} min/km"}}


def build_easy_continuous(minutes: int) -> list[dict]:
    """Easy continuous run target centred on Zone 2."""
    return [
        {"warmup": "5m"},
        {"run": {"time": f"{minutes}m"}},
        {"cooldown": "5m"},
    ]


def build_easy_with_strides(minutes: int) -> list[dict]:
    """Easy continuous run with 4 short strides at the end."""
    return [
        {"warmup": "5m"},
        {"run": {"time": f"{minutes}m"}},
        {
            "repeat": {
                "count": 4,
                "steps": [
                    {"run": {"time": "20s"}},
                    {"recovery": {"time": "60s"}},
                ],
            }
        },
        {"cooldown": "5m"},
    ]


def build_long_steady(target_km: float, pace: list[str] | None) -> list[dict]:
    """Steady long run with optional effort-based pace."""
    if pace is None:
        return [
            {"warmup": "10m"},
            {"run": {"distance": f"{target_km:.1f}km"}},
            {"cooldown": "10m"},
        ]
    return [
        {"warmup": "10m"},
        {"run": {"distance": f"{target_km:.1f}km", "pace": f"{pace[0]}-{pace[1]} min/km"}},
        {"cooldown": "10m"},
    ]


def build_long_with_finish(easy_km: float, finish_km: float, pace: list[str] | None) -> list[dict]:
    """Easy long run with a moderate finish segment."""
    if pace is None:
        return [
            {"warmup": "10m"},
            {"run": {"distance": f"{easy_km:.1f}km"}},
            {"run": {"distance": f"{finish_km:.1f}km"}},
            {"cooldown": "5m"},
        ]
    return [
        {"warmup": "10m"},
        {"run": {"distance": f"{easy_km:.1f}km"}},
        {"run": {"distance": f"{finish_km:.1f}km", "pace": f"{pace[0]}-{pace[1]} min/km"}},
        {"cooldown": "5m"},
    ]


def build_long_with_hill_surges(easy_km: float, surge_count: int) -> list[dict]:
    """Long run with hill surges inserted into an easy run."""
    return [
        {"warmup": "10m"},
        {"run": {"distance": f"{easy_km:.1f}km"}},
        {
            "repeat": {
                "count": surge_count,
                "steps": [
                    {"run": {"time": "30s"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_long_with_kickouts(easy_km: float, kick_count: int, kick_minutes: int) -> list[dict]:
    """Long run with steady kickouts embedded."""
    return [
        {"warmup": "10m"},
        {"run": {"distance": f"{easy_km:.1f}km"}},
        {
            "repeat": {
                "count": kick_count,
                "steps": [
                    {"run": {"time": f"{kick_minutes}m"}},
                    {"recovery": {"time": "2m"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_continuous_tempo(minutes: int, pace: list[str]) -> list[dict]:
    """Continuous tempo block in Zone 3."""
    return [
        {"warmup": "10m"},
        {"run": {"time": f"{minutes}m", "pace": f"{pace[0]}-{pace[1]} min/km"}},
        {"cooldown": "10m"},
    ]


def build_cruise_intervals(reps: int, rep_minutes: int, pace: list[str]) -> list[dict]:
    """Cruise intervals in Zone 3 with jog recoveries."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"time": f"{rep_minutes}m", "pace": f"{pace[0]}-{pace[1]} min/km"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_track_400m(reps: int, pace: list[str]) -> list[dict]:
    """Short 400m repeats in Zone 5."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"distance": "400m", "pace": f"{pace[0]}-{pace[1]} min/km"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_track_1k(reps: int, pace: list[str]) -> list[dict]:
    """Steady 1K repeats in Zone 4-5."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"distance": "1km", "pace": f"{pace[0]}-{pace[1]} min/km"}},
                    {"recovery": {"time": "2m"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_hill_repeats(reps: int, effort_seconds: int) -> list[dict]:
    """Hill repeats in Zone 4 with jog-down recovery."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"time": f"{effort_seconds}s"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_fartlek(cycle_count: int, hard_minutes: int, easy_minutes: int) -> list[dict]:
    """Fartlek-style alternation between hard and easy running."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": cycle_count,
                "steps": [
                    {"run": {"time": f"{hard_minutes}m"}},
                    {"recovery": {"time": f"{easy_minutes}m"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_recovery_run(minutes: int) -> list[dict]:
    """Very short recovery run in Zone 1."""
    return [{"run": {"time": f"{minutes}m"}}]


def build_race(distance_km: float) -> list[dict]:
    """A race workout: a single distance step with no pace."""
    formatted = "10km" if abs(distance_km - 10.0) < 0.05 else f"{distance_km:.1f}km"
    return [{"run": {"distance": formatted}}]


def build_warmup_run(minutes: int) -> list[dict]:
    """Default warmup only for very short or unstructured sessions."""
    return [
        {"warmup": "5m"},
        {"run": {"time": f"{minutes}m"}},
        {"cooldown": "5m"},
    ]


def steps_easy_continuous(minutes: int) -> list[dict]:
    return build_easy_continuous(minutes)


# Order is meaningful: variety cycler uses index modulo len to pick a fresh
# workout type each week and to avoid repeating the same type week-over-week.
QUALITY_TEMPLATES: tuple[str, ...] = (
    "continuous_tempo",
    "cruise_intervals",
    "track_400m",
    "track_1k",
    "hill_repeats",
    "fartlek",
)

LONG_RUN_TEMPLATES: tuple[str, ...] = (
    "steady",
    "with_finish",
    "with_hill_surges",
    "with_kickouts",
)

EASY_TEMPLATES: tuple[str, ...] = (
    "easy_continuous",
    "easy_with_strides",
    "easy_continuous",
)


def long_run_builder(
    style: str,
    target_km: float,
    pace: list[str] | None,
) -> list[dict]:
    """Return the steps for a long-run workout of the given style."""
    if target_km <= 0:
        return build_recovery_run(15)
    if style == "steady":
        return build_long_steady(target_km, pace)
    if style == "with_finish":
        finish_km = max(1.5, round(target_km * 0.20, 1))
        easy_km = max(2.0, round(target_km - finish_km, 1))
        return build_long_with_finish(easy_km, finish_km, pace)
    if style == "with_hill_surges":
        surge_count = 6 if target_km >= 8 else 4
        return build_long_with_hill_surges(target_km, surge_count)
    if style == "with_kickouts":
        kick_count = 4 if target_km >= 8 else 3
        kick_minutes = 2 if target_km >= 8 else 1
        return build_long_with_kickouts(target_km, kick_count, kick_minutes)
    return build_long_steady(target_km, pace)


def easy_builder(style: str, target_km: float) -> list[dict]:
    """Return the steps for an easy run of the given style."""
    minutes = max(20, round(target_km * 6))
    if style == "easy_with_strides":
        return build_easy_with_strides(minutes)
    return build_easy_continuous(minutes)


def quality_builder(
    style: str,
    pace: list[str] | None,
    week: int,
    phase: PhaseKind,
) -> tuple[str, list[dict]]:
    """Return a (name, steps) pair for a quality session.

    The pace argument is ``None`` when the user did not supply known pace
    data. Quality templates return effort-only step descriptions in that case.
    """
    if pace is None:
        return _quality_without_pace(style, week, phase)
    smooth = _smooth_pace(pace)
    tempo_pace = _tempo_pace(smooth)
    interval_pace = _interval_pace(smooth)

    if style == "continuous_tempo":
        minutes = _tempo_minutes(week, phase)
        return ("Tempo run", build_continuous_tempo(minutes, tempo_pace))
    if style == "cruise_intervals":
        reps = _cruise_reps(week, phase)
        rep_minutes = _cruise_minutes(week, phase)
        return ("Cruise intervals", build_cruise_intervals(reps, rep_minutes, tempo_pace))
    if style == "track_400m":
        reps = _track_400_reps(week, phase)
        return ("400m repeats", build_track_400m(reps, interval_pace))
    if style == "track_1k":
        if week <= 3:
            return ("Tempo run", build_continuous_tempo(_tempo_minutes(week, phase), tempo_pace))
        reps = _track_1k_reps(week, phase)
        return ("1km repeats", build_track_1k(reps, interval_pace))
    if style == "hill_repeats":
        reps = _hill_reps(week, phase)
        return ("Hill repeats", build_hill_repeats(reps, 60))
    if style == "fartlek":
        cycles = _fartlek_cycles(week, phase)
        return ("Fartlek", build_fartlek(cycles, 2, 1))
    return ("Tempo run", build_continuous_tempo(15, tempo_pace))


def _quality_without_pace(style: str, week: int, phase: PhaseKind) -> tuple[str, list[dict]]:
    """Effort-only build when no pace is known."""
    if style == "continuous_tempo":
        minutes = _tempo_minutes(week, phase)
        return ("Tempo run", _time_tempo(minutes))
    if style == "cruise_intervals":
        reps = _cruise_reps(week, phase)
        rep_minutes = _cruise_minutes(week, phase)
        return ("Cruise intervals", _time_cruise(reps, rep_minutes))
    if style == "track_400m":
        reps = _track_400_reps(week, phase)
        return ("400m repeats", _time_400m(reps))
    if style == "track_1k":
        if week <= 3:
            return ("Tempo run", _time_tempo(_tempo_minutes(week, phase)))
        return ("1km repeats", _time_1k(_track_1k_reps(week, phase)))
    if style == "hill_repeats":
        reps = _hill_reps(week, phase)
        return ("Hill repeats", build_hill_repeats(reps, 60))
    if style == "fartlek":
        cycles = _fartlek_cycles(week, phase)
        return ("Fartlek", build_fartlek(cycles, 2, 1))
    return ("Tempo run", _time_tempo(15))


def _time_tempo(minutes: int) -> list[dict]:
    return [
        {"warmup": "10m"},
        {"run": {"time": f"{minutes}m"}},
        {"cooldown": "10m"},
    ]


def _time_cruise(reps: int, rep_minutes: int) -> list[dict]:
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"time": f"{rep_minutes}m"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def _time_400m(reps: int) -> list[dict]:
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"time": "90s"}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def _time_1k(reps: int) -> list[dict]:
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"time": "4m"}},
                    {"recovery": {"time": "2m"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def _smooth_pace(pace: list[str]) -> list[str]:
    """Return a stable list of two minute:second strings."""
    return [pace[0], pace[1]]


def _pace_string_to_seconds(text: str) -> int:
    """Convert a M:SS min/km string to total seconds."""
    minute, second = text.split(":")
    return int(minute) * 60 + int(second)


def _seconds_to_pace_string(seconds: int) -> str:
    """Convert seconds back to a M:SS string."""
    return f"{seconds // 60}:{seconds % 60:02d}"


def _tempo_pace(pace: list[str]) -> list[str]:
    """Return a tempo pace range: 10-15% slower than the easy pace midpoint."""
    fast = _pace_string_to_seconds(pace[0])
    slow = _pace_string_to_seconds(pace[1])
    midpoint = (fast + slow) // 2
    tempo = int(round(midpoint * 1.10))
    return [_seconds_to_pace_string(tempo), _seconds_to_pace_string(tempo)]


def _interval_pace(pace: list[str]) -> list[str]:
    """Return an interval pace range: 5-8% faster than the easy pace midpoint."""
    fast = _pace_string_to_seconds(pace[0])
    slow = _pace_string_to_seconds(pace[1])
    midpoint = (fast + slow) // 2
    interval = int(round(midpoint * 0.93))
    return [_seconds_to_pace_string(interval), _seconds_to_pace_string(interval)]


def _tempo_minutes(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 15
    if phase is PhaseKind.BUILD:
        return 20 if week <= 8 else 25
    return 25 if phase is PhaseKind.PEAK else 20


def _cruise_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 3
    if phase is PhaseKind.BUILD:
        return 4
    return 5 if phase is PhaseKind.PEAK else 3


def _cruise_minutes(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 4
    if phase is PhaseKind.BUILD:
        return 5
    return 6 if phase is PhaseKind.PEAK else 5


def _track_400_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 5
    if phase is PhaseKind.BUILD:
        return 7
    return 8 if phase is PhaseKind.PEAK else 5


def _track_1k_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.BUILD:
        return 4
    return 5 if phase is PhaseKind.PEAK else 4


def _hill_reps(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 5
    if phase is PhaseKind.BUILD:
        return 7
    return 8 if phase is PhaseKind.PEAK else 6


def _fartlek_cycles(week: int, phase: PhaseKind) -> int:
    if phase is PhaseKind.FOUNDATION:
        return 5
    if phase is PhaseKind.BUILD:
        return 7
    return 8 if phase is PhaseKind.PEAK else 6


def easy_minutes_from_km(target_km: float) -> int:
    """Convert a target distance into an easy-run duration in minutes."""
    return max(20, round(target_km * 6))


__all__ = [
    "EASY_TEMPLATES",
    "LONG_RUN_TEMPLATES",
    "QUALITY_TEMPLATES",
    "WorkoutTemplate",
    "build_continuous_tempo",
    "build_cruise_intervals",
    "build_easy_continuous",
    "build_easy_with_strides",
    "build_fartlek",
    "build_hill_repeats",
    "build_long_steady",
    "build_long_with_finish",
    "build_long_with_hill_surges",
    "build_long_with_kickouts",
    "build_race",
    "build_recovery_run",
    "build_track_400m",
    "build_track_1k",
    "build_warmup_run",
    "easy_builder",
    "easy_minutes_from_km",
    "long_run_builder",
    "quality_builder",
]
