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

## Wishing well

Ideas in this section are intentionally not implementation-ready. Promote an
idea to the section above only after its scope and product decisions are clear.

- Add validated generic 5K, 10K, half-marathon, and marathon programs that
  users can browse and copy before editing.
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
