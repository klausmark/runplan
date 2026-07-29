"""Report structural size signals without enforcing them as quality gates."""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "src" / "runplan"
TEST_ROOT = ROOT / "tests"

FUNCTION_REVIEW_LINES = 40
FUNCTION_STRONG_LINES = 80
MODULE_REVIEW_LINES = 300
MODULE_STRONG_LINES = 500
CLASS_REVIEW_LINES = 100
CLASS_REVIEW_METHODS = 8
TEST_MODULE_REVIEW_LINES = 250
TEST_FUNCTION_REVIEW_LINES = 40
TEST_CLASS_REVIEW_METHODS = 10


@dataclass(frozen=True, slots=True)
class ModuleMetric:
    path: str
    lines: int


@dataclass(frozen=True, slots=True)
class FunctionMetric:
    path: str
    line: int
    name: str
    lines: int
    kind: str


@dataclass(frozen=True, slots=True)
class ClassMetric:
    path: str
    line: int
    name: str
    lines: int
    methods: int
    test_methods: int


@dataclass(frozen=True, slots=True)
class Inventory:
    modules: tuple[ModuleMetric, ...]
    functions: tuple[FunctionMetric, ...]
    classes: tuple[ClassMetric, ...]


class EntityCollector(ast.NodeVisitor):
    """Collect qualified function and class metrics from one syntax tree."""

    def __init__(self, path: str) -> None:
        self.path = path
        self.scope: list[tuple[str, str]] = []
        self.functions: list[FunctionMetric] = []
        self.classes: list[ClassMetric] = []

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        name = self._qualified_name(node.name)
        methods = [item for item in node.body if isinstance(item, ast.FunctionDef)]
        self.classes.append(
            ClassMetric(
                path=self.path,
                line=node.lineno,
                name=name,
                lines=_node_lines(node),
                methods=len(methods),
                test_methods=sum(method.name.startswith("test_") for method in methods),
            )
        )
        self.scope.append(("class", node.name))
        self.generic_visit(node)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        kind = "method" if any(kind == "class" for kind, _ in self.scope) else "function"
        self.functions.append(
            FunctionMetric(
                path=self.path,
                line=node.lineno,
                name=self._qualified_name(node.name),
                lines=_node_lines(node),
                kind=kind,
            )
        )
        self.scope.append(("function", node.name))
        self.generic_visit(node)
        self.scope.pop()

    visit_AsyncFunctionDef = visit_FunctionDef

    def _qualified_name(self, name: str) -> str:
        return ".".join([*(scope_name for _, scope_name in self.scope), name])


def _node_lines(node: ast.AST) -> int:
    return node.end_lineno - node.lineno + 1  # type: ignore[attr-defined]


def collect_inventory(root: Path) -> Inventory:
    """Collect structural metrics for every Python file below a root."""
    modules: list[ModuleMetric] = []
    functions: list[FunctionMetric] = []
    classes: list[ClassMetric] = []
    for path in sorted(root.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        relative = path.relative_to(ROOT).as_posix()
        modules.append(ModuleMetric(relative, len(source.splitlines())))
        collector = EntityCollector(relative)
        collector.visit(ast.parse(source, filename=relative))
        functions.extend(collector.functions)
        classes.extend(collector.classes)
    return Inventory(tuple(modules), tuple(functions), tuple(classes))


def _sorted_by_size(items: tuple[object, ...]) -> list[object]:
    return sorted(items, key=lambda item: (-item.lines, item.path, getattr(item, "line", 0)))


def _print_table(headers: tuple[str, ...], rows: list[tuple[object, ...]]) -> None:
    print("| " + " | ".join(headers) + " |")
    print("| " + " | ".join("---" for _ in headers) + " |")
    for row in rows:
        print("| " + " | ".join(str(value) for value in row) + " |")
    if not rows:
        print("| " + " | ".join("None" for _ in headers) + " |")
    print()


def _function_signal(lines: int) -> str:
    return "strong" if lines >= FUNCTION_STRONG_LINES else "review"


def _module_signal(lines: int) -> str:
    return "strong" if lines >= MODULE_STRONG_LINES else "review"


def report_source(inventory: Inventory, *, show_all: bool) -> None:
    """Print the production inventory and configured size signals."""
    modules = (
        inventory.modules
        if show_all
        else tuple(item for item in inventory.modules if item.lines >= MODULE_REVIEW_LINES)
    )
    functions = (
        inventory.functions
        if show_all
        else tuple(item for item in inventory.functions if item.lines >= FUNCTION_REVIEW_LINES)
    )
    classes = (
        inventory.classes
        if show_all
        else tuple(
            item
            for item in inventory.classes
            if item.lines >= CLASS_REVIEW_LINES or item.methods >= CLASS_REVIEW_METHODS
        )
    )

    print("## Production modules")
    print(
        f"{len(inventory.modules)} total; "
        f"{sum(item.lines >= MODULE_REVIEW_LINES for item in inventory.modules)} size signals.\n"
    )
    _print_table(
        ("Lines", "Signal", "Module"),
        [(item.lines, _module_signal(item.lines), item.path) for item in _sorted_by_size(modules)],
    )

    print("## Production functions and methods")
    print(
        f"{len(inventory.functions)} total; "
        f"{sum(item.lines >= FUNCTION_REVIEW_LINES for item in inventory.functions)} "
        "size signals.\n"
    )
    _print_table(
        ("Lines", "Signal", "Kind", "Location"),
        [
            (
                item.lines,
                _function_signal(item.lines),
                item.kind,
                f"{item.path}:{item.line} `{item.name}`",
            )
            for item in _sorted_by_size(functions)
        ],
    )

    print("## Production classes")
    print(
        f"{len(inventory.classes)} total; "
        f"{sum(item.lines >= CLASS_REVIEW_LINES or item.methods >= CLASS_REVIEW_METHODS for item in inventory.classes)} "
        "review candidates.\n"
    )
    _print_table(
        ("Lines", "Methods", "Location"),
        [
            (item.lines, item.methods, f"{item.path}:{item.line} `{item.name}`")
            for item in _sorted_by_size(classes)
        ],
    )


def report_tests(inventory: Inventory) -> None:
    """Print a concise overview of large test structures."""
    modules = tuple(item for item in inventory.modules if item.lines >= TEST_MODULE_REVIEW_LINES)
    functions = tuple(
        item for item in inventory.functions if item.lines >= TEST_FUNCTION_REVIEW_LINES
    )
    classes = tuple(
        item for item in inventory.classes if item.test_methods >= TEST_CLASS_REVIEW_METHODS
    )

    print("## Test overview")
    _print_table(
        ("Lines", "Module"),
        [(item.lines, item.path) for item in _sorted_by_size(modules)],
    )
    _print_table(
        ("Lines", "Kind", "Location"),
        [
            (item.lines, item.kind, f"{item.path}:{item.line} `{item.name}`")
            for item in _sorted_by_size(functions)
        ],
    )
    _print_table(
        ("Lines", "Test methods", "Location"),
        [
            (item.lines, item.test_methods, f"{item.path}:{item.line} `{item.name}`")
            for item in _sorted_by_size(classes)
        ],
    )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--all",
        action="store_true",
        help="Show the complete production inventory instead of size signals only",
    )
    return parser.parse_args()


def main() -> int:
    """Print the current production audit and test overview."""
    arguments = parse_arguments()
    report_source(collect_inventory(SOURCE_ROOT), show_all=arguments.all)
    report_tests(collect_inventory(TEST_ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
