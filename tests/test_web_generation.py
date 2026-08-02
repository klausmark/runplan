from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest

from runplan.domain.generation_inputs import (
    AmountKind,
    ClubSessionKind,
    GenerationInputError,
    ProgressionProfile,
    QualityPreference,
    RaceIntensity,
    TrainingStyle,
    Weekday,
)
from runplan.users import RunplanUser, UserRegistry
from runplan.web_generation import WebProgramGenerationService, parse_first_10k_generation_request

TODAY = date(2026, 8, 1)


def registry(tmp_path: Path) -> UserRegistry:
    return UserRegistry(
        [
            RunplanUser(
                "runner",
                "Runner",
                tmp_path / "credentials.toml",
                tmp_path / "tokens",
                tmp_path / "state",
                default_pace="6:10 min/km",
            )
        ]
    )


def generation_payload() -> dict:
    return {
        "userId": "runner",
        "currentTraining": {
            "averageWeeklyKm": 15,
            "runDaysPerWeek": 3,
            "longestRecentRun": {"distanceKm": 6},
        },
        "weekdays": ["tuesday", "thursday", "sunday"],
        "longRunDay": "sunday",
        "startWeek": "2026-08-03",
        "durationWeeks": 4,
    }


def test_request_parser_covers_standard_and_advanced_typed_fields() -> None:
    payload = generation_payload() | {
        "currentTraining": {
            "averageWeeklyKm": 20.5,
            "runDaysPerWeek": 4,
            "longestRecentRun": {"durationMinutes": 70},
            "recent5KDurationMinutes": 27.5,
            "easyPace": {"fastSecondsPerKm": 350, "slowSecondsPerKm": 380},
        },
        "mainRaceDate": "2026-10-11",
        "clubSessions": [
            {
                "weekday": "thursday",
                "kind": "quality",
                "amount": {"durationMinutes": 60},
                "note": "Mixed intervals",
            }
        ],
        "bRaces": [
            {
                "date": "2026-09-13",
                "distanceKm": 5,
                "intensity": "controlled",
                "note": "Local race",
            }
        ],
        "maximumWeeklyKm": 38,
        "maximumLongRunKm": 13,
        "progression": "cautious",
        "trainingStyle": "continuous",
        "qualityPreference": "build",
    }

    request = parse_first_10k_generation_request(payload)

    assert request.current_training.longest_recent_run.kind is AmountKind.DURATION_MINUTES
    assert request.current_training.recent_5k_duration.value == 27.5
    assert request.current_training.easy_pace.fast_seconds_per_km == 350
    assert request.weekdays == (Weekday.TUESDAY, Weekday.THURSDAY, Weekday.SUNDAY)
    assert request.club_sessions[0].kind is ClubSessionKind.QUALITY
    assert request.b_races[0].intensity is RaceIntensity.CONTROLLED
    assert request.progression is ProgressionProfile.CAUTIOUS
    assert request.training_style is TrainingStyle.CONTINUOUS
    assert request.quality_preference is QualityPreference.BUILD
    assert request.maximum_weekly_km == 38


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("5:50", (350, 350)),
        ("5:50-6:20", (350, 380)),
        ("5:50-6:20 min/km", (350, 380)),
    ],
)
def test_request_parser_accepts_easy_pace_form_syntax(
    value: str, expected: tuple[int, int]
) -> None:
    payload = generation_payload()
    payload["currentTraining"] = {
        **payload["currentTraining"],
        "easyPace": value,
    }

    request = parse_first_10k_generation_request(payload)

    assert request.current_training.easy_pace is not None
    assert request.current_training.easy_pace.fast_seconds_per_km == expected[0]
    assert request.current_training.easy_pace.slow_seconds_per_km == expected[1]


def test_request_parser_treats_blank_easy_pace_as_missing() -> None:
    payload = generation_payload()
    payload["currentTraining"] = {
        **payload["currentTraining"],
        "easyPace": "   ",
    }

    request = parse_first_10k_generation_request(payload)

    assert request.current_training.easy_pace is None


def test_malformed_easy_pace_has_fixed_safe_error() -> None:
    private_value = "PRIVATE-EASY-PACE-value"
    payload = generation_payload()
    payload["currentTraining"] = {
        **payload["currentTraining"],
        "easyPace": private_value,
    }

    with pytest.raises(GenerationInputError) as raised:
        parse_first_10k_generation_request(payload)

    assert str(raised.value) == "currentTraining.easyPace must use M:SS or M:SS-M:SS per km"
    assert private_value not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("averageWeeklyKm", -0.1, "at least 0 km"),
        ("averageWeeklyKm", 300.1, "at most 300 km"),
        ("recent5KDurationMinutes", 9.9, "from 10 to 180 minutes"),
        ("recent5KDurationMinutes", 180.1, "from 10 to 180 minutes"),
    ],
)
def test_request_parser_enforces_browser_numeric_bounds(
    field: str, value: float, message: str
) -> None:
    payload = generation_payload()
    payload["currentTraining"] = {**payload["currentTraining"], field: value}

    with pytest.raises(GenerationInputError, match=message):
        parse_first_10k_generation_request(payload)


@pytest.mark.parametrize(
    "change",
    [
        {"currentTraining": {**generation_payload()["currentTraining"], "averageWeeklyKm": True}},
        {
            "currentTraining": {
                **generation_payload()["currentTraining"],
                "longestRecentRun": {"distanceKm": 6, "durationMinutes": 40},
            }
        },
        {"durationWeeks": True},
        {"startWeek": "2026-13-01"},
    ],
)
def test_request_parser_rejects_invalid_typed_values(change: dict) -> None:
    with pytest.raises(ValueError):
        parse_first_10k_generation_request(generation_payload() | change)


def test_service_generates_local_draft_without_persistence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = WebProgramGenerationService(registry(tmp_path), today=lambda: TODAY)

    def reject_write(*args: object, **kwargs: object) -> int:
        raise AssertionError("generation must not persist")

    monkeypatch.setattr(Path, "write_text", reject_write)
    draft = service.generate(generation_payload())

    assert draft.summary.weeks == 4
    assert draft.attempt_count == 1
