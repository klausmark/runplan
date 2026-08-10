"""Annotate the bundled NRC templates with relative pace_type targets."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML

TEMPLATES_DIR = Path(__file__).resolve().parents[1] / "src" / "runplan" / "templates" / "programs"

MILE_PATTERN = re.compile(r"\bMile Pace\b")
HALF_HINTS = ("half marathon", "hm effort", "half effort")
MARATHON_HINTS = ("marathon",)
TEMPO_HINTS = ("tempo",)
RECOVERY_HINTS = ("recovery run", "recovery", "progression")
FIVE_K_HINTS = ("5k", "5km")
TEN_K_HINTS = ("10k", "10km")


def _classify_note(note: str | None) -> str | None:
    if not note:
        return None
    text = note.strip()
    lowered = text.lower()
    if MILE_PATTERN.search(text):
        return "1k"
    if any(hint in lowered for hint in HALF_HINTS) and "half marathon" in lowered:
        return "half-marathon"
    if any(hint in lowered for hint in MARATHON_HINTS):
        return "marathon"
    if any(hint in lowered for hint in TEMPO_HINTS):
        return "tempo"
    if any(hint in lowered for hint in RECOVERY_HINTS):
        return "recovery"
    if any(hint in lowered for hint in TEN_K_HINTS):
        return "10k"
    if any(hint in lowered for hint in FIVE_K_HINTS):
        return "5k"
    return None


def _classify_distance(value: Any) -> str | None:
    """Translate a distance value into the closest race intensity."""
    text = str(value).strip().lower() if value is not None else ""
    kilometers: float | None = None
    if text.endswith("km"):
        try:
            kilometers = float(text[:-2].strip())
        except ValueError:
            kilometers = None
    elif text.endswith("m"):
        try:
            kilometers = float(text[:-1].strip()) / 1000
        except ValueError:
            kilometers = None
    else:
        try:
            kilometers = float(text) / 1000
        except ValueError:
            kilometers = None
    if kilometers is None:
        return None
    if abs(kilometers - 5.0) < 0.5:
        return "5k"
    if abs(kilometers - 10.0) < 0.5:
        return "10k"
    if abs(kilometers - 21.0975) < 0.5:
        return "half-marathon"
    if abs(kilometers - 42.195) < 0.5:
        return "marathon"
    return None


RACE_DISTANCE_HINTS = (
    ("marathon", "marathon"),
    ("half marathon", "half-marathon"),
    ("10k", "10k"),
    ("5k", "5k"),
)


def _classify_race_note(note: str | None) -> str | None:
    if not note:
        return None
    lowered = note.lower()
    if "race" not in lowered:
        return None
    for keyword, target in RACE_DISTANCE_HINTS:
        if keyword in lowered:
            return target
    return None


def _annotate_step(step: Any) -> None:
    if not isinstance(step, dict) or len(step) != 1:
        return
    action, value = next(iter(step.items()))
    if action == "repeat":
        # Do not assign pace_type to children: repeats are already validated
        # to forbid pace_type and their pace targets stay at the per-step level.
        return
    if not isinstance(value, dict):
        return
    note = value.get("note")
    note_text = str(note) if note is not None else None
    target = _classify_note(note_text) or _classify_race_note(note_text)
    if target is None and action == "run" and value.get("distance") is not None:
        target = _classify_distance(value["distance"])
    if target is None:
        return
    if value.get("pace") is None and value.get("pace_type") is None:
        value["pace_type"] = target


def _annotate_workout(workout: Any) -> None:
    if not isinstance(workout, dict):
        return
    for step in workout.get("steps") or []:
        _annotate_step(step)


def _replace_mile_pace_text(text: str) -> str:
    return MILE_PATTERN.sub("1K Pace", text)


def _load_yaml() -> YAML:
    yaml = YAML()
    yaml.preserve_quotes = True
    yaml.width = 4096
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


def annotate_file(path: Path) -> None:
    yaml = _load_yaml()
    raw = yaml.load(path)
    for week in raw.get("weeks", []):
        for workout in week.get("workouts", []):
            _annotate_workout(workout)
    with path.open("w", encoding="utf-8") as handle:
        yaml.dump(raw, handle)
    text = path.read_text(encoding="utf-8")
    text = _replace_mile_pace_text(text)
    path.write_text(text, encoding="utf-8")


def annotate_all() -> None:
    for name in ("nike-5k.yaml", "nike-10k.yaml", "nike-half-marathon.yaml", "nike-marathon.yaml"):
        annotate_file(TEMPLATES_DIR / name)


if __name__ == "__main__":
    annotate_all()
    print("Annotated 1K/5K/10K/HM/Marathon/Tempo/Recovery targets across the NRC templates.")
