"""Read and atomically persist Garmin credentials for configured users."""

from __future__ import annotations

import json
import logging
import tomllib
from http import HTTPStatus
from pathlib import Path

logger = logging.getLogger("runplan.users")


class CredentialStore:
    """Own the on-disk representation of one user's Garmin credentials."""

    def read(self, path: Path) -> dict[str, str]:
        from .users import WebError

        try:
            value = tomllib.loads(path.read_text(encoding="utf-8-sig"))
        except FileNotFoundError as exc:
            logger.debug("Garmin credentials file not found exception=%s", type(exc).__name__)
            return {}
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise WebError(
                HTTPStatus.UNPROCESSABLE_ENTITY,
                f"Could not read Garmin credentials: {exc}",
            ) from exc
        return {
            key: item for key in ("email", "password") if isinstance((item := value.get(key)), str)
        }

    def write(self, path: Path, email: str, password: str) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(".tmp")
        temporary.write_text(
            f"email = {json.dumps(email)}\npassword = {json.dumps(password)}\n",
            encoding="utf-8",
        )
        temporary.replace(path)
