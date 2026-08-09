"""Parse the optional `coaching:` block of a program YAML document."""

from __future__ import annotations

from typing import Any

from ..domain.errors import WorkoutDefinitionError
from ..domain.models import (
    CoachingGuide,
    CoachingSection,
    CoachingTip,
    GlossaryEntry,
    PaceChart,
    PaceColumn,
    PaceExample,
    PaceType,
)


def parse_coaching(raw: Any, location: str = "program.coaching") -> CoachingGuide | None:
    """Parse the optional `coaching:` mapping into a typed guide."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(f"{location}: must be an object")
    known = {
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
    unknown = sorted(set(raw) - known)
    if unknown:
        raise WorkoutDefinitionError(
            f"{location}: unknown field {unknown[0]!r}; expected one of {sorted(known)}"
        )

    return CoachingGuide(
        tagline=_parse_text(raw.get("tagline"), f"{location}.tagline", required=False),
        intro_sections=tuple(
            _parse_section(item, f"{location}.intro_sections[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("intro_sections"), location, "intro_sections"), start=1
            )
        ),
        weekly_workouts=tuple(
            _parse_section(item, f"{location}.weekly_workouts[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("weekly_workouts"), location, "weekly_workouts"), start=1
            )
        ),
        plan_tips=tuple(
            _parse_tip(item, f"{location}.plan_tips[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("plan_tips"), location, "plan_tips"), start=1
            )
        ),
        pace_chart=_parse_pace_chart(raw.get("pace_chart"), f"{location}.pace_chart"),
        glossary=tuple(
            _parse_glossary_entry(item, f"{location}.glossary[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("glossary"), location, "glossary"), start=1
            )
        ),
        pace_types=tuple(
            _parse_pace_type(item, f"{location}.pace_types[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("pace_types"), location, "pace_types"), start=1
            )
        ),
        things_to_know=tuple(
            _parse_text(item, f"{location}.things_to_know[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("things_to_know"), location, "things_to_know"), start=1
            )
        ),
        situational_advice=tuple(
            _parse_tip(item, f"{location}.situational_advice[{index}]")
            for index, item in enumerate(
                _as_list(raw.get("situational_advice"), location, "situational_advice"), start=1
            )
        ),
    )


def _as_list(value: Any, location: str, field: str) -> list[Any]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise WorkoutDefinitionError(f"{location}.{field}: must be a list")
    return value


def _parse_text(value: Any, location: str, *, required: bool = True) -> str | None:
    if value is None:
        if required:
            return None
        return None
    if not isinstance(value, str):
        raise WorkoutDefinitionError(f"{location}: must be text")
    text = value.strip()
    if not text:
        raise WorkoutDefinitionError(f"{location}: text is empty")
    return text


def _parse_section(raw: Any, location: str) -> CoachingSection:
    if not isinstance(raw, dict) or len(raw) != 2 or "title" not in raw or "body" not in raw:
        raise WorkoutDefinitionError(f"{location}: must contain exactly 'title' and 'body'")
    title = _parse_text(raw["title"], f"{location}.title")
    body = _parse_text(raw["body"], f"{location}.body")
    return CoachingSection(title=title, body=body)


def _parse_tip(raw: Any, location: str) -> CoachingTip:
    if not isinstance(raw, dict) or "title" not in raw:
        raise WorkoutDefinitionError(f"{location}: must contain 'title'")
    extra = set(raw) - {"title", "body", "items"}
    if extra:
        raise WorkoutDefinitionError(
            f"{location}: unknown field {sorted(extra)[0]!r}; expected 'title', 'body' or 'items'"
        )
    title = _parse_text(raw["title"], f"{location}.title")
    body_value = raw.get("body")
    body = (
        _parse_text(body_value, f"{location}.body", required=False)
        if body_value is not None
        else None
    )
    items_value = raw.get("items")
    items: list[str] = []
    if items_value is not None:
        if not isinstance(items_value, list):
            raise WorkoutDefinitionError(f"{location}.items: must be a list")
        if body is not None:
            raise WorkoutDefinitionError(f"{location}: use either 'body' or 'items', not both")
        for index, item in enumerate(items_value, start=1):
            items.append(_parse_text(item, f"{location}.items[{index}]"))
    if body is None and not items:
        raise WorkoutDefinitionError(f"{location}: must contain 'body' or 'items'")
    return CoachingTip(title=title, body=body or "", items=tuple(items))


def _parse_pace_chart(raw: Any, location: str) -> PaceChart | None:
    if raw is None:
        return None
    if not isinstance(raw, dict):
        raise WorkoutDefinitionError(f"{location}: must be an object")
    extra = set(raw) - {"title", "intro", "headers", "rows", "examples"}
    if extra:
        raise WorkoutDefinitionError(f"{location}: unknown field {sorted(extra)[0]!r}")
    title = _parse_text(raw.get("title"), f"{location}.title") or "Pace Chart"
    intro = _parse_text(raw.get("intro"), f"{location}.intro", required=False) or ""
    headers_raw = _as_list(raw.get("headers"), location, "headers")
    if not headers_raw:
        raise WorkoutDefinitionError(f"{location}.headers: must contain at least one column")
    headers = tuple(
        _parse_pace_column(item, f"{location}.headers[{index}]")
        for index, item in enumerate(headers_raw, start=1)
    )
    column_count = len(headers)
    rows_raw = _as_list(raw.get("rows"), location, "rows")
    if not rows_raw:
        raise WorkoutDefinitionError(f"{location}.rows: must contain at least one row")
    rows: list[tuple[str, ...]] = []
    for row_index, row in enumerate(rows_raw, start=1):
        if not isinstance(row, list):
            raise WorkoutDefinitionError(f"{location}.rows[{row_index}]: must be a list")
        if len(row) != column_count:
            raise WorkoutDefinitionError(
                f"{location}.rows[{row_index}]: expected {column_count} values, got {len(row)}"
            )
        values: list[str] = []
        for col_index, cell in enumerate(row, start=1):
            values.append(_parse_text(cell, f"{location}.rows[{row_index}][{col_index}]"))
        rows.append(tuple(values))
    examples_raw = _as_list(raw.get("examples"), location, "examples")
    examples = tuple(
        _parse_pace_example(item, f"{location}.examples[{index}]", column_count)
        for index, item in enumerate(examples_raw, start=1)
    )
    return PaceChart(
        title=title,
        intro=intro,
        headers=headers,
        rows=tuple(rows),
        examples=examples,
    )


def _parse_pace_column(raw: Any, location: str) -> PaceColumn:
    if not isinstance(raw, dict) or "label" not in raw or "description" not in raw:
        raise WorkoutDefinitionError(f"{location}: must contain 'label' and 'description'")
    extra = set(raw) - {"label", "description"}
    if extra:
        raise WorkoutDefinitionError(f"{location}: unknown field {sorted(extra)[0]!r}")
    label = _parse_text(raw["label"], f"{location}.label")
    description = _parse_text(raw["description"], f"{location}.description")
    return PaceColumn(label=label, description=description)


def _parse_pace_example(raw: Any, location: str, column_count: int) -> PaceExample:
    if not isinstance(raw, dict) or "title" not in raw or "row" not in raw or "targets" not in raw:
        raise WorkoutDefinitionError(f"{location}: must contain 'title', 'row' and 'targets'")
    extra = set(raw) - {"title", "row", "targets"}
    if extra:
        raise WorkoutDefinitionError(f"{location}: unknown field {sorted(extra)[0]!r}")
    title = _parse_text(raw["title"], f"{location}.title")
    row_raw = raw["row"]
    if not isinstance(row_raw, list):
        raise WorkoutDefinitionError(f"{location}.row: must be a list")
    if len(row_raw) != column_count:
        raise WorkoutDefinitionError(
            f"{location}.row: must be a list with {column_count} values, got {len(row_raw)}"
        )
    row = tuple(
        _parse_text(value, f"{location}.row[{index}]")
        for index, value in enumerate(row_raw, start=1)
    )
    targets_raw = raw["targets"]
    if not isinstance(targets_raw, list) or not targets_raw:
        raise WorkoutDefinitionError(f"{location}.targets: must be a non-empty list")
    targets = tuple(
        _parse_text(value, f"{location}.targets[{index}]")
        for index, value in enumerate(targets_raw, start=1)
    )
    return PaceExample(title=title, row=row, targets=targets)


def _parse_glossary_entry(raw: Any, location: str) -> GlossaryEntry:
    if not isinstance(raw, dict) or "term" not in raw or "definition" not in raw:
        raise WorkoutDefinitionError(f"{location}: must contain 'term' and 'definition'")
    extra = set(raw) - {"term", "definition"}
    if extra:
        raise WorkoutDefinitionError(f"{location}: unknown field {sorted(extra)[0]!r}")
    term = _parse_text(raw["term"], f"{location}.term")
    definition = _parse_text(raw["definition"], f"{location}.definition")
    return GlossaryEntry(term=term, definition=definition)


def _parse_pace_type(raw: Any, location: str) -> PaceType:
    if (
        not isinstance(raw, dict)
        or "name" not in raw
        or "effort" not in raw
        or "description" not in raw
    ):
        raise WorkoutDefinitionError(f"{location}: must contain 'name', 'effort' and 'description'")
    extra = set(raw) - {"name", "effort", "description"}
    if extra:
        raise WorkoutDefinitionError(f"{location}: unknown field {sorted(extra)[0]!r}")
    name = _parse_text(raw["name"], f"{location}.name")
    effort = _parse_text(raw["effort"], f"{location}.effort")
    description = _parse_text(raw["description"], f"{location}.description")
    return PaceType(name=name, effort=effort, description=description)


__all__ = ["parse_coaching"]
