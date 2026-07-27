"""Shared filesystem behavior for deterministic text-based exporters."""

from pathlib import Path


def write_export(content: str, output_path: Path, force: bool) -> None:
    output_path = output_path.expanduser().resolve()
    if output_path.exists() and not force:
        raise FileExistsError(
            f"Output file already exists: {output_path}\nUse --force to overwrite it."
        )
    if not output_path.parent.exists():
        raise FileNotFoundError(f"Output directory does not exist: {output_path.parent}")
    output_path.write_text(content, encoding="utf-8")


__all__ = ["write_export"]
