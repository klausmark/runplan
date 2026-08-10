"""Validate that every bundled Nike Run Club template loads and round-trips."""

from __future__ import annotations

import re
from datetime import date

import pytest

from runplan import (
    TEMPLATE_CATALOG,
    TemplateCopyError,
    TemplateMetadata,
    build_workout,
    compile_steps,
    copy_template,
    default_start_week,
    get_template,
    list_templates,
    load_program,
    load_program_model,
    template_yaml,
)
from runplan.domain.models import Program
from runplan.parsing.values import MAX_STEP_NOTE_LENGTH

EXPECTED_TEMPLATES = {
    "nike-5k": (5.0, "5K", 8),
    "nike-10k": (10.0, "10K", 8),
    "nike-half-marathon": (21.1, "Half Marathon", 14),
    "nike-marathon": (42.2, "Marathon", 18),
}


@pytest.fixture
def all_templates() -> list[TemplateMetadata]:
    return list_templates()


def test_catalog_lists_every_bundled_template() -> None:
    catalog_ids = {item.id for item in TEMPLATE_CATALOG}
    assert catalog_ids == set(EXPECTED_TEMPLATES)
    catalog = list_templates()
    assert [item.id for item in catalog] == [
        "nike-5k",
        "nike-10k",
        "nike-half-marathon",
        "nike-marathon",
    ]
    distances = [item.goal_distance_km for item in catalog]
    assert distances == sorted(distances)


@pytest.mark.parametrize("template_id", list(EXPECTED_TEMPLATES))
def test_template_metadata_matches_expected_layout(template_id: str) -> None:
    item = get_template(template_id)
    distance_km, label, weeks = EXPECTED_TEMPLATES[template_id]
    assert item.id == template_id
    assert item.goal_distance_km == distance_km
    assert item.distance_label == label
    assert item.duration_weeks == weeks
    assert item.sessions_per_week == 5
    assert item.source == "Nike Run Club"
    assert item.default_long_run_day in range(1, 8)
    assert item.has_race_week is True
    assert item.short_name
    assert item.name


@pytest.mark.parametrize("template_id", list(EXPECTED_TEMPLATES))
def test_template_loads_and_builds_every_week(template_id: str) -> None:
    item = get_template(template_id)

    def resolver(_label: str) -> tuple[float, float]:
        return (295.0, 305.0)

    for week_number in range(1, item.duration_weeks + 1):
        normalized = load_program(_load_template_raw(template_id), selected_week=week_number)
        for workout in normalized["workouts"]:
            assert not re.match(r"^Week\s+\d+\s+-", workout["name"])
            assert workout["steps"], workout
            assert compile_steps(workout["steps"], resolve_pace_type=resolver)
            build_workout(workout, resolve_pace_type=resolver)


@pytest.mark.parametrize("template_id", list(EXPECTED_TEMPLATES))
def test_template_round_trips_through_loader(template_id: str) -> None:
    raw = _load_template_raw(template_id)
    program = load_program_model(raw)
    assert program.id == template_id
    assert len(program.weeks) == EXPECTED_TEMPLATES[template_id][2]
    for week in program.weeks:
        assert len(week.workouts) == 5
        days = [workout.day for workout in week.workouts]
        assert days == sorted(days)
        assert len(set(days)) == 5
        for workout in week.workouts:
            assert workout.name
            for step in workout.steps:
                _assert_step_well_formed(step)


def _assert_step_well_formed(step) -> None:
    if step.action == "repeat":
        assert step.count and step.count > 0
        assert step.steps
        for child in step.steps:
            _assert_step_well_formed(child)
        return
    assert step.end_kind in {"time", "distance"}
    assert step.end_value and step.end_value > 0
    if step.note is not None:
        assert 0 < len(step.note) <= MAX_STEP_NOTE_LENGTH


def _load_template_raw(template_id: str) -> dict:
    from runplan.templates.catalog import load_template_document

    return load_template_document(template_id)


@pytest.mark.parametrize("template_id", list(EXPECTED_TEMPLATES))
def test_copy_template_assigns_unique_id_per_start_week(template_id: str) -> None:
    copy_a = copy_template(template_id, start_week="2026-W32")
    copy_b = copy_template(template_id, start_week="2027-W01")
    assert copy_a["program"]["id"] == f"{template_id}-2026-w32"
    assert copy_b["program"]["id"] == f"{template_id}-2027-w01"
    assert copy_a["program"]["start_week"] == "2026-W32"
    assert copy_b["program"]["start_week"] == "2027-W01"


def test_copy_template_default_start_week_is_a_future_monday() -> None:
    today = date(2026, 6, 10)
    assert default_start_week(today) == "2026-W25"


def test_copy_template_unknown_id_raises_with_helpful_message() -> None:
    with pytest.raises(TemplateCopyError, match="Unknown template"):
        copy_template("not-a-template")


def test_copy_template_rejects_malformed_start_week() -> None:
    with pytest.raises(TemplateCopyError, match="start_week"):
        copy_template("nike-5k", start_week="2026-W99")


def test_template_yaml_is_valid_runplan_yaml() -> None:
    payload = template_yaml("nike-10k", start_week="2026-W32")
    assert "program:" in payload
    assert "id: nike-10k-2026-w32" in payload
    assert "weeks:" in payload
    program = load_program_model(_yaml_to_dict(payload))
    assert program.id == "nike-10k-2026-w32"
    assert program.start_week == "2026-W32"
    assert len(program.weeks) == 8


def _yaml_to_dict(text: str) -> dict:
    import yaml

    return yaml.safe_load(text)


def test_copied_program_is_typed_and_loadable() -> None:
    from runplan.templates.copy import copied_program

    program: Program = copied_program("nike-half-marathon", start_week="2026-W30")
    assert program.id == "nike-half-marathon-2026-w30"
    assert len(program.weeks) == 14
    assert program.weeks[0].workouts[0].schedule_date.isoformat() == "2026-07-20"
