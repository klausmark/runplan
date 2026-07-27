"""Machine-readable preview formatting."""

from __future__ import annotations

import json

from ..application.preview import PreviewResult


def format_json(preview: PreviewResult) -> str:
    """Serialize selected weeks as stable JSON output."""
    document = {
        "programId": preview.program_id,
        "weeks": [
            {
                "week": week.number,
                "startDate": week.start_date,
                "endDate": week.end_date,
                "workouts": [
                    {"id": workout.id, "date": workout.date, "payload": workout.payload}
                    for workout in week.workouts
                ],
            }
            for week in preview.weeks
        ],
    }
    if preview.sync_plan is not None:
        document["sync"] = preview.sync_plan.to_dict()
    return json.dumps(document, ensure_ascii=False, indent=2)


__all__ = ["format_json"]
