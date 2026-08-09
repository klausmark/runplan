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


SHARED_PACE_CHART_7 = {
    "headers": [
        {"label": "Mile best", "description": "Your best one-mile effort."},
        {
            "label": "5K best / avg mile",
            "description": "Best 5K time and the average pace per mile you held during it.",
        },
        {
            "label": "10K best / avg mile",
            "description": "Best 10K time and the average pace per mile you held during it.",
        },
        {
            "label": "Tempo avg mile",
            "description": "Steady, hard-but-controlled pace you can hold for 30-60 minutes.",
        },
        {
            "label": "Half marathon best / avg mile",
            "description": "Best half marathon time and the average pace per mile you held during it.",
        },
        {
            "label": "Marathon best / avg mile",
            "description": "Best marathon time and the average pace per mile you held during it.",
        },
        {
            "label": "Recovery day pace",
            "description": "Easy conversational pace, often 60-90 seconds per mile slower than your marathon pace.",
        },
    ],
    "rows": [
        [
            "5:00",
            "17:05 / 5:30",
            "35:45 / 5:45",
            "6:05",
            "1:18:00 / 6:00",
            "2:44:00 / 6:15",
            "7:00",
        ],
        [
            "5:30",
            "18:45 / 6:00",
            "39:00 / 6:15",
            "6:35",
            "1:25:00 / 6:30",
            "3:00:00 / 6:50",
            "7:35",
        ],
        [
            "6:00",
            "20:15 / 6:30",
            "42:00 / 6:45",
            "7:05",
            "1:35:00 / 7:15",
            "3:15:00 / 7:25",
            "8:10",
        ],
        [
            "6:30",
            "22:00 / 7:05",
            "45:45 / 7:20",
            "7:40",
            "1:40:00 / 7:35",
            "3:30:00 / 8:00",
            "8:45",
        ],
        [
            "7:00",
            "23:45 / 7:40",
            "49:00 / 7:55",
            "8:15",
            "1:50:00 / 8:20",
            "3:45:00 / 8:35",
            "9:20",
        ],
        [
            "7:30",
            "25:15 / 8:05",
            "52:30 / 8:25",
            "8:50",
            "1:55:00 / 8:45",
            "4:00:00 / 9:10",
            "9:55",
        ],
        [
            "8:00",
            "27:00 / 8:40",
            "55:50 / 9:00",
            "9:25",
            "2:05:00 / 9:30",
            "4:15:00 / 9:45",
            "10:30",
        ],
        [
            "8:30",
            "28:30 / 9:10",
            "59:00 / 9:30",
            "9:55",
            "2:10:00 / 9:55",
            "4:30:00 / 10:15",
            "11:00",
        ],
        [
            "9:00",
            "30:00 / 9:40",
            "62:30 / 10:00",
            "10:30",
            "2:20:00 / 10:40",
            "4:45:00 / 10:50",
            "11:35",
        ],
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
            "10:00",
            "33:00 / 10:40",
            "69:00 / 11:05",
            "11:35",
            "2:35:00 / 11:45",
            "5:15:00 / 12:00",
            "12:45",
        ],
        [
            "10:30",
            "35:00 / 11:15",
            "72:00 / 11:35",
            "12:00",
            "2:40:00 / 12:10",
            "5:30:00 / 12:35",
            "13:20",
        ],
        [
            "11:00",
            "36:15 / 11:40",
            "75:00 / 12:00",
            "12:35",
            "2:50:00 / 12:55",
            "5:40:00 / 13:00",
            "13:45",
        ],
        [
            "11:30",
            "38:00 / 12:15",
            "78:30 / 12:35",
            "13:00",
            "2:55:00 / 13:15",
            "5:50:00 / 13:20",
            "14:05",
        ],
        [
            "12:00",
            "39:30 / 12:40",
            "81:30 / 13:05",
            "13:35",
            "3:05:00 / 14:05",
            "6:00:00 / 13:45",
            "14:30",
        ],
    ],
    "examples": [
        {
            "title": "If your last 5K was 27:00",
            "row": [
                "8:00",
                "27:00 / 8:40",
                "55:50 / 9:00",
                "9:25",
                "2:05:00 / 9:30",
                "4:15:00 / 9:45",
                "10:30",
            ],
            "targets": [
                "Best Mile Pace: 8:00 minutes",
                "5K Average Mile Pace: 8:40 minutes",
                "10K Average Mile Pace: 9:00 minutes",
                "Tempo Pace: 9:25 minutes",
                "Marathon Average Mile Pace: 9:45 minutes",
            ],
        },
        {
            "title": "If your Best Mile time is 9:30",
            "row": [
                "9:30",
                "31:45 / 10:15",
                "66:00 / 10:35",
                "11:00",
                "2:25:00 / 11:05",
                "5:00:00 / 11:25",
                "12:10",
            ],
            "targets": [
                "Best Mile Pace: 9:30 minutes",
                "5K Average Mile Pace: 10:15 minutes",
                "10K Average Mile Pace: 10:35 minutes",
                "Tempo Pace: 11 minutes",
                "Marathon Average Mile Pace: 11:25 minutes",
            ],
        },
    ],
}

SHARED_PACE_CHART_6 = {
    "headers": SHARED_PACE_CHART_7["headers"][:-1],
    "rows": [row[:-1] for row in SHARED_PACE_CHART_7["rows"]],
    "examples": [
        {
            "title": "If your last 5K was 27:00",
            "row": SHARED_PACE_CHART_7["examples"][0]["row"][:-1],
            "targets": SHARED_PACE_CHART_7["examples"][0]["targets"],
        },
        {
            "title": "If your Best Mile time is 9:30",
            "row": SHARED_PACE_CHART_7["examples"][1]["row"][:-1],
            "targets": SHARED_PACE_CHART_7["examples"][1]["targets"],
        },
    ],
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
