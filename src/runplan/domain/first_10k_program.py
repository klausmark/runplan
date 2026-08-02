"""Build complete deterministic first-10K programs."""

from __future__ import annotations

from .first_10k_blueprint import First10KOutline, TrainingPhase
from .first_10k_loads import plan_first_10k_loads
from .first_10k_workouts import build_first_10k_workout
from .generation_inputs import NormalizedFirst10KGenerationInput
from .models import Program, Week

_PHASE_FOCUS = {
    TrainingPhase.FOUNDATION: "Build consistency with relaxed, sustainable running",
    TrainingPhase.BUILD: "Develop endurance and controlled aerobic strength",
    TrainingPhase.CONSOLIDATION: "Absorb training with a deliberately reduced week",
    TrainingPhase.TAPER: "Reduce extra running and complete the 10K",
}


def build_first_10k_program(
    inputs: NormalizedFirst10KGenerationInput,
    outline: First10KOutline,
) -> Program:
    """Return a complete program calculated from normalized inputs and an outline."""
    loads = plan_first_10k_loads(inputs, outline)
    weeks = []
    for outline_week, load in zip(outline.weeks, loads, strict=True):
        workouts = tuple(
            build_first_10k_workout(
                slot,
                load.distance_for(slot),
                outline_week.phase,
                inputs,
            )
            for slot in outline_week.workouts
        )
        weeks.append(
            Week(
                number=outline_week.number,
                focus=_PHASE_FOCUS[outline_week.phase],
                workouts=workouts,
            )
        )
    iso_year, iso_week, _ = inputs.period.start_week.isocalendar()
    anchor = inputs.main_race_date or inputs.period.start_week
    return Program(
        id=f"first-10k-{anchor.isoformat()}",
        name="Complete Your First 10K",
        short_name="FIRST-10K",
        description=(
            "A deterministic, progressive program for building the consistency and endurance "
            "needed to complete 10 kilometers."
        ),
        start_date=inputs.period.start_week,
        start_week=f"{iso_year}-W{iso_week:02d}",
        weeks=tuple(weeks),
    )


__all__ = ["build_first_10k_program"]
