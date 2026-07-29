# Runplan agent guide

Run the complete test suite before finishing a code change:

```bash
uv run pytest
```

Ruff is configured but is not yet a required gate. Do not run Ruff with `--fix` or format the
whole repository as part of an unrelated change. A dedicated baseline change will activate
the combined formatting, lint, and test check.

## Engineering rules

- Write code, tests, documentation, identifiers, and user-facing text in English.
- Give every function one clearly named task at one abstraction level.
- Give every class one purpose and one primary reason to change.
- Give every module one cohesive purpose that can be stated in one short sentence.
- Prefer pure functions for calculations and transformations, typed dataclasses for domain
  data, and classes for stateful services, repositories, and external adapters.
- Prefer composition to inheritance. Use protocols at replaceable application boundaries.
- Keep dependencies pointing inward as described in [docs/project-design.md](docs/project-design.md).
- Follow the detailed guidance in
  [docs/development-standards.md](docs/development-standards.md).

## Tests

- Use pytest for new test modules. Name tests `test_<situation>_<expected_result>`.
- Keep each test focused on one behavior and make setup, action, and result easy to read.
- Existing `unittest` modules may remain until they need substantial changes. When migrating,
  convert the whole module instead of mixing styles within it.
- Never contact a real Garmin account from a test. Use fakes or mocks at external boundaries.

## Safety and compatibility

- Never commit credentials, tokens, generated user state, or unnecessary health data.
- Preserve compatibility deliberately for the CLI, YAML format, JSON output, stored-state
  schemas, and the public exports in `runplan.__init__`.
- Add migrations or explicit errors when a persisted format changes incompatibly.
- Keep Garmin mutations behind the existing preview and confirmation boundaries.

## Definition of done

- Changed functions, classes, and modules remain cohesive and single-purpose.
- The complete pytest suite passes.
- Behavior changes have readable tests, and affected documentation is updated.
- User-visible changes are recorded under `Unreleased` in `CHANGELOG.md`.
