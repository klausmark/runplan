"""Garmin authentication and query adapter."""

from __future__ import annotations

import os
import tomllib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from garminconnect import Garmin

from ...application.ports import GarminClient


def load_credentials(credentials_file: Path | None = None) -> tuple[str, str]:
    """Load Garmin credentials from a TOML file outside the project."""
    credentials_path = (
        (
            credentials_file
            or Path(os.getenv("GARMIN_CREDENTIALS_FILE", "~/.config/runplan/credentials.toml"))
        )
        .expanduser()
        .resolve()
    )
    project_directory = Path(__file__).resolve().parents[3]

    if credentials_path == project_directory or project_directory in credentials_path.parents:
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
        raise SystemExit(f"Credentials file is not valid TOML: {credentials_path}\n{exc}") from exc
    except OSError as exc:
        raise SystemExit(f"Could not read credentials file: {credentials_path}\n{exc}") from exc

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
        token_store or Path(os.getenv("GARMIN_TOKENSTORE", "~/.garminconnect"))
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


def scheduled_items_for_dates(client: GarminClient, dates: set[str]) -> list[dict[str, Any]]:
    """Return workout calendar items from every month represented by dates."""
    items = _unique_calendar_items(_calendar_items(client, dates), dates)
    workouts = _normalized_workouts(items, dates)
    _associate_calendar_activities(client, items, workouts, dates)
    _enrich_direct_activities(client, workouts)
    return workouts


def _calendar_items(client: GarminClient, dates: set[str]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for month_key in sorted({value[:7] for value in dates}):
        year, month = (int(part) for part in month_key.split("-"))
        calendar = client.get_scheduled_workouts(year, month)
        items.extend(calendar.get("calendarItems", []))
    return items


def _unique_calendar_items(items: list[dict[str, Any]], dates: set[str]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for item in items:
        item_date = item.get("date", item.get("calendarDate"))
        if item_date not in dates:
            continue
        workout = item.get("workout") if isinstance(item.get("workout"), dict) else {}
        item_id = item.get("id")
        identity = (
            (item.get("itemType"), "id", item_id)
            if item_id is not None
            else (
                item.get("itemType"),
                "fallback",
                item_date,
                item.get("workoutId", workout.get("workoutId")),
            )
        )
        if identity not in seen:
            seen.add(identity)
            result.append(item)
    return result


def _normalized_workouts(items: list[dict[str, Any]], dates: set[str]) -> list[dict[str, Any]]:
    result = []
    for item in items:
        if item.get("itemType") != "workout":
            continue
        workout = item.get("workout") if isinstance(item.get("workout"), dict) else {}
        normalized = {
            **item,
            "date": item.get("date", item.get("calendarDate")),
            "workoutId": item.get("workoutId", workout.get("workoutId")),
            "workoutScheduleId": item.get("workoutScheduleId", item.get("id")),
        }
        if normalized["date"] in dates:
            result.append(normalized)
    return result


def _associate_calendar_activities(
    client: GarminClient,
    items: list[dict[str, Any]],
    workouts: list[dict[str, Any]],
    dates: set[str],
) -> None:
    occurrences = {
        (item.get("workoutId"), item.get("date")): item
        for item in workouts
        if item.get("workoutId") is not None
    }
    associated: set[tuple[Any, str]] = set()
    for item in items:
        if (
            item.get("itemType") != "activity"
            or item.get("date") not in dates
            or item.get("id") is None
        ):
            continue
        summary = client.get_activity(str(item["id"]))
        metadata = (
            summary.get("metadataDTO") if isinstance(summary.get("metadataDTO"), dict) else {}
        )
        key = (metadata.get("associatedWorkoutId"), item.get("date"))
        occurrence = occurrences.get(key)
        if occurrence is None:
            continue
        if key in associated:
            raise RuntimeError(
                f"Multiple Garmin activities are associated with workoutId={key[0]} on {key[1]}"
            )
        _apply_activity(occurrence, summary, item["id"], item.get("startTimestampLocal"))
        associated.add(key)


def _enrich_direct_activities(client: GarminClient, workouts: list[dict[str, Any]]) -> None:
    """Fill actual totals for older responses that expose an activity ID on the workout."""
    for occurrence in workouts:
        activity_id = occurrence.get("associatedActivityId")
        if activity_id is None or occurrence.get("actualDistanceMeters") is not None:
            continue
        summary = client.get_activity(str(activity_id))
        existing_time = occurrence.get("associatedActivityDateTime")
        _apply_activity(occurrence, summary, activity_id, existing_time)
        if existing_time is not None:
            occurrence["associatedActivityDateTime"] = existing_time


def _apply_activity(
    occurrence: dict[str, Any], summary: dict[str, Any], activity_id: Any, fallback_time: Any
) -> None:
    details = summary.get("summaryDTO") if isinstance(summary.get("summaryDTO"), dict) else {}
    distance, duration = details.get("distance"), details.get("duration")
    if (
        not isinstance(distance, (int, float))
        or isinstance(distance, bool)
        or distance <= 0
        or not isinstance(duration, (int, float))
        or isinstance(duration, bool)
        or duration <= 0
    ):
        raise RuntimeError(f"Garmin activity {activity_id} has invalid distance or duration")
    occurrence["associatedActivityId"] = summary.get("activityId", activity_id)
    occurrence["associatedActivityDateTime"] = details.get("startTimeLocal", fallback_time)
    occurrence["actualDistanceMeters"] = float(distance)
    occurrence["actualDurationSeconds"] = float(duration)


__all__ = [
    "get_all_workouts",
    "load_credentials",
    "login_to_garmin",
    "scheduled_items_for_dates",
]
