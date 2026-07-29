"""Run Runplan's required local quality checks."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PYTHON_TARGETS = ("src", "tests", "scripts")


def run_check(command: list[str]) -> None:
    """Run one check and stop immediately when it fails."""
    print(f"\n> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def main() -> int:
    """Run formatting, lint, and tests in fail-fast order."""
    run_check([sys.executable, "-m", "ruff", "format", "--check", *PYTHON_TARGETS])
    run_check([sys.executable, "-m", "ruff", "check", *PYTHON_TARGETS])
    run_check([sys.executable, "-m", "pytest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
