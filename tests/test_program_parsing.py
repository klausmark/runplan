import re
from pathlib import Path

import pytest

from runplan import (
    WorkoutDefinitionError,
    build_workout,
    compile_steps,
    load_definition,
    load_program,
    parse_duration,
)
from tests.helpers import normalized_program, program_data

PROJECT_DIR = Path(__file__).resolve().parents[1]
PROGRAM_FIXTURES = PROJECT_DIR / "tests" / "fixtures" / "programs"


@pytest.mark.parametrize("value", ["2026-01-03", "2026-W00", "2026-W54", 202631])
def test_start_week_must_be_a_valid_iso_calendar_week(value) -> None:
    raw = program_data()
    raw["program"]["start_week"] = value

    with pytest.raises(WorkoutDefinitionError, match="start_week"):
        load_program(raw, selected_week=1)


def test_legacy_start_date_is_not_accepted() -> None:
    raw = program_data()
    raw["program"]["start_date"] = raw["program"].pop("start_week")

    with pytest.raises(WorkoutDefinitionError, match="start_week"):
        load_program(raw, selected_week=1)


def test_normalizes_program_and_dates_across_year_boundary() -> None:
    program = normalized_program(selected_week=2)

    assert program["program_id"] == "characterization-plan"
    assert program["start_date"] == "2026-12-28"
    assert program["start_week"] == "2026-W53"
    assert program["week"] == 2
    assert program["workouts"][0]["schedule_date"] == "2027-01-10"
    assert [week["number"] for week in program["weeks"]] == [1, 2]


def test_rejects_non_contiguous_weeks_with_location() -> None:
    raw = program_data()
    raw["weeks"][1]["week"] = 3

    with pytest.raises(
        WorkoutDefinitionError,
        match=r"weeks: week numbers must be contiguous from 1; found \[1, 3\]",
    ):
        load_program(raw, selected_week=1)


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda raw: raw["weeks"][0]["workouts"][1].update(id="mixed"), "ID 'mixed'"),
        (lambda raw: raw["weeks"][0]["workouts"][1].update(day=1), "day 1 is already"),
        (lambda raw: raw["weeks"][0]["workouts"][0].update(day=5), "must be sorted by day"),
    ],
    ids=["duplicate-id", "duplicate-day", "unsorted-day"],
)
def test_rejects_invalid_workout_identity_and_order(mutate, message) -> None:
    raw = program_data()
    mutate(raw)

    with pytest.raises(WorkoutDefinitionError, match=message):
        load_program(raw, selected_week=1)


def test_allows_workout_names_to_repeat_across_weeks() -> None:
    raw = program_data()
    raw["weeks"][1]["workouts"][0]["name"] = raw["weeks"][0]["workouts"][0]["name"]

    load_program(raw, selected_week=1)


@pytest.mark.parametrize("value", [None, "A", "TOO-LONG-123", "not valid", "HCA_26"])
def test_short_name_is_required_and_compact(value) -> None:
    raw = program_data()
    raw["program"]["short_name"] = value

    with pytest.raises(WorkoutDefinitionError, match="short_name"):
        load_program(raw, selected_week=1)


def test_rejects_unknown_selected_week() -> None:
    with pytest.raises(WorkoutDefinitionError, match="Program does not contain week 9"):
        load_program(program_data(), selected_week=9)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (30, 30),
        ("30s", 30),
        ("2m", 120),
        ("1m30s", 90),
        ("1.5m", 90),
        ("00:30", 30),
        ("02:30", 150),
        ("01:02:03", 3723),
    ],
)
def test_duration_formats_remain_backward_compatible(value, expected) -> None:
    assert parse_duration(value, "steps[1]") == expected


def test_nested_step_error_keeps_precise_location() -> None:
    steps = [{"repeat": {"count": 2, "steps": [{"run": {"distance": "400"}}]}}]

    with pytest.raises(
        WorkoutDefinitionError,
        match=r"steps\[1\]\.steps\[1\]\.distance: invalid distance",
    ):
        compile_steps(steps)


def test_danish_yaml_field_names_are_rejected() -> None:
    raw = program_data()
    raw["uger"] = raw.pop("weeks")

    with pytest.raises(WorkoutDefinitionError, match="Field 'weeks'"):
        load_program(raw, selected_week=1)


def test_every_bundled_program_loads_and_builds_every_week() -> None:
    paths = sorted(PROGRAM_FIXTURES.glob("*.yaml")) + sorted(
        (PROJECT_DIR / "docs" / "examples").glob("*.yaml")
    )
    assert len(paths) >= 4

    for path in paths:
        first = load_definition(path)
        assert first["program_short_name"], path.name
        for week in first["weeks"]:
            selected = load_definition(path, selected_week=week["number"])
            for workout in selected["workouts"]:
                assert not re.match(r"^Week\s+\d+\s+-", workout["name"]), path.name
                build_workout(workout)


def test_fictional_marathon_calendar_preserves_key_dates() -> None:
    source = PROGRAM_FIXTURES / "avery-example-marathon.yaml"
    first = load_definition(source, selected_week=1)
    last = load_definition(source, selected_week=3)

    assert first["start_week"] == "2027-W10"
    assert first["workouts"][0]["schedule_date"] == "2027-03-08"
    assert first["workouts"][0]["day"] == 1
    assert last["workouts"][-1]["schedule_date"] == "2027-03-27"
    assert last["workouts"][-1]["day"] == 6


def test_maintained_yaml_and_documentation_use_english_schema_keys() -> None:
    maintained = [
        *PROGRAM_FIXTURES.glob("*.yaml"),
        *(PROJECT_DIR / "docs" / "examples").glob("*.yaml"),
        PROJECT_DIR / "README.md",
        PROJECT_DIR / "docs" / "program-prompt.md",
        PROGRAM_FIXTURES / "avery-example-marathon.md",
    ]
    danish_key = re.compile(
        r"(?:^\s*|[{,]\s*)(?:navn|beskrivelse|startdato|uger|uge|fokus|dag|"
        r"trin|opvarmning|løb|gå|afslutning|gentag|antal|tid|tempo):",
        re.MULTILINE,
    )

    for path in maintained:
        assert danish_key.search(path.read_text(encoding="utf-8")) is None, path.name


def test_maintained_user_facing_content_has_no_danish_characters() -> None:
    maintained = [
        PROJECT_DIR / "README.md",
        PROJECT_DIR / "PLAN.md",
        PROGRAM_FIXTURES / "morgan-example-5k.yaml",
        PROGRAM_FIXTURES / "riley-example-5k.yaml",
        PROGRAM_FIXTURES / "avery-example-marathon.yaml",
        PROGRAM_FIXTURES / "avery-example-marathon.md",
        *sorted((PROJECT_DIR / "docs").rglob("*.md")),
        *sorted((PROJECT_DIR / "docs" / "examples").glob("*.yaml")),
    ]

    for path in maintained:
        assert re.search(r"[æøåÆØÅ]", path.read_text(encoding="utf-8")) is None, path.relative_to(
            PROJECT_DIR
        )
