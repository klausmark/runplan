import pytest

from runplan import (
    WorkoutDefinitionError,
    compile_steps,
    estimate_totals,
    format_totals,
    parse_distance,
    parse_pace,
    parse_step_end,
    step_summary,
)


@pytest.mark.parametrize(("value", "expected"), [("400m", 400), ("1.5km", 1500)])
def test_distance_with_unit_is_parsed(value: str, expected: float) -> None:
    assert parse_distance(value, "steps[1].distance") == expected


def test_short_m_form_means_minutes_unless_distance_is_explicit() -> None:
    assert parse_step_end("2m", "steps[1]") == ("time", 120)
    assert parse_step_end({"distance": "2m"}, "steps[1]") == ("distance", 2)


@pytest.mark.parametrize("value", ["400", "0m", 400])
def test_distance_without_valid_positive_unit_is_rejected(value: object) -> None:
    with pytest.raises(WorkoutDefinitionError):
        parse_distance(value, "steps[1].distance")


@pytest.mark.parametrize("action", ["warmup", "run", "recovery", "cooldown"])
def test_distance_step_compiles_to_garmin_distance_condition(action: str) -> None:
    step = compile_steps([{action: {"distance": "400m"}}])[0]

    assert step.endCondition["conditionTypeKey"] == "distance"
    assert step.endCondition["conditionTypeId"] == 3
    assert step.endConditionValue == 400


def test_warmup_and_cooldown_do_not_assume_walking() -> None:
    warmup, cooldown = compile_steps([{"warmup": "5m"}, {"cooldown": "5m"}])

    assert warmup.description == "Warm up"
    assert cooldown.description == "Cool down"


def test_unknown_translated_step_name_is_rejected() -> None:
    with pytest.raises(WorkoutDefinitionError, match="unknown step"):
        compile_steps([{"løb": "5m"}])


def test_totals_include_nested_time_and_distance() -> None:
    steps = [
        {"warmup": "5m"},
        {
            "repeat": {
                "count": 3,
                "steps": [
                    {"run": {"distance": "400m"}},
                    {"recovery": {"time": "1m"}},
                ],
            }
        },
        {"cooldown": {"distance": "1km"}},
    ]

    assert estimate_totals(steps) == (480, 2200)
    assert format_totals(steps) == "8 min + 2.2 km"
    assert "Run 400 m" in step_summary(steps)


def test_pace_range_parses_and_compiles_to_garmin_target() -> None:
    step = compile_steps([{"run": {"distance": "400m", "pace": "4:30-4:45 min/km"}}])[0]

    assert parse_pace("4:30-4:45 min/km", "steps[1].pace") == (270, 285)
    assert step.targetType["workoutTargetTypeKey"] == "pace.zone"
    assert step.targetType["workoutTargetTypeId"] == 6
    assert step.targetValueOne == pytest.approx(1000 / 285)
    assert step.targetValueTwo == pytest.approx(1000 / 270)


def test_step_summary_formats_pace() -> None:
    summary = step_summary([{"run": {"time": "5m", "pace": "5:00 min/km"}}])

    assert summary == "Run 5 min @ 5:00 min/km"


@pytest.mark.parametrize(
    "value", ["4.30 min/km", "4:60 min/km", "4:30 min/mile", "0:00 min/km", 270]
)
def test_invalid_pace_is_rejected(value: object) -> None:
    with pytest.raises(WorkoutDefinitionError):
        parse_pace(value, "steps[1].pace")


@pytest.mark.parametrize(
    "step",
    [
        {"run": {"distance": "1km", "pace": None}},
        {"run": {"distance": "1km", "tempo": "5:00 min/km", "pace": "5:00 min/km"}},
    ],
)
def test_invalid_compiled_pace_is_rejected(step: dict) -> None:
    with pytest.raises(WorkoutDefinitionError):
        compile_steps([step])
