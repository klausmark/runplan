# Runplan roadmap

This file contains only upcoming work. Product and architecture decisions live
in [docs/project-design.md](docs/project-design.md).

## Ready to implement

These features are sufficiently defined to be implemented next, in order.

1. Preserve unknown optional YAML metadata during every supported visual edit,
   with regression tests for metadata at program, week, workout, and step level.
2. Return structured validation errors from the web API with a stable error
   code, message, document path, and YAML line and column when available.
3. Add browser-level coverage for the critical calendar, touch movement,
   theme, validation, and confirmed sync flows.

## Shipped

- Deterministic first 10K program generator. The `runplan generation`
  module encodes the coaching rules from
  `docs/generation-first-10k-evidence.md` into pure functions and ships
  a `runplan generate first-10k` CLI command. The implementation lives
  in `src/runplan/generation/` and is exercised by the
  `tests/test_generation_*.py` suite.
- Nike Run Club training plan templates. Four templates (5K, 10K,
  half-marathon, marathon) ship under
  `src/runplan/templates/programs/` as static YAML files. The
  `runplan.templates` module exposes them through the public Python
  API and the Studio catalog (`GET /api/templates`,
  `GET /api/templates/<id>`, `POST /api/templates/<id>/copy`). The
  Studio empty-state offers a **Browse templates** button that copies
  the chosen template to the active user with a chosen start week.
  The templates are unofficial adaptations; pace targets stay in step
  notes so Garmin Connect receives the user's own pace when applied.

## Wishing well

Ideas in this section are intentionally not implementation-ready. Promote an
idea to the section above only after its scope and product decisions are clear.

- Expose prompts and generic programs consistently through the CLI.
- Add revision history and restore with readable change summaries.
- Add calendar copy/paste, duplication, multi-select, and whole-week moves.
- Build a form-based workout editor for steps, repeats, distance, time, and
  pace while retaining YAML as an advanced mode.
- Make form and YAML editing round-trip through one canonical schema.
- Consider an opt-in setting for multiple workouts on the same day.
- Add reviewable, validated LLM-generated plans and revisions.
- Consider feedback-driven plan adaptation only after consent and coaching
  safety boundaries are defined.
