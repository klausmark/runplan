"""Round-trip YAML parsing and rendering for the web program editor."""

from __future__ import annotations

from io import StringIO
from typing import Any

from ruamel.yaml import YAML


def editable_yaml() -> YAML:
    """Create the consistently configured round-trip YAML codec."""
    parser = YAML()
    parser.preserve_quotes = True
    parser.width = 4096
    parser.indent(mapping=2, sequence=4, offset=2)
    return parser


def load_editable_yaml(text: str) -> Any:
    """Parse YAML while retaining presentation details needed by the editor."""
    return editable_yaml().load(text)


def dump_editable_yaml(value: Any) -> str:
    """Render round-trip YAML without introducing display-only line wrapping."""
    stream = StringIO()
    editable_yaml().dump(value, stream)
    return stream.getvalue()
