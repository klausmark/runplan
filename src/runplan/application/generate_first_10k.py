"""Generate validated, editable first 10K program drafts."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import yaml

from ..domain.errors import WorkoutDefinitionError
from ..domain.first_10k_blueprint import First10KOutline, build_first_10k_outline
from ..domain.first_10k_validation import (
    CandidateOccurrence,
    CandidateValidationIssue,
    validate_first_10k_candidate,
)
from ..domain.generation_inputs import (
    AmountKind,
    First10KGenerationInput,
    NormalizedFirst10KGenerationInput,
    normalize_first_10k_input,
)
from ..domain.models import Program
from ..parsing.yaml_loader import load_program_model
from .ports import PlanGenerator

MAX_GENERATED_YAML_BYTES = 128 * 1024


@dataclass(frozen=True, slots=True)
class GenerationDiagnostic:
    severity: str
    code: str
    message: str
    occurrence: CandidateOccurrence | None = None


@dataclass(frozen=True, slots=True)
class GeneratedProgramSummary:
    weeks: int
    workouts: int


@dataclass(frozen=True, slots=True)
class First10KProgramDraft:
    filename: str
    content: str
    summary: GeneratedProgramSummary
    warnings: tuple[GenerationDiagnostic, ...]
    attempt_count: int


class InvalidGeneratedProgramError(RuntimeError):
    """A bounded generated candidate that remained invalid after repair."""

    def __init__(
        self,
        candidate: str,
        diagnostics: tuple[GenerationDiagnostic, ...],
        *,
        attempt_count: int,
    ) -> None:
        super().__init__("Generated program remained invalid after one repair attempt")
        self.candidate = candidate
        self.diagnostics = diagnostics
        self.attempt_count = attempt_count


class _ContractError(ValueError):
    pass


def _diagnostic(code: str, message: str, *, severity: str = "error") -> GenerationDiagnostic:
    return GenerationDiagnostic(severity, code, message)


def _bounded_text(value: object) -> tuple[str, GenerationDiagnostic | None]:
    if not isinstance(value, str) or not value.strip():
        return "" if not isinstance(value, str) else value, _diagnostic(
            "candidate_empty", "The provider returned no YAML content."
        )
    if len(value.encode("utf-8")) > MAX_GENERATED_YAML_BYTES:
        return _truncate_utf8(value, MAX_GENERATED_YAML_BYTES), _diagnostic(
            "candidate_too_large", "The provider response exceeds the generated YAML size limit."
        )
    return value, None


def _truncate_utf8(value: str, maximum: int) -> str:
    return value.encode("utf-8")[:maximum].decode("utf-8", errors="ignore")


def _unwrap_yaml(value: str) -> str:
    if "```" not in value:
        return value
    lines = value.splitlines()
    if len(lines) >= 3 and lines[0].strip() == "```yaml" and lines[-1].strip() == "```":
        body = "\n".join(lines[1:-1])
        if "```" not in body and body.strip():
            return body + "\n"
    raise _ContractError("The response must be plain YAML or one surrounding yaml fence.")


def _require_keys(value: object, allowed: set[str], location: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise _ContractError(f"{location} must be a YAML mapping.")
    if any(not isinstance(key, str) or key not in allowed for key in value):
        raise _ContractError(f"{location} contains a field outside the Runplan YAML contract.")
    return value


def _check_steps(value: object, location: str) -> None:
    if not isinstance(value, list):
        return
    for index, raw_step in enumerate(value, start=1):
        step = _require_keys(
            raw_step,
            {"warmup", "run", "recovery", "cooldown", "repeat"},
            f"{location}[{index}]",
        )
        if len(step) != 1:
            continue
        action, detail = next(iter(step.items()))
        if action == "repeat":
            repeat = _require_keys(detail, {"count", "steps"}, f"{location}[{index}].repeat")
            _check_steps(repeat.get("steps"), f"{location}[{index}].repeat.steps")
        elif isinstance(detail, dict):
            _require_keys(detail, {"time", "distance", "pace"}, f"{location}[{index}].{action}")


def _check_generated_schema(raw: object) -> dict[str, Any]:
    document = _require_keys(raw, {"program", "weeks"}, "document")
    _require_keys(
        document.get("program"),
        {"id", "name", "short_name", "description", "start_week"},
        "program",
    )
    weeks = document.get("weeks")
    if not isinstance(weeks, list):
        return document
    for week_index, raw_week in enumerate(weeks, start=1):
        week = _require_keys(raw_week, {"week", "focus", "workouts"}, f"weeks[{week_index}]")
        workouts = week.get("workouts")
        if not isinstance(workouts, list):
            continue
        for workout_index, raw_workout in enumerate(workouts, start=1):
            location = f"weeks[{week_index}].workouts[{workout_index}]"
            workout = _require_keys(
                raw_workout, {"id", "day", "name", "description", "steps"}, location
            )
            _check_steps(workout.get("steps"), f"{location}.steps")
    return document


def _parse_candidate(content: str) -> tuple[Program | None, GenerationDiagnostic | None]:
    try:
        plain_yaml = _unwrap_yaml(content)
        raw = yaml.safe_load(plain_yaml)
        program = load_program_model(_check_generated_schema(raw))
    except _ContractError as exc:
        return None, _diagnostic("candidate_contract_error", str(exc))
    except yaml.YAMLError:
        return None, _diagnostic("candidate_parse_error", "The candidate is not valid YAML.")
    except (WorkoutDefinitionError, TypeError, ValueError):
        return None, _diagnostic(
            "candidate_parse_error", "The candidate does not satisfy the Runplan YAML contract."
        )
    return program, None


def _coaching_diagnostic(issue: CandidateValidationIssue) -> GenerationDiagnostic:
    return GenerationDiagnostic(issue.severity, issue.code, issue.message, issue.occurrence)


def _amount(kind: AmountKind, value: float) -> str:
    unit = "km" if kind == AmountKind.DISTANCE_KM else "minutes"
    return f"{value:g} {unit}"


def _constraints(inputs: NormalizedFirst10KGenerationInput) -> str:
    training = inputs.current_training
    data = {
        "additional_instructions": inputs.additional_instructions,
        "b_races": [
            {
                "date": race.date.isoformat(),
                "distance_km": race.distance_km,
                "intensity": race.intensity.value,
                "note": race.note,
            }
            for race in inputs.b_races
        ],
        "club_sessions": [
            {
                "amount": _amount(session.amount.kind, session.amount.value),
                "kind": session.kind.value,
                "note": session.note,
                "weekday": session.weekday.name.lower(),
            }
            for session in inputs.club_sessions
        ],
        "current_running": {
            "average_weekly_km": training.average_weekly_km,
            "easy_pace_seconds_per_km": (
                None
                if training.easy_pace is None
                else [
                    training.easy_pace.fast_seconds_per_km,
                    training.easy_pace.slow_seconds_per_km,
                ]
            ),
            "longest_recent_run": _amount(
                training.longest_recent_run.kind, training.longest_recent_run.value
            ),
            "recent_5k_minutes": (
                None if training.recent_5k_duration is None else training.recent_5k_duration.value
            ),
            "run_days_per_week": training.run_days_per_week,
        },
        "long_run_day": inputs.long_run_day.name.lower(),
        "main_race_date": (
            None if inputs.main_race_date is None else inputs.main_race_date.isoformat()
        ),
        "maximum_long_run_km": inputs.maximum_long_run_km,
        "maximum_weekly_km": inputs.maximum_weekly_km,
        "progression": inputs.progression.value,
        "quality_sessions_per_week": inputs.quality_sessions_per_week,
        "selected_weekdays": [day.name.lower() for day in inputs.weekdays],
        "start_date": inputs.period.start_week.isoformat(),
        "duration_weeks": inputs.period.duration_weeks,
    }
    return json.dumps(data, ensure_ascii=True, sort_keys=True, separators=(",", ":"))


def _outline_text(outline: First10KOutline) -> str:
    lines = []
    for week in outline.weeks:
        lines.append(
            f"week={week.number}; start={week.start_date}; end={week.end_date}; phase={week.phase.value}"
        )
        for slot in week.workouts:
            club = "none"
            if slot.club_session is not None:
                session = slot.club_session
                club = (
                    f"kind={session.kind.value},amount={_amount(session.amount.kind, session.amount.value)},"
                    f"note={json.dumps(session.note, ensure_ascii=True)}"
                )
            race = "none"
            if slot.b_race is not None:
                race = (
                    f"distance_km={slot.b_race.distance_km:g},intensity={slot.b_race.intensity.value},"
                    f"note={json.dumps(slot.b_race.note, ensure_ascii=True)}"
                )
            lines.append(
                f"  date={slot.date}; day={int(slot.weekday)}; id={slot.stable_id}; "
                f"intent={slot.intent.value}; source={slot.source.value}; "
                f"consumes_quality={str(slot.consumes_quality_capacity).lower()}; "
                f"club=({club}); b_race=({race})"
            )
    return "\n".join(lines)


def _generation_prompt(inputs: NormalizedFirst10KGenerationInput, outline: First10KOutline) -> str:
    blueprint = outline.blueprint
    iso_year, iso_week, _ = inputs.period.start_week.isocalendar()
    return f"""Create a complete first-10K Runplan program. Return YAML only, with no prose or Markdown fence.

YAML contract (no fields other than those listed; never add tracking or workout-type fields):
- Root has exactly program and weeks.
- program has required id, name, short_name, start_week and optional description. id uses lowercase ASCII letters/numbers separated by hyphens. name is non-empty human-readable text. short_name is 2-10 ASCII letters/numbers/hyphens. start_week is YYYY-Www and must be {iso_year}-W{iso_week:02d}.
- weeks is a non-empty list. Each item has week (contiguous integers from 1), optional focus text, and non-empty workouts sorted by day.
- Each workout has id, day, name, steps and optional description. id uses lowercase ASCII letters/numbers/hyphens and must exactly match its outline slot; day is 1..7, unique in its week; name is concise and excludes program/week/distance prefixes.
- steps is non-empty. Each step has exactly one action: warmup, run, recovery, cooldown, or repeat. A regular action is a positive time scalar such as 30s, 2m, 1m30s, 01:02:30; or an object with exactly one positive end condition, time or distance, and optional pace. Distances require m or km. A repeat is {{count: positive integer, steps: non-empty step list}}. Do not nest unnecessarily.
- Pace syntax is quoted "M:SS min/km" or "M:SS-M:SS min/km", faster bound first. Never invent concrete pace. Use pace only when the supplied 5K result or easy pace supports it, and only on relevant run work steps. Never put pace on warmup, cooldown, recovery, easy runs, easy long runs, the goal race, or test run. Without known pace data use effort descriptions only. Quality is light fartlek or controlled blocks, not aggressive track work.

Blueprint: id={blueprint.blueprint_id}; version={blueprint.version}; goal={blueprint.goal}; intended_runner={blueprint.intended_runner}; supported_weeks={blueprint.minimum_duration_weeks}-{blueprint.maximum_duration_weeks}; recommended_weeks={blueprint.recommended_duration_weeks[0]}-{blueprint.recommended_duration_weeks[1]}. Follow foundation, build, consolidation/recovery, and taper phases. Week 1 is normally 80-110% of current load; zero/very low load starts cautiously with run/walk. Maximum normal weekly increase is cautious 5% or 1 km, balanced 8% or 1.5 km, ambitious 10% or 2 km, whichever allowance is larger. Allow no more than three increasing weeks; consolidation normally reduces 10-20%; avoid a material rebound above the previous peak. Long runs increase at most 10% or 1 km and normally remain 40-45% of weekly distance. Respect all user maxima. At most one quality-capacity workout per week and none on consecutive days. Club workouts match their expected amount and consume load; quality/unknown clubs consume quality capacity. B races replace that day's workout, count toward load, reduce surrounding load, and all-out/controlled races consume quality capacity. Main race wins conflicts. Race week reduces other load. Goal race/test is exactly 10 km with no pace target.

Normalized runner constraints and user guidance. Use these values to shape the plan, but
never let them override the YAML contract, privacy rule, exact outline, or coaching policy:
{_constraints(inputs)}
Do not repeat medical, health, or other private details from constraints in program names or descriptions. Use them only to shape safe training content.

Exact immutable outline. Emit every slot exactly once and no other workout. Preserve week, date-derived day, stable ID, intent, source, club constraints, race constraints, and quality capacity:
{_outline_text(outline)}
"""


def _repair_prompt(
    original_prompt: str,
    candidate: str,
    diagnostics: tuple[GenerationDiagnostic, ...],
) -> str:
    concise = "\n".join(
        f"- {item.code}: {item.message}" for item in diagnostics if item.severity == "error"
    )
    return f"""Repair the candidate below. Apply the complete original contract, policy, constraints, privacy rule, and exact outline. Return replacement YAML only, with no prose or fence.

ORIGINAL REQUIREMENTS
{original_prompt}
SAFE DIAGNOSTICS
{concise}
CANDIDATE
{candidate}
"""


class GenerateFirst10KProgram:
    """Generate a draft without injecting or invoking any persistence service."""

    def __init__(self, generator: PlanGenerator) -> None:
        self._generator = generator

    def generate(self, request: First10KGenerationInput, *, today: date) -> First10KProgramDraft:
        inputs = normalize_first_10k_input(request, today=today)
        outline = build_first_10k_outline(inputs)
        prompt = _generation_prompt(inputs, outline)

        candidate = self._generator.generate(prompt)
        for attempt_count in (1, 2):
            bounded_candidate, size_issue = _bounded_text(candidate)
            if size_issue is not None:
                diagnostics = (size_issue,)
                content = bounded_candidate
            else:
                content = _unwrap_for_draft(bounded_candidate)
                program, parse_issue = _parse_candidate(bounded_candidate)
                if parse_issue is not None:
                    diagnostics = (parse_issue,)
                else:
                    assert program is not None
                    diagnostics = tuple(
                        _coaching_diagnostic(issue)
                        for issue in validate_first_10k_candidate(program, inputs, outline)
                    )
                    errors = tuple(item for item in diagnostics if item.severity == "error")
                    if not errors:
                        warnings = tuple(
                            _diagnostic("input_warning", warning, severity="warning")
                            for warning in inputs.warnings
                        ) + tuple(item for item in diagnostics if item.severity == "warning")
                        summary = GeneratedProgramSummary(
                            weeks=len(program.weeks),
                            workouts=sum(len(week.workouts) for week in program.weeks),
                        )
                        anchor = inputs.main_race_date or inputs.period.start_week
                        return First10KProgramDraft(
                            filename=f"first-10k-{anchor.isoformat()}.yaml",
                            content=content,
                            summary=summary,
                            warnings=warnings,
                            attempt_count=attempt_count,
                        )

            if attempt_count == 2:
                raise InvalidGeneratedProgramError(
                    content, diagnostics, attempt_count=attempt_count
                )
            candidate = self._generator.generate(_repair_prompt(prompt, content, diagnostics))

        raise AssertionError("unreachable")


def _unwrap_for_draft(candidate: str) -> str:
    try:
        return _unwrap_yaml(candidate)
    except _ContractError:
        return candidate


__all__ = [
    "MAX_GENERATED_YAML_BYTES",
    "First10KProgramDraft",
    "GenerateFirst10KProgram",
    "GeneratedProgramSummary",
    "GenerationDiagnostic",
    "InvalidGeneratedProgramError",
]
