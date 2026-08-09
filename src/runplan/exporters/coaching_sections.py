"""Renderer-independent coaching-guide sections for program exports."""

from __future__ import annotations

from collections.abc import Iterable

from ..domain.models import (
    CoachingGuide,
    CoachingSection,
    CoachingTip,
    GlossaryEntry,
    PaceChart,
    PaceType,
)


def coaching_lines(guide: CoachingGuide) -> list[tuple[str, list[str]]]:
    """Return a sequence of (title, markdown_lines) sections for one guide."""
    if not _has_any_content(guide):
        return []
    sections: list[tuple[str, list[str]]] = []
    if guide.tagline:
        sections.append(("__eyebrow__", [guide.tagline]))
    for entry in guide.intro_sections:
        sections.append((entry.title, _section_lines(entry)))
    for entry in guide.weekly_workouts:
        sections.append((entry.title, _section_lines(entry)))
    for entry in guide.plan_tips:
        sections.append((entry.title, _tip_lines(entry)))
    if guide.pace_chart is not None:
        sections.append((guide.pace_chart.title, _pace_chart_lines(guide.pace_chart)))
    if guide.glossary:
        sections.append(("Types of Runs", _glossary_lines(guide.glossary)))
    if guide.pace_types:
        sections.append(("Types of Pace", _pace_types_lines(guide.pace_types)))
    if guide.things_to_know:
        sections.append(("Things to Know", [""] + _bullet_lines(guide.things_to_know)))
    if guide.situational_advice:
        sections.append(("If You...", _situational_advice_lines(guide.situational_advice)))
    return sections


def _has_any_content(guide: CoachingGuide) -> bool:
    return any(
        [
            guide.tagline,
            guide.intro_sections,
            guide.weekly_workouts,
            guide.plan_tips,
            guide.pace_chart,
            guide.glossary,
            guide.pace_types,
            guide.things_to_know,
            guide.situational_advice,
        ]
    )


def _section_lines(entry: CoachingSection) -> list[str]:
    return ["", *entry.body.splitlines()]


def _tip_lines(entry: CoachingTip) -> list[str]:
    if entry.items:
        return ["", *_bullet_lines(entry.items)]
    return _section_lines(CoachingSection(title=entry.title, body=entry.body))


def _bullet_lines(items: Iterable[str]) -> list[str]:
    return [f"- {item}" for item in items]


def _glossary_lines(items: Iterable[GlossaryEntry]) -> list[str]:
    lines: list[str] = [""]
    for entry in items:
        lines.append(f"- **{entry.term}** — {entry.definition}")
    return lines


def _pace_types_lines(items: Iterable[PaceType]) -> list[str]:
    lines: list[str] = [""]
    for pace in items:
        lines.append(f"- **{pace.name}** ({pace.effort}) — {pace.description}")
    return lines


def _pace_chart_lines(chart: PaceChart) -> list[str]:
    lines: list[str] = [""]
    if chart.intro:
        lines.extend(chart.intro.splitlines())
        lines.append("")
    header_cells = [col.label for col in chart.headers]
    lines.append("| " + " | ".join(header_cells) + " |")
    lines.append("|" + "|".join("---" for _ in chart.headers) + "|")
    for row in chart.rows:
        lines.append("| " + " | ".join(row) + " |")
    if chart.examples:
        lines.append("")
        lines.append("**Worked examples**")
        lines.append("")
        for example in chart.examples:
            lines.append(
                f"- *{example.title}* — row: "
                + ", ".join(f"{header_cells[i]} = {value}" for i, value in enumerate(example.row))
            )
            for target in example.targets:
                lines.append(f"  - {target}")
    return lines


def _situational_advice_lines(items: Iterable[CoachingTip]) -> list[str]:
    lines: list[str] = [""]
    for entry in items:
        lines.append(f"- **{entry.title}** — {entry.body}")
    return lines
