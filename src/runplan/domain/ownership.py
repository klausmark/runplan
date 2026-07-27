"""Versioned Runplan ownership metadata embedded in Garmin descriptions."""

from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass


PREFIX = "[runplan:v1:"
SUFFIX = "]"
_MARKER = re.compile(r"(?:\n\n)?\[runplan:v(?P<version>\d+):(?P<payload>[A-Za-z0-9_-]+)\]$")


class OwnershipMetadataError(ValueError):
    """Raised when a Runplan marker exists but is invalid or unsupported."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class OwnershipMetadata:
    owner_id: str
    program_id: str
    week: int
    workout_id: str
    date: str
    content_hash: str

    def payload(self) -> dict[str, object]:
        return {
            "o": self.owner_id,
            "p": self.program_id,
            "w": self.week,
            "i": self.workout_id,
            "d": self.date,
            "h": self.content_hash,
        }


def ownership_marker(metadata: OwnershipMetadata) -> str:
    encoded = json.dumps(
        metadata.payload(), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    payload = base64.urlsafe_b64encode(encoded).decode("ascii").rstrip("=")
    return f"{PREFIX}{payload}{SUFFIX}"


def description_with_ownership(
    description: str | None, metadata: OwnershipMetadata
) -> str:
    human = strip_ownership(description)[0].rstrip()
    marker = ownership_marker(metadata)
    return f"{human}\n\n{marker}" if human else marker


def strip_ownership(description: object) -> tuple[str, bool]:
    if not isinstance(description, str):
        return "", False
    match = _MARKER.search(description)
    if match is None:
        return description, False
    return description[:match.start()].rstrip(), True


def parse_ownership(description: object) -> OwnershipMetadata | None:
    if not isinstance(description, str) or "[runplan:v" not in description:
        return None
    match = _MARKER.search(description)
    if match is None:
        raise OwnershipMetadataError("invalid", "Malformed Runplan ownership marker")
    if match.group("version") != "1":
        raise OwnershipMetadataError(
            "unsupported_version",
            f"Unsupported Runplan ownership version {match.group('version')}",
        )
    payload = match.group("payload")
    try:
        decoded = base64.urlsafe_b64decode(payload + "=" * (-len(payload) % 4))
        raw = json.loads(decoded)
    except (ValueError, json.JSONDecodeError) as exc:
        raise OwnershipMetadataError("invalid", "Invalid Runplan ownership payload") from exc
    if not isinstance(raw, dict):
        raise OwnershipMetadataError("invalid", "Runplan ownership payload must be an object")
    fields = (raw.get("o"), raw.get("p"), raw.get("w"), raw.get("i"), raw.get("d"), raw.get("h"))
    if not (
        isinstance(fields[0], str) and fields[0]
        and isinstance(fields[1], str) and fields[1]
        and isinstance(fields[2], int) and not isinstance(fields[2], bool) and fields[2] > 0
        and isinstance(fields[3], str) and fields[3]
        and isinstance(fields[4], str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", fields[4])
        and isinstance(fields[5], str) and re.fullmatch(r"[0-9a-f]{64}", fields[5])
    ):
        raise OwnershipMetadataError("invalid", "Runplan ownership payload has invalid fields")
    return OwnershipMetadata(
        owner_id=fields[0], program_id=fields[1], week=fields[2],
        workout_id=fields[3], date=fields[4], content_hash=fields[5],
    )


__all__ = [
    "OwnershipMetadata",
    "OwnershipMetadataError",
    "description_with_ownership",
    "ownership_marker",
    "parse_ownership",
    "strip_ownership",
]
