"""Raw step builders shared by the recipe catalogue and the generator.

The :mod:`runplan.domain.recipes` modules and the non-recipe slots
(club sessions, races) call into this module to materialise a workout's
step list as raw dictionaries. The step builders mirror the YAML
vocabulary so the generated program round-trips through the existing
parser. Step 9 removed the dispatch wrappers and the style-string
dispatch tables; everything in this module is now a leaf-level helper.
"""

from __future__ import annotations

__all__ = [
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
    "steps_pace_distance",
    "steps_pace_time",
]


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


def _pace_spec(pace: list[str] | None) -> dict:
    """Return the pace spec dict, or an empty dict when pace is unknown."""
    if pace is None:
        return {}
    return {"pace": f"{pace[0]}-{pace[1]} min/km"}


def build_continuous_tempo(minutes: int, pace: list[str] | None) -> list[dict]:
    """Continuous tempo block in Zone 3."""
    return [
        {"warmup": "10m"},
        {"run": {"time": f"{minutes}m", **_pace_spec(pace)}},
        {"cooldown": "10m"},
    ]


def build_cruise_intervals(reps: int, rep_minutes: int, pace: list[str] | None) -> list[dict]:
    """Cruise intervals in Zone 3 with jog recoveries."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"time": f"{rep_minutes}m", **_pace_spec(pace)}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_track_400m(reps: int, pace: list[str] | None) -> list[dict]:
    """Short 400m repeats in Zone 5."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"distance": "400m", **_pace_spec(pace)}},
                    {"recovery": {"time": "90s"}},
                ],
            }
        },
        {"cooldown": "10m"},
    ]


def build_track_1k(reps: int, pace: list[str] | None) -> list[dict]:
    """Steady 1K repeats in Zone 4-5."""
    return [
        {"warmup": "10m"},
        {
            "repeat": {
                "count": reps,
                "steps": [
                    {"run": {"distance": "1km", **_pace_spec(pace)}},
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
