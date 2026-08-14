"""Coaching context builder and program-history bridge (Step 8).

The recommender is pure, but the Studio needs to populate it from a
program document and the run plan's saved state. These tests pin down:

- the parser helpers that turn JSON-friendly values into the domain
  enums,
- the context builder's handling of the user's pace baseline,
- the bridging of completed records (with ``tracking.actual`` blocks)
  into :class:`CompletedWorkout` rows that the recommender can reason
  about, and
- the week-key detector the Studio uses for the key-workout warning
  on planned workouts.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import date

import pytest

from runplan.application.coaching.context import (
    build_recommendation_context,
    completed_workouts_from_program,
    parse_readiness,
    parse_request_kind,
    week_key_forms_for,
)
from runplan.domain.recommendations import (
    Readiness,
    WorkoutRequestKind,
)
from runplan.domain.workout_form import (
    EASY_RUN,
    TEMPO_RUN,
)

_BASE_PROGRAM: dict = {
    "program": {
        "id": "context-demo",
        "name": "Context demo",
        "short_name": "CTX",
        "description": "Coaching context tests",
        "start_week": "2026-W01",
    },
    "weeks": [
        {
            "week": 1,
            "focus": "Base",
            "workouts": [
                {
                    "id": "easy-mon",
                    "day": 1,
                    "name": "Easy Monday",
                    "steps": [{"run": {"distance": "5km"}}],
                },
            ],
        },
        {
            "week": 2,
            "focus": "Build",
            "workouts": [
                {
                    "id": "tempo-tue",
                    "day": 2,
                    "name": "Tempo Tuesday",
                    "steps": [{"run": {"time": "20m", "pace": "5:00 min/km"}}],
                },
                {
                    "id": "long-sun",
                    "day": 7,
                    "name": "Long Sunday",
                    "steps": [{"run": {"distance": "12km"}}],
                },
            ],
        },
    ],
}


# ---------------------------------------------------------------------------
# parse_readiness / parse_request_kind
# ---------------------------------------------------------------------------


def test_parse_readiness_accepts_low_normal_high() -> None:
    assert parse_readiness("low") is Readiness.LOW
    assert parse_readiness("NORMAL") is Readiness.NORMAL
    assert parse_readiness("high") is Readiness.HIGH


def test_parse_readiness_treats_missing_or_blank_as_none() -> None:
    assert parse_readiness(None) is None
    assert parse_readiness("") is None
    assert parse_readiness("   ") is None


def test_parse_readiness_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="invalid readiness"):
        parse_readiness("medium")


def test_parse_readiness_rejects_non_strings() -> None:
    with pytest.raises(ValueError, match="invalid readiness"):
        parse_readiness(5)


def test_parse_request_kind_defaults_when_missing() -> None:
    assert parse_request_kind(None) is WorkoutRequestKind.DEFAULT
    assert parse_request_kind("") is WorkoutRequestKind.DEFAULT


def test_parse_request_kind_maps_known_values() -> None:
    assert parse_request_kind("easy") is WorkoutRequestKind.EASY
    assert parse_request_kind("recovery") is WorkoutRequestKind.RECOVERY
    assert parse_request_kind("key") is WorkoutRequestKind.KEY


def test_parse_request_kind_rejects_unknown_values() -> None:
    with pytest.raises(ValueError, match="invalid request_kind"):
        parse_request_kind("nope")


# ---------------------------------------------------------------------------
# build_recommendation_context
# ---------------------------------------------------------------------------


def test_build_context_converts_five_k_best_into_runner_pace() -> None:
    context = build_recommendation_context(
        (),
        five_k_best="25:00",
        readiness=None,
        request_kind=WorkoutRequestKind.DEFAULT,
    )
    assert context.pace is not None
    assert context.pace.five_k_seconds == pytest.approx(25 * 60 / 5.0)


def test_build_context_leaves_pace_none_when_five_k_invalid() -> None:
    context = build_recommendation_context(
        (),
        five_k_best="",
        readiness=Readiness.NORMAL,
        request_kind=WorkoutRequestKind.EASY,
    )
    assert context.pace is None
    assert context.readiness is Readiness.NORMAL
    assert context.request_kind is WorkoutRequestKind.EASY


def test_build_context_passes_through_recent_workouts() -> None:
    completed = _completed_rows()
    context = build_recommendation_context(
        completed,
        five_k_best="25:00",
        readiness=None,
        request_kind=WorkoutRequestKind.DEFAULT,
    )
    assert context.recent_completed_workouts == completed


# ---------------------------------------------------------------------------
# completed_workouts_from_program
# ---------------------------------------------------------------------------


def _completed_rows() -> tuple:
    from runplan.domain.recommendations import CompletedWorkout

    return (
        CompletedWorkout(
            date=date(2026, 1, 1),
            form=EASY_RUN,
            distance_meters=5_000.0,
            duration_seconds=1_800,
        ),
    )


def test_completed_workouts_returns_empty_when_no_records() -> None:
    assert completed_workouts_from_program(deepcopy(_BASE_PROGRAM)) == ()


def test_completed_workouts_skips_planned_workouts() -> None:
    program = deepcopy(_BASE_PROGRAM)
    for workout in program["weeks"][0]["workouts"]:
        workout["tracking"] = {"status": "planned"}
    assert completed_workouts_from_program(program) == ()


def test_completed_workouts_includes_records_with_actual_block() -> None:
    program = deepcopy(_BASE_PROGRAM)
    program["weeks"][0]["workouts"][0]["tracking"] = {
        "status": "completed",
        "actual": {
            "distance_meters": 5_000,
            "duration_seconds": 1_800,
            "completed_at": "2026-01-05T08:00:00",
        },
    }
    rows = completed_workouts_from_program(program)
    assert len(rows) == 1
    assert rows[0].date == date(2026, 1, 5)
    assert rows[0].form is EASY_RUN
    assert rows[0].distance_meters == 5_000.0
    assert rows[0].duration_seconds == 1_800


def test_completed_workouts_falls_back_to_schedule_date() -> None:
    program = deepcopy(_BASE_PROGRAM)
    program["weeks"][0]["workouts"][0]["tracking"] = {
        "status": "completed",
        "actual": {"distance_meters": 5_000, "duration_seconds": 1_800},
    }
    rows = completed_workouts_from_program(program)
    assert len(rows) == 1
    # 2026-W01 starts on 2025-12-29
    assert rows[0].date == date(2025, 12, 29)


def test_completed_workouts_infers_tempo_form_for_paced_run() -> None:
    program = deepcopy(_BASE_PROGRAM)
    tempo = program["weeks"][1]["workouts"][0]
    tempo["tracking"] = {
        "status": "completed",
        "actual": {
            "distance_meters": 5_000,
            "duration_seconds": 1_500,
            "completed_at": "2026-01-13T08:00:00",
        },
    }
    rows = completed_workouts_from_program(program)
    assert len(rows) == 1
    assert rows[0].form is TEMPO_RUN


def test_completed_workouts_returns_empty_for_malformed_yaml() -> None:
    assert completed_workouts_from_program({"not": "a program"}) == ()


# ---------------------------------------------------------------------------
# week_key_forms_for
# ---------------------------------------------------------------------------


def test_week_key_forms_for_returns_tempo_in_target_week() -> None:
    program = deepcopy(_BASE_PROGRAM)
    forms = week_key_forms_for(program, 2)
    # Long runs are not structurally inferrable from steps alone, so only the
    # paced tempo workout contributes here.
    assert set(forms) == {"tempo_run"}


def test_week_key_forms_for_returns_empty_for_week_without_keys() -> None:
    program = deepcopy(_BASE_PROGRAM)
    assert week_key_forms_for(program, 1) == ()


def test_week_key_forms_for_excludes_completed_workouts() -> None:
    program = deepcopy(_BASE_PROGRAM)
    program["weeks"][1]["workouts"][0]["tracking"] = {"status": "completed"}
    assert "tempo_run" not in week_key_forms_for(program, 2)


def test_week_key_forms_for_unknown_week_returns_empty() -> None:
    program = deepcopy(_BASE_PROGRAM)
    assert week_key_forms_for(program, 99) == ()


def test_week_key_forms_for_includes_interval_workouts() -> None:
    program = deepcopy(_BASE_PROGRAM)
    program["weeks"][0]["workouts"].append(
        {
            "id": "intervals",
            "day": 4,
            "name": "Intervals",
            "steps": [
                {"warmup": {"distance": "1km"}},
                {
                    "repeat": {
                        "count": 4,
                        "steps": [
                            {"run": {"distance": "400m", "pace": "4:30 min/km"}},
                            {"recovery": {"time": "90s"}},
                        ],
                    }
                },
                {"cooldown": {"distance": "1km"}},
            ],
        }
    )
    forms = week_key_forms_for(program, 1)
    assert "interval_workout" in forms


def test_week_key_forms_for_ignores_recovery_and_easy_run() -> None:
    program = deepcopy(_BASE_PROGRAM)
    program["weeks"][1]["workouts"] = [
        {
            "id": "easy",
            "day": 1,
            "name": "Easy",
            "steps": [{"run": {"distance": "5km"}}],
        },
        {
            "id": "recovery",
            "day": 3,
            "name": "Recovery",
            "steps": [{"run": {"time": "20m"}}],
        },
    ]
    assert week_key_forms_for(program, 2) == ()
