"""Build per-distance coaching blocks for the bundled Nike Run Club templates.

The pace chart is generated from the central pace model so the rendered
table can never drift from the runtime pace calculations. The 1K best
column is the lookup key. Race totals are computed from Riegel's
formula at the 5K reference and then back-converted through each
distance's predicted pace to keep them self-consistent.
"""

from __future__ import annotations

from pathlib import Path

from runplan.domain import (
    FIVE_KM,
    HALF_MARATHON_KM,
    MARATHON_KM,
    TEN_KM,
    format_pace_seconds,
    intensity_pace_seconds,
    one_k_pace_to_five_k_seconds,
    race_pace_seconds,
    round5,
    total_from_pace,
)

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "src" / "runplan" / "templates" / "programs"

# Lookup key starts at 3:00 min/km and walks in 20-second steps until 8:00.
ONE_K_PACE_START_SECONDS = 3 * 60
ONE_K_PACE_STOP_SECONDS = 8 * 60
ONE_K_PACE_STEP_SECONDS = 20

RACE_DISTANCES_KM = (
    ("5k", FIVE_KM),
    ("10k", TEN_KM),
    ("half-marathon", HALF_MARATHON_KM),
    ("marathon", MARATHON_KM),
)


def _build_pace_chart_block(
    columns: list[dict[str, str]], rows: list[list[str]], examples: list[dict]
) -> str:
    header_lines = (
        "      headers:\n"
        + "\n".join(
            f'        - {{ label: "{col["label"]}", description: "{col["description"]}" }}'
            for col in columns
        )
        + "\n"
    )
    row_lines = (
        "      rows:\n"
        + "\n".join("        - [" + ", ".join(f'"{cell}"' for cell in row) + "]" for row in rows)
        + "\n"
    )
    example_lines = "      examples:\n" + "".join(
        "        - title: "
        + f'"{ex["title"]}"'
        + "\n"
        + "          row: ["
        + ", ".join(f'"{cell}"' for cell in ex["row"])
        + "]\n"
        + "          targets:\n"
        + "\n".join(f'            - "{t}"' for t in ex["targets"])
        + "\n"
        for ex in examples
    )
    return header_lines + row_lines + example_lines


def _format_total(total_seconds: int) -> str:
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def _race_cell(pace_seconds_per_km: int, distance_km: float) -> str:
    total = total_from_pace(pace_seconds_per_km, distance_km)
    return f"{_format_total(total)} / {format_pace_seconds(pace_seconds_per_km)}"


def _pace_cell(pace_seconds_per_km: int) -> str:
    return format_pace_seconds(pace_seconds_per_km)


def _chart_headers(include_recovery: bool) -> list[dict[str, str]]:
    headers = [
        {
            "label": "1K best",
            "description": "Your best 1K effort in minutes per kilometer.",
        },
        {
            "label": "5K best / avg km",
            "description": "Best 5K time and the average pace per kilometer you held during it.",
        },
        {
            "label": "10K best / avg km",
            "description": "Best 10K time and the average pace per kilometer you held during it.",
        },
        {
            "label": "Tempo min/km",
            "description": "Steady, hard-but-controlled pace per kilometer.",
        },
        {
            "label": "Half marathon best / avg km",
            "description": "Best half marathon time and the average pace per kilometer you held during it.",
        },
        {
            "label": "Marathon best / avg km",
            "description": "Best marathon time and the average pace per kilometer you held during it.",
        },
    ]
    if include_recovery:
        headers.append(
            {
                "label": "Recovery min/km",
                "description": "Easy conversational pace per kilometer.",
            }
        )
    return headers


def _row_for_one_k(one_k_seconds: int, include_recovery: bool) -> tuple[list[str], dict[str, int]]:
    one_k_pace = round5(one_k_seconds)
    five_k_seconds = int(round(one_k_pace_to_five_k_seconds(one_k_pace)))
    pace = {
        "1k": one_k_pace,
        "5k": race_pace_seconds(five_k_seconds, FIVE_KM),
        "10k": race_pace_seconds(five_k_seconds, TEN_KM),
        "tempo": intensity_pace_seconds(five_k_seconds, "tempo"),
        "half-marathon": race_pace_seconds(five_k_seconds, HALF_MARATHON_KM),
        "marathon": race_pace_seconds(five_k_seconds, MARATHON_KM),
    }
    cells = [_pace_cell(pace["1k"])]
    cells.append(_race_cell(pace["5k"], FIVE_KM))
    cells.append(_race_cell(pace["10k"], TEN_KM))
    cells.append(_pace_cell(pace["tempo"]))
    cells.append(_race_cell(pace["half-marathon"], HALF_MARATHON_KM))
    cells.append(_race_cell(pace["marathon"], MARATHON_KM))
    if include_recovery:
        pace["recovery"] = intensity_pace_seconds(five_k_seconds, "recovery")
        cells.append(_pace_cell(pace["recovery"]))
    return cells, pace


def _one_k_steps() -> list[int]:
    step_count = (ONE_K_PACE_STOP_SECONDS - ONE_K_PACE_START_SECONDS) // ONE_K_PACE_STEP_SECONDS
    return [ONE_K_PACE_START_SECONDS + i * ONE_K_PACE_STEP_SECONDS for i in range(step_count + 1)]


def _chart_rows(include_recovery: bool) -> tuple[list[list[str]], dict[int, dict[str, int]]]:
    rows: list[list[str]] = []
    paces_by_one_k: dict[int, dict[str, int]] = {}
    for one_k in _one_k_steps():
        cells, pace = _row_for_one_k(one_k, include_recovery)
        rows.append(cells)
        paces_by_one_k[one_k] = pace
    return rows, paces_by_one_k


def _example_for_one_k(
    title: str,
    one_k_seconds: int,
    pace: dict[str, int],
    include_recovery: bool,
) -> dict:
    cells, _ = _row_for_one_k(one_k_seconds, include_recovery)
    targets: list[str] = []
    targets.append(f"Best 1K Pace: {_pace_cell(pace['1k'])} min/km")
    targets.append(
        f"5K Pace: {_format_total(total_from_pace(pace['5k'], FIVE_KM))} / {_pace_cell(pace['5k'])} min/km"
    )
    targets.append(
        f"10K Pace: {_format_total(total_from_pace(pace['10k'], TEN_KM))} / {_pace_cell(pace['10k'])} min/km"
    )
    targets.append(f"Tempo Pace: {_pace_cell(pace['tempo'])} min/km")
    targets.append(
        "Marathon Pace: "
        f"{_format_total(total_from_pace(pace['marathon'], MARATHON_KM))} / {_pace_cell(pace['marathon'])} min/km"
    )
    return {"title": title, "row": cells, "targets": targets}


def _chart_examples(
    paces_by_one_k: dict[int, dict[str, int]],
    include_recovery: bool,
    columns: list[dict[str, str]],
) -> list[dict]:
    sample_seconds = sorted(paces_by_one_k.keys())
    five_k_one_k_seconds = sample_seconds[len(sample_seconds) // 2]
    target = paces_by_one_k[five_k_one_k_seconds]
    five_k_total = total_from_pace(target["5k"], FIVE_KM)
    return [
        _example_for_one_k(
            f"If your last 5K was {_format_total(five_k_total)}",
            five_k_one_k_seconds,
            target,
            include_recovery,
        ),
        _example_for_one_k(
            "If your Best 1K time is 5:00",
            300,
            paces_by_one_k[300],
            include_recovery,
        ),
    ]


def _build_chart(include_recovery: bool) -> dict:
    columns = _chart_headers(include_recovery)
    rows, paces_by_one_k = _chart_rows(include_recovery)
    examples = _chart_examples(paces_by_one_k, include_recovery, columns)
    return {"headers": columns, "rows": rows, "examples": examples}


CHART_WITH_RECOVERY = _build_chart(include_recovery=True)
CHART_WITHOUT_RECOVERY = _build_chart(include_recovery=False)


def _build_pace_chart_block_structured(chart: dict) -> str:
    """Build the YAML for a pace_chart block from structured inputs."""
    return _build_pace_chart_block(chart["headers"], chart["rows"], chart["examples"])


def _apply_block_variants(
    base_block: str,
    *,
    tagline: str,
    weeks_label: str,
    schedule_text: str,
    run_count_text: str,
    pace_chart: dict,
    audio_guided: bool,
) -> str:
    block = base_block
    block = block.replace(
        '"Speed, endurance, recovery and motivation"',
        f'"{tagline}"',
    )
    block = re_sub(
        r"Download and run with the Nike Run Club App and this\n          \d+-week \w+ Training\n          Program to coach yourself across the finish line\.",
        f"Download and run with the Nike Run Club App and this {weeks_label} Training\n          Program to coach yourself across the finish line.",
        block,
    )
    block = re_sub(
        r"This plan was designed around a? \d+-week schedule for maximum results\. It\n          was built to adapt to your experience level and intended to be uniquely\n          flexible to your needs as you prepare(?: to)? (?:a )?[^\.]+\. Whether you're[^.]+\.\n          We do recommend that you plan on\n          training for at least \d+ weeks before the[^\.]+\.",
        schedule_text,
        block,
    )
    block = re_sub(
        r"You have (?:two|three) Recovery Runs and (?:two|two) Rest Days - use them to\n          break up your Speed and Long Runs(?:\. Try to avoid doing your Speed Run\n          and Long Run on back-to-back days)?\.",
        run_count_text,
        block,
    )

    new_pace_chart = _build_pace_chart_block_structured(pace_chart)
    block = re_sub(
        r"      headers:\n(?:        - \{ label:[^\n]+\}\n)+      rows:\n(?:        - \[[^\n]+\]\n)+      examples:\n(?:        - title:.*?\n          row:.*?\n          targets:\n(?:            - .*?\n)+)+",
        new_pace_chart,
        block,
    )

    if audio_guided:
        block = block.replace(
            '    glossary:\n      - term: "Progression Run"',
            "    glossary:\n" + AUDIO_GUIDED_TERM + '      - term: "Progression Run"',
        )
    return block


def re_sub(pattern: str, replacement: str, string: str) -> str:
    import re

    return re.sub(pattern, replacement, string)


def _read_base_coaching() -> str:
    """Return the verbatim coaching block from the 5K template."""
    text = (TEMPLATES_DIR / "nike-5k.yaml").read_text(encoding="utf-8")
    start = text.index("  coaching:")
    end = text.index("\nweeks:")
    return text[start:end]


def _inject(path: Path, block: str) -> None:
    text = path.read_text(encoding="utf-8")
    start = text.index("  start_week:")
    end = text.index("\nweeks:")
    head = text[: start + len("  start_week: 2027-W01")]
    tail = text[end:]
    path.write_text(head + "\n" + block + tail, encoding="utf-8")


AUDIO_GUIDED_TERM = """      - term: "Audio Guided Run"
        definition: >-
          The Nike Run Club app offers a library of Audio Guided Runs. You can find
          long and short runs, duration as well as distance-based runs and speed
          runs of all types including fartlek, interval and tempo runs. Some of our
          best coaches and athletes will meet you at the starting line to guide,
          motivate and inspire you to a better run. Every run in this plan has an
          accompanying Audio Guided Run. You can run alone, or you can run with us.
          As always, the choice is yours.
"""


def build_all() -> None:
    base = _read_base_coaching()

    ten_k_block = _apply_block_variants(
        base,
        tagline="Speed, endurance, recovery, and motivation",
        weeks_label="8-week 10K",
        schedule_text=(
            "This plan was designed around an 8-week schedule for maximum results. It\n"
            "          was built to adapt to your experience level and intended to be uniquely\n"
            "          flexible to your needs as you prepare to tackle a 10K. Whether you're\n"
            "          four or eight weeks from race day, you can jump into this program\n"
            "          whenever it suits you. You're in control of what you put into the program\n"
            "          and therefore what you get out of it. We do recommend that you plan on\n"
            "          training for at least 4 weeks before the 10K and can comfortably run and\n"
            "          complete the programmed workouts."
        ),
        run_count_text=(
            "You have two Recovery Runs and two Rest Days - use them to\n"
            "          break up your Speed and Long Runs. Avoid doing Speed Runs on back-to-back\n"
            "          days."
        ),
        pace_chart=CHART_WITH_RECOVERY,
        audio_guided=False,
    )

    half_marathon_block = _apply_block_variants(
        base,
        tagline="Speed, endurance, and recovery",
        weeks_label="14-week Audio Guided Half Marathon",
        schedule_text=(
            "This plan was designed around a 14-week schedule for maximum results. It\n"
            "          was built to adapt to your experience level and intended to be uniquely\n"
            "          flexible to your needs as you prepare to tackle a Half Marathon. Whether\n"
            "          you're eight or fourteen weeks from race day, you can jump into this program\n"
            "          whenever it suits you. You're in control of what you put into the program\n"
            "          and therefore what you get out of it. We do recommend that you plan on\n"
            "          training for at least 6 weeks before the Half Marathon and can comfortably\n"
            "          run and complete the programmed workouts."
        ),
        run_count_text=(
            "You have two Recovery Runs and two Rest Days - use them to\n"
            "          break up your Speed and Long Runs. Avoid doing Speed Runs on back-to-back\n"
            "          days."
        ),
        pace_chart=CHART_WITH_RECOVERY,
        audio_guided=True,
    )

    marathon_block = _apply_block_variants(
        base,
        tagline="Speed, endurance, recovery, and motivation",
        weeks_label="18-week Marathon",
        schedule_text=(
            "This plan was designed around an 18-week schedule for maximum results. It\n"
            "          was built to adapt to your experience level and intended to be uniquely\n"
            "          flexible to your needs as you prepare for a Marathon. Whether you're\n"
            "          twelve or eighteen weeks from race day, you can jump into this program\n"
            "          whenever it suits you. You're in control of what you put into the program\n"
            "          and therefore what you get out of it. We do recommend that you plan on\n"
            "          training for at least 12 weeks before the Marathon and can comfortably\n"
            "          run and complete the programmed workouts."
        ),
        run_count_text=(
            "You have three Recovery Runs and two Rest Days - use them to\n"
            "          break up your Speed and Long Runs. Try to avoid doing your Speed Run\n"
            "          and Long Run on back-to-back days."
        ),
        pace_chart=CHART_WITH_RECOVERY,
        audio_guided=False,
    )

    _inject(TEMPLATES_DIR / "nike-10k.yaml", ten_k_block)
    _inject(TEMPLATES_DIR / "nike-half-marathon.yaml", half_marathon_block)
    _inject(TEMPLATES_DIR / "nike-marathon.yaml", marathon_block)


if __name__ == "__main__":
    build_all()
    print(
        "Coaching injected into nike-10k, nike-half-marathon and nike-marathon "
        "with the regenerated metric pace chart."
    )
