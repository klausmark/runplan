import json

from runplan.application.preview import build_preview
from runplan.application.results import SyncPlan
from runplan.presentation.json_output import format_json
from runplan.presentation.overview import format_overview
from tests.helpers import compiled_week


def test_overview_formats_structured_multi_week_preview() -> None:
    preview = build_preview([compiled_week(1), compiled_week(2)])

    output = format_overview(preview)

    assert "Program: characterization-plan" in output
    assert "Week 1" in output
    assert "Week 2" in output
    assert "Monday · Week 1 - Mixed" in output
    assert "Thursday · Week 1 - Easy" in output
    assert "Sunday · Week 2 - Long" in output
    assert "2026-12-28 · Week 1 - Mixed" not in output
    assert not output.lstrip().startswith("{")


def test_json_formatter_returns_machine_readable_selected_weeks() -> None:
    preview = build_preview([compiled_week(1), compiled_week(2)])

    document = json.loads(format_json(preview))

    assert document["programId"] == "characterization-plan"
    assert [week["week"] for week in document["weeks"]] == [1, 2]


def test_formatters_include_structured_sync_diff() -> None:
    plan = SyncPlan("characterization-plan", (1, 2))
    plan.add("reuse", "Kept workout", workout_id=10)
    plan.add("delete", "Old workout", workout_id=99)
    preview = build_preview([compiled_week(1), compiled_week(2)], plan)

    overview = format_overview(preview)
    document = json.loads(format_json(preview))

    assert "reuse: Kept workout" in overview
    assert "delete: Old workout" in overview
    assert [action["kind"] for action in document["sync"]["actions"]] == [
        "reuse",
        "delete",
    ]
