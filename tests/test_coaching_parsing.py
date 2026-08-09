"""Tests for the structured `coaching:` block of program YAML."""

from __future__ import annotations

from pathlib import Path

import pytest

from runplan import WorkoutDefinitionError
from runplan.parsing.coaching import parse_coaching

EXPECTED_KEYS = {
    "tagline",
    "intro_sections",
    "weekly_workouts",
    "plan_tips",
    "pace_chart",
    "glossary",
    "pace_types",
    "things_to_know",
    "situational_advice",
}


def test_parse_coaching_accepts_none() -> None:
    assert parse_coaching(None) is None


def test_parse_coaching_rejects_non_object() -> None:
    with pytest.raises(WorkoutDefinitionError, match="must be an object"):
        parse_coaching(["not", "an", "object"])


def test_parse_coaching_rejects_unknown_top_level_field() -> None:
    with pytest.raises(WorkoutDefinitionError, match="unknown field"):
        parse_coaching({"mystery": True})


def test_parse_coaching_minimal_payload() -> None:
    guide = parse_coaching({"tagline": "Just one line."})
    assert guide is not None
    assert guide.tagline == "Just one line."
    assert guide.intro_sections == ()
    assert guide.glossary == ()
    assert guide.pace_chart is None


def test_parse_coaching_intro_section_requires_title_and_body() -> None:
    with pytest.raises(WorkoutDefinitionError, match="must contain exactly 'title' and 'body'"):
        parse_coaching({"intro_sections": [{"title": "Only title"}]})


def test_parse_coaching_tip_must_contain_body_or_items() -> None:
    with pytest.raises(WorkoutDefinitionError, match="must contain 'body' or 'items'"):
        parse_coaching({"plan_tips": [{"title": "Empty"}]})
    with pytest.raises(WorkoutDefinitionError, match="use either 'body' or 'items', not both"):
        parse_coaching({"plan_tips": [{"title": "Both", "body": "b", "items": ["i"]}]})


def test_parse_coaching_pace_chart_requires_at_least_one_column() -> None:
    with pytest.raises(WorkoutDefinitionError, match="headers: must contain at least one column"):
        parse_coaching({"pace_chart": {"headers": [], "rows": [], "examples": []}})


def test_parse_coaching_pace_chart_row_length_must_match_headers() -> None:
    payload = {
        "pace_chart": {
            "headers": [{"label": "A", "description": "A"}, {"label": "B", "description": "B"}],
            "rows": [["only-one"]],
            "examples": [],
        }
    }
    with pytest.raises(WorkoutDefinitionError, match="expected 2 values, got 1"):
        parse_coaching(payload)


def test_parse_coaching_pace_chart_example_requires_full_row() -> None:
    payload = {
        "pace_chart": {
            "headers": [
                {"label": "A", "description": "A"},
                {"label": "B", "description": "B"},
            ],
            "rows": [["x", "y"]],
            "examples": [{"title": "t", "row": ["only-one"], "targets": ["tgt"]}],
        }
    }
    with pytest.raises(WorkoutDefinitionError, match=r"row: must be a list with 2 values, got 1"):
        parse_coaching(payload)


def test_parse_coaching_glossary_entry_shape() -> None:
    with pytest.raises(WorkoutDefinitionError, match="must contain 'term' and 'definition'"):
        parse_coaching({"glossary": [{"term": "only-term"}]})


def test_parse_coaching_pace_type_shape() -> None:
    with pytest.raises(
        WorkoutDefinitionError, match="must contain 'name', 'effort' and 'description'"
    ):
        parse_coaching({"pace_types": [{"name": "x", "effort": "x"}]})


def test_parse_coaching_location_is_precise() -> None:
    payload = {
        "plan_tips": [{"title": "  "}],
    }
    with pytest.raises(WorkoutDefinitionError, match=r"program\.coaching\.plan_tips\[1\]\.title"):
        parse_coaching(payload, "program.coaching")


def test_every_nike_template_carries_coaching_with_expected_sections() -> None:
    expected = {
        "nike-5k": {"columns": 7, "glossary": 5},
        "nike-10k": {"columns": 7, "glossary": 5},
        "nike-half-marathon": {"columns": 7, "glossary": 6},
        "nike-marathon": {"columns": 6, "glossary": 5},
    }
    for slug, expectations in expected.items():
        raw_path = (
            Path(__file__).parents[1]
            / "src"
            / "runplan"
            / "templates"
            / "programs"
            / f"{slug}.yaml"
        )
        import yaml

        raw = yaml.safe_load(raw_path.read_text(encoding="utf-8"))
        guide = parse_coaching(raw["program"].get("coaching"))
        assert guide is not None, slug
        assert guide.tagline, slug
        assert len(guide.intro_sections) >= 2, slug
        assert len(guide.weekly_workouts) == 4, slug
        assert len(guide.plan_tips) >= 3, slug
        assert guide.pace_chart is not None
        assert len(guide.pace_chart.headers) == expectations["columns"], slug
        assert guide.pace_chart.headers[1].label == "5K best / avg km", slug
        assert len(guide.pace_chart.rows) == 15, slug
        assert len(guide.glossary) == expectations["glossary"], slug
        assert len(guide.pace_types) == 6, slug
        assert len(guide.things_to_know) >= 3, slug
        assert len(guide.situational_advice) == 8, slug
