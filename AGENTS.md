# Runplan agent guide

## Local quality check

Run before finishing a code change:

```bash
uv run python scripts/check.py
```

The script runs Ruff format, Ruff lint, and the full pytest suite in fail-fast order. Use `uv run pytest` directly for a test-only loop. Do not apply repository-wide formatting during unrelated work.

## Engineering rules

- Target Python 3.13 (`[tool.ruff] target-version = "py313"`). Dependencies and the lockfile are `uv`-managed; there is no `requirements.txt`.
- Write code, tests, documentation, identifiers, and user-facing text in English.
- Prefer pure functions for calculations, typed dataclasses for domain data, and classes for stateful services, repositories, and external adapters.
- Keep dependencies pointing inward — see [docs/project-design.md](docs/project-design.md).
- Follow [docs/development-standards.md](docs/development-standards.md). Use [docs/code-quality-audit.md](docs/code-quality-audit.md) to scope structural refactoring; refresh its measurements with `uv run python scripts/audit_structure.py`.
- Use a single-line subject for every commit: short, imperative, and in English. Add a body when it helps reviewers understand the change or its motivation; bodies are free-form. Commit messages are the project's change history — release notes are derived from `git log` at milestones. See [docs/development-standards.md](docs/development-standards.md) for context.

## Tests

- Pytest is the only framework. Name tests `test_<situation>_<expected_result>`.
- Prefer plain test functions. Use small non-inheriting `Test...` classes only when they group related behavior.
- Never contact a real Garmin account from a test. Use fakes or mocks at external boundaries.

## Safety and compatibility

- Never commit credentials, tokens, generated user state, or unnecessary health data.
- Preserve compatibility deliberately for the CLI surface, YAML format, JSON output, stored-state schemas, and the public exports in `runplan.__init__`. Add migrations or explicit errors when a persisted format changes incompatibly.
- Keep Garmin mutations behind the existing preview and confirmation boundaries.

## Definition of done

- `uv run python scripts/check.py` passes.
- User-visible changes are documented in the commit message body (or PR description), not in a tracked file.
