"""Generate validated, editable first-10K program drafts locally."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..domain.first_10k_blueprint import build_first_10k_outline
from ..domain.first_10k_program import build_first_10k_program
from ..domain.first_10k_validation import CandidateOccurrence, validate_first_10k_candidate
from ..domain.generation_inputs import First10KGenerationInput, normalize_first_10k_input
from ..parsing.yaml_writer import dump_program_yaml

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
    """Raised when the local algorithm violates its independent validator."""

    def __init__(
        self,
        candidate: str,
        diagnostics: tuple[GenerationDiagnostic, ...],
        *,
        attempt_count: int = 1,
    ) -> None:
        super().__init__("The calculated program did not pass validation")
        self.candidate = candidate[:MAX_GENERATED_YAML_BYTES]
        self.diagnostics = diagnostics
        self.attempt_count = attempt_count


def _diagnostic(
    code: str,
    message: str,
    *,
    severity: str = "error",
    occurrence: CandidateOccurrence | None = None,
) -> GenerationDiagnostic:
    return GenerationDiagnostic(severity, code, message, occurrence)


class GenerateFirst10KProgram:
    """Calculate a deterministic draft without any persistence dependency."""

    def generate(
        self,
        request: First10KGenerationInput,
        *,
        today: date,
    ) -> First10KProgramDraft:
        inputs = normalize_first_10k_input(request, today=today)
        outline = build_first_10k_outline(inputs)
        program = build_first_10k_program(inputs, outline)
        content = dump_program_yaml(program)
        diagnostics = tuple(
            GenerationDiagnostic(issue.severity, issue.code, issue.message, issue.occurrence)
            for issue in validate_first_10k_candidate(program, inputs, outline)
        )
        if len(content.encode("utf-8")) > MAX_GENERATED_YAML_BYTES:
            diagnostics += (
                _diagnostic(
                    "calculated_program_too_large",
                    "The calculated program exceeds the supported YAML size.",
                ),
            )
        if any(item.severity == "error" for item in diagnostics):
            raise InvalidGeneratedProgramError(content, diagnostics)
        warnings = tuple(
            _diagnostic("input_warning", warning, severity="warning") for warning in inputs.warnings
        ) + tuple(item for item in diagnostics if item.severity == "warning")
        anchor = inputs.main_race_date or inputs.period.start_week
        return First10KProgramDraft(
            filename=f"first-10k-{anchor.isoformat()}.yaml",
            content=content,
            summary=GeneratedProgramSummary(
                weeks=len(program.weeks),
                workouts=sum(len(week.workouts) for week in program.weeks),
            ),
            warnings=warnings,
            attempt_count=1,
        )


__all__ = [
    "MAX_GENERATED_YAML_BYTES",
    "First10KProgramDraft",
    "GenerateFirst10KProgram",
    "GeneratedProgramSummary",
    "GenerationDiagnostic",
    "InvalidGeneratedProgramError",
]
