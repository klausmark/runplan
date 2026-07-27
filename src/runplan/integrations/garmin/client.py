"""Garmin authentication and query adapter."""

from __future__ import annotations

import os
import tomllib
from pathlib import Path
from typing import Any, Callable

from garminconnect import Garmin

from ...application.ports import GarminClient


def load_credentials(credentials_file: Path | None = None) -> tuple[str, str]:
    """Load Garmin credentials from a TOML file outside the project."""
    credentials_path = (
        credentials_file
        or Path(os.getenv("GARMIN_CREDENTIALS_FILE", "~/.config/runplan/credentials.toml"))
    ).expanduser().resolve()
    project_directory = Path(__file__).resolve().parents[3]

    if (
        credentials_path == project_directory
        or project_directory in credentials_path.parents
    ):
        raise SystemExit(
            "The credentials file must be outside the project directory.\n"
            f"Current path: {credentials_path}"
        )

    try:
        credentials = tomllib.loads(credentials_path.read_text(encoding="utf-8-sig"))
    except FileNotFoundError as exc:
        raise SystemExit(
            f"Credentials file not found: {credentials_path}\n"
            "Create it with this content:\n\n"
            'email = "name@example.com"\n'
            'password = "your-password"'
        ) from exc
    except tomllib.TOMLDecodeError as exc:
        raise SystemExit(
            f"Credentials file is not valid TOML: {credentials_path}\n{exc}"
        ) from exc
    except OSError as exc:
        raise SystemExit(
            f"Could not read credentials file: {credentials_path}\n{exc}"
        ) from exc

    email = credentials.get("email")
    password = credentials.get("password")
    if not isinstance(email, str) or not email.strip():
        raise SystemExit(f"Field 'email' is missing from {credentials_path}")
    if not isinstance(password, str) or not password:
        raise SystemExit(f"Field 'password' is missing from {credentials_path}")
    return email.strip(), password


def login_to_garmin(
    prompt_mfa: Callable[[], str] | None = None,
    *,
    credentials_file: Path | None = None,
    token_store: Path | None = None,
) -> Garmin:
    """Authenticate and reuse Garmin tokens from the configured token store."""
    resolved_token_store = (
        token_store
        or Path(os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect"))
    ).expanduser()
    email, password = load_credentials(credentials_file)
    client = Garmin(
        email,
        password,
        prompt_mfa=prompt_mfa or (lambda: input("Garmin MFA code: ").strip()),
    )
    client.login(str(resolved_token_store))
    return client


def get_all_workouts(client: GarminClient) -> list[dict[str, Any]]:
    """Return every workout by consuming Garmin's paginated endpoint."""
    workouts: list[dict[str, Any]] = []
    start = 0
    while True:
        page = client.get_workouts(start=start, limit=100)
        workouts.extend(page)
        if len(page) < 100:
            return workouts
        start += len(page)


def scheduled_items_for_dates(
    client: GarminClient, dates: set[str]
) -> list[dict[str, Any]]:
    """Return workout calendar items from every month represented by dates."""
    items: list[dict[str, Any]] = []
    for month_key in sorted({value[:7] for value in dates}):
        year, month = (int(part) for part in month_key.split("-"))
        calendar = client.get_scheduled_workouts(year, month)
        items.extend(calendar.get("calendarItems", []))
    normalized = []
    for item in items:
        if item.get("itemType") != "workout":
            continue
        workout = item.get("workout") if isinstance(item.get("workout"), dict) else {}
        normalized.append(
            {
                **item,
                "date": item.get("date", item.get("calendarDate")),
                "workoutId": item.get("workoutId", workout.get("workoutId")),
                "workoutScheduleId": item.get(
                    "workoutScheduleId", item.get("id")
                ),
            }
        )
    return normalized


__all__ = [
    "get_all_workouts",
    "load_credentials",
    "login_to_garmin",
    "scheduled_items_for_dates",
]
