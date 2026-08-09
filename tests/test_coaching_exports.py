"""Tests for coaching-guide rendering in program exports."""

from __future__ import annotations

from pathlib import Path

from runplan import (
    CoachingGuide,
    CoachingSection,
    CoachingTip,
    GlossaryEntry,
    PaceChart,
    PaceColumn,
    PaceExample,
    PaceType,
    load_program_model,
)
from runplan.application.export import build_program_export
from runplan.domain.selectors import WeekSelection
from runplan.exporters.html import format_program_html
from runplan.exporters.markdown import format_program_markdown


def _load_nike(slug: str):
    import yaml

    raw = yaml.safe_load(
        (
            Path(__file__).parents[1]
            / "src"
            / "runplan"
            / "templates"
            / "programs"
            / f"{slug}.yaml"
        ).read_text(encoding="utf-8")
    )
    return load_program_model(raw)


def _build_export(slug: str):
    program = _load_nike(slug)
    selection = WeekSelection.parse("all")
    return build_program_export(program, selection)


def test_markdown_export_includes_coaching_guide_for_nike_5k() -> None:
    export = _build_export("nike-5k")
    md = format_program_markdown(export)
    assert "## Coaching guide" in md
    assert "A Great Coach" in md
    assert "It's Not Just About Running" in md
    assert "Speed Runs" in md
    assert "Long Runs" in md
    assert "Recovery Runs" in md
    assert "Rest Days" in md
    assert "Nike Run Club Pace Chart" in md
    assert "| Mile best | 5K best / avg mile |" in md
    assert "If your last 5K was 27:00" in md
    assert "Progression Run" in md
    assert "Intervals" in md
    assert "Fartlek" in md
    assert "Hills" in md
    assert "Tempo Run" in md
    assert "Best Pace" in md
    assert "If your schedule does not match" in md
    assert "If you are going to race" in md


def test_html_export_includes_coaching_table_and_examples() -> None:
    export = _build_export("nike-5k")
    html = format_program_html(export)
    assert '<section class="coaching">' in html
    assert "<table>" in html
    assert "<th>Mile best</th>" in html
    assert "<td>5:00</td>" in html
    assert "If your last 5K was 27:00" in html


def test_markdown_export_for_marathon_uses_six_column_pace_chart() -> None:
    export = _build_export("nike-marathon")
    md = format_program_markdown(export)
    lines = [line for line in md.splitlines() if line.startswith("| Mile best")]
    assert len(lines) == 1
    header_cells = [cell.strip() for cell in lines[0].strip("|").split("|")]
    assert len(header_cells) == 6
    assert "Recovery day pace" not in md.split("Coaching guide")[1]


def test_html_export_escapes_user_content_in_coaching() -> None:
    from dataclasses import replace

    raw_program = _load_nike("nike-5k")
    raw_program = replace(
        raw_program,
        coaching=replace(
            raw_program.coaching,
            intro_sections=(CoachingSection(title="A <script> title", body="Body & more"),),
        ),
    )
    selection = WeekSelection.parse("all")
    export = build_program_export(raw_program, selection)
    html = format_program_html(export)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
    assert "Body &amp; more" in html


def test_markdown_export_drops_empty_coaching_guide() -> None:
    from dataclasses import replace

    raw_program = _load_nike("nike-5k")
    raw_program = replace(raw_program, coaching=CoachingGuide())
    selection = WeekSelection.parse("all")
    export = build_program_export(raw_program, selection)
    md = format_program_markdown(export)
    assert "## Coaching guide" not in md


def test_build_export_preserves_coaching_reference() -> None:
    export = _build_export("nike-half-marathon")
    assert export.coaching is not None
    assert len(export.coaching.glossary) == 6
    assert any(entry.term == "Audio Guided Run" for entry in export.coaching.glossary)


def test_coaching_sections_helper_renders_full_payload() -> None:
    from dataclasses import replace

    guide = CoachingGuide(
        tagline="All four pillars",
        intro_sections=(CoachingSection(title="Intro", body="Hello there"),),
        weekly_workouts=(CoachingSection(title="Speed Runs", body="Run fast."),),
        plan_tips=(CoachingTip(title="Plan tip", body="", items=("Tip one", "Tip two")),),
        pace_chart=PaceChart(
            title="Pace Chart",
            intro="Read me first",
            headers=(
                PaceColumn(label="Mile", description="Best mile"),
                PaceColumn(label="5K", description="Best 5K"),
            ),
            rows=(("5:00", "17:05"), ("6:00", "20:15")),
            examples=(
                PaceExample(
                    title="Example row",
                    row=("6:00", "20:15"),
                    targets=("Run easy",),
                ),
            ),
        ),
        glossary=(GlossaryEntry(term="Tempo", definition="A hard pace."),),
        pace_types=(PaceType(name="Tempo Pace", effort="6 out of 10", description="Steady."),),
        things_to_know=("Listen to effort",),
        situational_advice=(CoachingTip(title="If you're tired", body="Rest."),),
    )
    raw_program = _load_nike("nike-5k")
    raw_program = replace(raw_program, coaching=guide)
    selection = WeekSelection.parse("all")
    export = build_program_export(raw_program, selection)
    md = format_program_markdown(export)
    assert "All four pillars" in md
    assert "| Mile | 5K |" in md
    assert "Tempo" in md
    assert "If you're tired" in md
