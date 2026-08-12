# Locked decisions for the workout recipe initiative

These decisions were taken on 2026-08-12 and apply to every later step in
[PLAN.md](PLAN.md). Later steps must stay consistent with them. When a later
step needs to revisit a decision, update this file in the same change.

## Decision 1 — Canonical workout actions

Add `walk` and `rest` to the canonical step actions:

- `warmup`
- `run`
- `walk`
- `recovery`
- `rest`
- `cooldown`
- `repeat`

Runplan currently has no other users, so existing programs, documentation,
examples, and tests can be updated freely. The change is not required to be
backwards-compatible.

## Decision 2 — Meaning of `recovery`

Keep `recovery` as **flexible active recovery** (option A from the planning
session). It means "restitute actively in the way that fits today" and may
carry a pace, a note, or no extra guidance.

`walk` and `rest` exist for the cases where the exact movement matters:

- `walk` is planned walking as part of the workout.
- `rest` is a pause where standing is acceptable.
- `recovery` is active recovery — usually easy movement that the runner may
  interpret.

`recovery` is a powerful coaching tool and stays in the action list.

## Decision 3 — Categories and recipe keys are authoring concepts

Categories and recipe keys are authoring concepts. They are **not** fields in
program YAML. Programs stay flexible so the runner can include workout types
that Runplan does not catalogue.

The category must still be visible to the runner. Visibility is achieved
outside the YAML format:

- **A — Studio UI strip.** Each workout card shows its category as a visible
  label, either inferred from the workout or set locally when a recipe
  instantiates the workout.
- **B — Local metadata outside YAML.** The category is stored in local
  application state associated with the program. It travels with the user's
  plan in Runplan but does not travel inside the program file. Exports keep
  their usual portability.
- **C — Export headings.** Markdown and HTML exports present the category as a
  clear heading before each workout.

Program YAML continues to describe only what is run: name, description,
steps, and optional pace targets. Recipes expand into ordinary explicit
workouts when they are added to a program.