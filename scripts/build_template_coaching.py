"""Build per-distance coaching blocks for the bundled Nike Run Club templates."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEMPLATES_DIR = PROJECT_ROOT / "src" / "runplan" / "templates" / "programs"


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


def _round5(seconds: float) -> int:
    """Round a duration in seconds to the nearest 5 seconds."""
    return round(seconds / 5) * 5


def _format_pace(seconds: int) -> str:
    minutes, sec = divmod(seconds, 60)
    return f"{minutes}:{sec:02d}"


def _parse_total(total: str) -> int:
    parts = total.split(":")
    return sum(int(p) * 60 ** (len(parts) - 1 - i) for i, p in enumerate(parts))


def _pace_from_total(total: str, distance_km: float) -> str:
    """Convert a total race time into a min/km pace, rounded to 5 seconds."""
    seconds = _parse_total(total)
    return _format_pace(_round5(seconds / distance_km))


def _pace_from_mile(mile_pace: str) -> str:
    """Convert a min/mile pace into a min/km pace, rounded to 5 seconds."""
    parts = mile_pace.split(":")
    seconds = int(parts[0]) * 60 + int(parts[1])
    return _format_pace(_round5(seconds / 1.609344))


MILE_BEST_COLUMN = {
    "label": "Mile best",
    "description": "Your best one-mile effort.",
}

METRIC_HEADERS_7 = [
    MILE_BEST_COLUMN,
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
    {
        "label": "Recovery min/km",
        "description": "Easy conversational pace per kilometer.",
    },
]

METRIC_HEADERS_6 = METRIC_HEADERS_7[:-1]


# Original mile-based row data: each row is (mile_best, 5k_time, 10k_time,
# tempo_mile, hm_time, m_time, recovery_mile). Marathon rows drop the last
# column.
MILES_ROWS_7 = [
    ("5:00", "17:05", "35:45", "6:05", "1:18:00", "2:44:00", "7:00"),
    ("5:30", "18:45", "39:00", "6:35", "1:25:00", "3:00:00", "7:35"),
    ("6:00", "20:15", "42:00", "7:05", "1:35:00", "3:15:00", "8:10"),
    ("6:30", "22:00", "45:45", "7:40", "1:40:00", "3:30:00", "8:45"),
    ("7:00", "23:45", "49:00", "8:15", "1:50:00", "3:45:00", "9:20"),
    ("7:30", "25:15", "52:30", "8:50", "1:55:00", "4:00:00", "9:55"),
    ("8:00", "27:00", "55:50", "9:25", "2:05:00", "4:15:00", "10:30"),
    ("8:30", "28:30", "59:00", "9:55", "2:10:00", "4:30:00", "11:00"),
    ("9:00", "30:00", "62:30", "10:30", "2:20:00", "4:45:00", "11:35"),
    ("9:30", "31:45", "66:00", "11:00", "2:25:00", "5:00:00", "12:10"),
    ("10:00", "33:00", "69:00", "11:35", "2:35:00", "5:15:00", "12:45"),
    ("10:30", "35:00", "72:00", "12:00", "2:40:00", "5:30:00", "13:20"),
    ("11:00", "36:15", "75:00", "12:35", "2:50:00", "5:40:00", "13:45"),
    ("11:30", "38:00", "78:30", "13:00", "2:55:00", "5:50:00", "14:05"),
    ("12:00", "39:30", "81:30", "13:35", "3:05:00", "6:00:00", "14:30"),
]


def _convert_row(row):
    mile_best, k5, k10, tempo, hm, m, recovery = row
    return [
        mile_best,
        f"{k5} / {_pace_from_total(k5, 5.0)}",
        f"{k10} / {_pace_from_total(k10, 10.0)}",
        _pace_from_mile(tempo),
        f"{hm} / {_pace_from_total(hm, 21.0975)}",
        f"{m} / {_pace_from_total(m, 42.195)}",
        _pace_from_mile(recovery),
    ]


METRIC_ROWS_7 = [_convert_row(row) for row in MILES_ROWS_7]
METRIC_ROWS_6 = [row[:-1] for row in METRIC_ROWS_7]


def _row_for_mile_best(mile_best: str) -> list[str] | None:
    for row in MILES_ROWS_7:
        if row[0] == mile_best:
            return _convert_row(row)
    return None


MILES_EXAMPLE_27 = (
    "If your last 5K was 27:00",
    ["8:00", "27:00 / 8:40", "55:50 / 9:00", "9:25", "2:05:00 / 9:30", "4:15:00 / 9:45", "10:30"],
    [
        "Best Mile Pace: 8:00 minutes",
        "5K Average Mile Pace: 8:40 minutes",
        "10K Average Mile Pace: 9:00 minutes",
        "Tempo Pace: 9:25 minutes",
        "Marathon Average Mile Pace: 9:45 minutes",
    ],
)

MILES_EXAMPLE_930 = (
    "If your Best Mile time is 9:30",
    [
        "9:30",
        "31:45 / 10:15",
        "66:00 / 10:35",
        "11:00",
        "2:25:00 / 11:05",
        "5:00:00 / 11:25",
        "12:10",
    ],
    [
        "Best Mile Pace: 9:30 minutes",
        "5K Average Mile Pace: 10:15 minutes",
        "10K Average Mile Pace: 10:35 minutes",
        "Tempo Pace: 11 minutes",
        "Marathon Average Mile Pace: 11:25 minutes",
    ],
)


def _convert_example(
    title: str, mile_row: list[str], mile_targets: list[str], *, drop_last: bool
) -> dict:
    mile_best = mile_row[0]
    metric_row = _row_for_mile_best(mile_best)
    if metric_row is None:
        raise ValueError(f"Unknown mile best: {mile_best!r}")
    if drop_last:
        metric_row = metric_row[:-1]
    targets = [
        "Best Mile Pace: 8:00 minutes"
        if mile_best == "8:00"
        else f"Best Mile Pace: {mile_best} minutes",
    ]
    pace_by_label = {
        "5K": 1,
        "10K": 2,
        "Tempo": 3,
        "HM": 4,
        "Marathon": 5,
    }
    target_labels = {
        "5K": "5K Pace",
        "10K": "10K Pace",
        "Tempo": "Tempo Pace",
        "Marathon": "Marathon Pace",
    }
    for label in ("5K", "10K", "Tempo", "Marathon"):
        targets.append(f"{target_labels[label]}: {metric_row[pace_by_label[label]]} min/km")
    return {"title": title, "row": metric_row, "targets": targets}


METRIC_EXAMPLES_7 = [
    _convert_example(*MILES_EXAMPLE_27, drop_last=False),
    _convert_example(*MILES_EXAMPLE_930, drop_last=False),
]

METRIC_EXAMPLES_6 = [
    _convert_example(*MILES_EXAMPLE_27, drop_last=True),
    _convert_example(*MILES_EXAMPLE_930, drop_last=True),
]


SHARED_PACE_CHART_7 = {
    "headers": METRIC_HEADERS_7,
    "rows": METRIC_ROWS_7,
    "examples": METRIC_EXAMPLES_7,
}

SHARED_PACE_CHART_6 = {
    "headers": METRIC_HEADERS_6,
    "rows": METRIC_ROWS_6,
    "examples": METRIC_EXAMPLES_6,
}


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
    block = re.sub(
        r"Download and run with the Nike Run Club App and this\n          \d+-week \w+ Training\n          Program to coach yourself across the finish line\.",
        f"Download and run with the Nike Run Club App and this {weeks_label} Training\n          Program to coach yourself across the finish line.",
        block,
    )
    block = re.sub(
        r"This plan was designed around a? \d+-week schedule for maximum results\. It\n          was built to adapt to your experience level and intended to be uniquely\n          flexible to your needs as you prepare(?: to)? (?:a )?[^\.]+\. Whether you're[^.]+\.\n          We do recommend that you plan on\n          training for at least \d+ weeks before the[^\.]+\.",
        schedule_text,
        block,
    )
    block = re.sub(
        r"You have (?:two|three) Recovery Runs and (?:two|two) Rest Days - use them to\n          break up your Speed and Long Runs(?:\. Try to avoid doing your Speed Run\n          and Long Run on back-to-back days)?\.",
        run_count_text,
        block,
    )

    new_pace_chart = _build_pace_chart_block_structured(pace_chart)
    block = re.sub(
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
        pace_chart=SHARED_PACE_CHART_7,
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
        pace_chart=SHARED_PACE_CHART_7,
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
        pace_chart=SHARED_PACE_CHART_6,
        audio_guided=False,
    )

    _inject(TEMPLATES_DIR / "nike-10k.yaml", ten_k_block)
    _inject(TEMPLATES_DIR / "nike-half-marathon.yaml", half_marathon_block)
    _inject(TEMPLATES_DIR / "nike-marathon.yaml", marathon_block)


if __name__ == "__main__":
    build_all()
    print("Coaching injected into nike-10k, nike-half-marathon, nike-marathon.")
