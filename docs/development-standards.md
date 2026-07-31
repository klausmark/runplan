# Runplan development standards

These standards favor clear responsibilities and readable behavior over adherence to a
particular programming paradigm.

## Design and responsibilities

A function performs one clearly named task at one abstraction level. An orchestration
function may coordinate multiple steps, but it delegates their implementation. Parsing,
validation, transformation, persistence, presentation, and external I/O should not be mixed
inside one function.

A class has one purpose and one primary reason to change. Use typed dataclasses for domain
data. Use classes where identity or state matters, including services, repositories, and
external adapters. Split classes that combine storage, business rules, formatting,
configuration, or transport. Prefer composition to inheritance.

A module has one cohesive purpose that can be described in one short sentence. Its public
names support that purpose. Independent workflows and architectural concerns belong in
separate modules.

Prefer pure functions for calculations and transformations. Use `Protocol` for replaceable
application boundaries. Public functions, methods, protocols, and dataclass fields have type
annotations. Dependencies continue to point inward according to
[project-design.md](project-design.md).

## Size signals

Line counts prompt review; they are not automated pass/fail limits:

- At 40 to 50 logical function lines, verify that the function still has one task and one
  abstraction level.
- A function over 80 lines normally needs extraction or a documented reason to remain whole.
- Review production modules around 300 lines. Modules over 500 lines normally need splitting
  by purpose.
- Test modules may be longer, but each module must still cover one coherent subsystem or
  behavior area.

A short unit can still violate single responsibility. A longer unit can remain cohesive, but
length never excuses mixed responsibilities.

## Tests

Pytest is the test runner and the target style. New test modules use plain `test_*` functions
or small context classes that do not inherit from `unittest.TestCase`. Use plain assertions,
fixtures for reusable setup, `pytest.mark.parametrize` for repeated scenarios, `tmp_path` for
temporary files, `monkeypatch` for environment or attribute changes, and `pytest.raises` for
expected failures. `unittest.mock` remains acceptable when an explicit mock is clearest; do
not add another mocking plugin without a demonstrated need.

Existing `unittest.TestCase` modules remain supported during migration because pytest can
collect them. Small changes may retain their existing style. When a module needs substantial
test changes, migrate the complete module so pytest and `TestCase` styles are not mixed in the
same file.

Name tests `test_<situation>_<expected_result>` using the product vocabulary. Keep setup,
action, and expected result visually distinct. A test covers one behavior; multiple assertions
are appropriate when they jointly describe that behavior. Tests use fakes or mocks at external
boundaries and never contact a real Garmin account.

## Formatting and local checks

Ruff formats and lints Python code with Python 3.13 as the language target and a 100-character
target line length. Run all required checks with:

```bash
uv run python scripts/check.py
```

The command checks formatting, lint, and the complete pytest suite. Use `uv run pytest` for a
test-only development loop. Do not apply repository-wide formatting during unrelated work.
Coverage thresholds, static type-checking, and hosted CI can be added when they solve a
demonstrated problem.

## Versioning and change history

`pyproject.toml` is the single source of the application version. Runplan uses Semantic
Versioning while remaining below 1.0: patches are compatible fixes; minor versions contain
features or intentional breaking changes. Breaking changes must be explicit.

`CHANGELOG.md` records changes that users or integrators notice, not every commit. Keep new
entries under `Unreleased`. At a milestone, move them under the version and date, update the
project version, and create a `vX.Y.Z` tag. Commit messages are a single subject line:
short, imperative, and in English. Do not add a body; detailed change notes belong in
`CHANGELOG.md` under `Unreleased` and in the PR description. Conventional Commits are not
required.

## Known deviations

The current web, synchronization, export, and CLI areas contain large units that need a
responsibility audit against these standards. Treat decomposition as separate,
behavior-preserving work backed by characterization tests. Do not mix those refactors into
unrelated feature changes. The measured inventory and prioritized responsibility assessment
live in [code-quality-audit.md](code-quality-audit.md).
