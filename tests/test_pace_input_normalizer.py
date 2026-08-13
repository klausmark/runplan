from __future__ import annotations

import re

import pytest

from runplan.web import ASSET_DIR


def normalize_pace_side(side: str) -> str | None:
    trimmed = side.strip()
    if re.fullmatch(r"\d+", trimmed):
        return f"{int(trimmed)}:00"
    if re.fullmatch(r"\d+:[0-5]\d", trimmed):
        return trimmed
    if re.fullmatch(r"\d+(?:\.\d+)?", trimmed):
        total_seconds = round(float(trimmed) * 60)
        minutes, seconds = divmod(total_seconds, 60)
        return f"{minutes}:{seconds:02d}"
    return None


def normalize_pace_input(raw: str | None) -> str | None:
    text = (raw or "").strip()
    if not text:
        return None
    stripped = re.sub(r"\s*min\s*/\s*km\s*$", "", text, flags=re.IGNORECASE).strip()
    parts = [normalize_pace_side(side) for side in re.split(r"\s*-\s*", stripped)]
    if any(part is None for part in parts):
        return None
    for part in parts:
        minutes_str, seconds_str = part.split(":")
        minutes, seconds = int(minutes_str), int(seconds_str)
        if seconds >= 60 or minutes <= 0:
            return None
    return f"{'-'.join(parts)} min/km"


def test_normalize_pace_input_bare_minutes_gets_seconds_and_unit() -> None:
    assert normalize_pace_input("6") == "6:00 min/km"


def test_normalize_pace_input_minutes_and_seconds_gets_unit_only() -> None:
    assert normalize_pace_input("6:30") == "6:30 min/km"


def test_normalize_pace_input_decimal_is_rounded_to_nearest_second() -> None:
    assert normalize_pace_input("6.5") == "6:30 min/km"
    assert normalize_pace_input("6.25") == "6:15 min/km"
    assert normalize_pace_input("6.75") == "6:45 min/km"


def test_normalize_pace_input_strips_trailing_unit_in_any_case() -> None:
    assert normalize_pace_input("6:30 min/km") == "6:30 min/km"
    assert normalize_pace_input("6:30 Min/KM") == "6:30 min/km"
    assert normalize_pace_input("6:30  min  /  km") == "6:30 min/km"


def test_normalize_pace_input_handles_ranges() -> None:
    assert normalize_pace_input("6:30-6:45") == "6:30-6:45 min/km"
    assert normalize_pace_input("6-6:30") == "6:00-6:30 min/km"
    assert normalize_pace_input("6:30-6") == "6:30-6:00 min/km"
    assert normalize_pace_input("4:30-4:45 min/km") == "4:30-4:45 min/km"
    assert normalize_pace_input("6:00 - 6:30 min/km") == "6:00-6:30 min/km"


def test_normalize_pace_input_trims_surrounding_whitespace() -> None:
    assert normalize_pace_input("  6  ") == "6:00 min/km"


def test_normalize_pace_input_returns_none_for_empty_input() -> None:
    assert normalize_pace_input("") is None
    assert normalize_pace_input("   ") is None
    assert normalize_pace_input(None) is None


def test_normalize_pace_input_returns_none_for_invalid_seconds() -> None:
    assert normalize_pace_input("4:60") is None
    assert normalize_pace_input("4:60 min/km") is None


def test_normalize_pace_input_returns_none_for_zero_pace() -> None:
    assert normalize_pace_input("0") is None
    assert normalize_pace_input("0:00") is None
    assert normalize_pace_input("0:30") is None


def test_normalize_pace_input_returns_none_for_unrecognized_input() -> None:
    assert normalize_pace_input("fast") is None
    assert normalize_pace_input("4:30 min/mile") is None
    assert normalize_pace_input("6:") is None
    assert normalize_pace_input(":30") is None
    assert normalize_pace_input("-6") is None


def test_normalize_pace_input_returns_none_when_any_range_side_is_invalid() -> None:
    assert normalize_pace_input("6:30-fast") is None
    assert normalize_pace_input("0-6:30") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("6", "6:00 min/km"),
        ("6:30", "6:30 min/km"),
        ("6.5", "6:30 min/km"),
        ("6:30 min/km", "6:30 min/km"),
        ("6:30-6:45", "6:30-6:45 min/km"),
        ("6-6:30", "6:00-6:30 min/km"),
        ("4:30-4:45 min/km", "4:30-4:45 min/km"),
        ("  6  ", "6:00 min/km"),
        ("4:60", None),
        ("0", None),
        ("fast", None),
    ],
)
def test_normalize_pace_input_table(raw: str, expected: str | None) -> None:
    assert normalize_pace_input(raw) == expected


def test_pace_normalizer_is_implemented_in_javascript_assets() -> None:
    script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
    assert "function normalizePaceInput" in script
    assert "function normalizePaceSide" in script
    assert "settings.defaultPace" not in script
    assert 'id="user-settings-default-pace"' not in (
        (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    )
    assert 'id="user-settings-five-k-best"' in (
        (ASSET_DIR / "index.html").read_text(encoding="utf-8")
    )


def test_javascript_normalizer_body_matches_python_mirror_rules() -> None:
    script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
    js_normalize_side = re.search(
        r"function normalizePaceSide\(side\) \{(.*?)^\}",
        script,
        re.DOTALL | re.MULTILINE,
    )
    js_normalize = re.search(
        r"function normalizePaceInput\(raw\) \{(.*?)^\}",
        script,
        re.DOTALL | re.MULTILINE,
    )
    assert js_normalize_side is not None
    assert js_normalize is not None
    side_body = js_normalize_side.group(1)
    body = js_normalize.group(1)
    assert "Math.round" in side_body
    assert ":00" in side_body
    assert "[0-5]\\d" in side_body
    assert "min/km" in body
    assert "split" in body


def test_recipe_pace_range_inputs_are_normalised_client_side() -> None:
    script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
    assert "normalizePaceSide" in script
    read_index = script.index("function readRecipeParameters(")
    next_function = script.index("\nfunction ", read_index + 1)
    read_body = script[read_index:next_function]
    assert "normalizePaceSide" in read_body
    assert "recipe-dose-error" in script
    assert "hasPaceError" in script
