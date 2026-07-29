"""Serialize the non-secret Runplan user registry."""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .users import RunplanUser


def write_user_config(path: Path, users: Iterable[RunplanUser]) -> None:
    """Atomically replace a registry TOML document."""
    lines: list[str] = []
    for user in users:
        lines.extend(
            [
                "[[users]]",
                f"id = {json.dumps(user.id)}",
                f"name = {json.dumps(user.name, ensure_ascii=False)}",
                f"credentials_file = {json.dumps(str(user.credentials_file))}",
                f"token_store = {json.dumps(str(user.token_store))}",
                f"state_dir = {json.dumps(str(user.state_directory))}",
                f"default_pace = {json.dumps(user.default_pace)}",
            ]
        )
        if user.active_program is not None:
            lines.append(f"active_program = {json.dumps(user.active_program)}")
        lines.append("")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text("\n".join(lines), encoding="utf-8")
    temporary.replace(path)
