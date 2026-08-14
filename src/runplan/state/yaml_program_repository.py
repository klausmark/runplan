"""Production implementer of the :class:`ProgramRepository` port.

The CLI's ``everyday`` and ``instantiate_recipe`` paths both need to read
and write the raw program YAML document. State repositories like
:class:`runplan.state.yaml_repository.YamlStateRepository` target the
tracking metadata instead, so the Step 10 everyday use case and any
future batch program editor use this dedicated repository.
"""

from __future__ import annotations

from io import StringIO
from pathlib import Path
from typing import Any

from ruamel.yaml import YAML


def _yaml() -> YAML:
    value = YAML()
    value.preserve_quotes = True
    value.width = 4096
    value.indent(mapping=2, sequence=4, offset=2)
    return value


class YamlProgramRepository:
    """Persistence contract for raw program YAML documents.

    The repository wraps a single program file. ``load`` validates that
    the document's ``program.id`` matches ``program_id``; ``save``
    writes the modified document back atomically without disturbing
    quoting or formatting.
    """

    def __init__(self, program_path: Path) -> None:
        self.program_path = program_path.expanduser().resolve()

    def _document(self) -> dict[str, Any]:
        document = _yaml().load(self.program_path.read_text(encoding="utf-8"))
        if not isinstance(document, dict):
            raise ValueError("program YAML must be an object")
        return document

    def load(self, program_id: str) -> dict[str, Any]:
        """Return the raw YAML document for ``program_id``.

        Raises ``KeyError`` when the document does not exist or when the
        ``program.id`` does not match.
        """
        if not self.program_path.exists():
            raise KeyError(f"program file does not exist: {self.program_path}")
        document = self._document()
        program_block = document.get("program")
        document_id = program_block.get("id") if isinstance(program_block, dict) else None
        if document_id != program_id:
            raise KeyError(f"program {program_id!r} does not match document id {document_id!r}")
        return document

    def save(self, program_id: str, raw: dict[str, Any]) -> None:
        """Persist the updated raw YAML document.

        A defensive deep copy of ``raw`` is written so the caller can
        continue to mutate the in-memory document without affecting
        what is on disk.
        """
        import copy

        if not isinstance(raw, dict):
            raise ValueError("raw must be a dict")
        program_block = raw.get("program")
        if not isinstance(program_block, dict) or program_block.get("id") != program_id:
            raise ValueError(f"raw document's program.id must remain {program_id!r}")
        stream = StringIO()
        _yaml().dump(copy.deepcopy(raw), stream)
        self.program_path.parent.mkdir(parents=True, exist_ok=True)
        self.program_path.write_text(stream.getvalue(), encoding="utf-8")


__all__ = ["YamlProgramRepository"]
