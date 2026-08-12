# Workout recipes and coaching recommendations

This plan describes the work required to make Runplan's "add workout" flow
recipe-driven and to lay the same foundation under a future goal-specific
program generator and a rolling everyday program that suggests the next two
weeks of running.

The plan is a working document. Each step has its own section so it can be
referenced from a planning session and then handed to a build session for
implementation. Steps build on each other in the listed order. Do not start
a step before its dependencies are merged.

The three locked decisions for every step are recorded in
[decisions.md](decisions.md).

## Step 0 — Decisions and plan storage

- **Purpose:** Lock the three product decisions, write the plan, commit it.
- **Done when:** `decisions.md` and this `PLAN.md` exist and are committed;
  `docs/terminology.md` and `docs/program-prompt.md` reflect the new actions
  and the new meaning of `recovery`; `uv run python scripts/check.py` passes.
- **Depends on:** none.
- **Primary files:** `docs/workout-recipes/PLAN.md` (new),
  `docs/workout-recipes/decisions.md` (new), `docs/terminology.md`,
  `docs/program-prompt.md`.
- **Test strategy:** documentation only. Local quality check must pass.

## Step 1 — Canonical workout actions

- **Purpose:** Make `walk` and `rest` first-class actions and update every
  dependent surface. No backwards compatibility is required.
- **Done when:** The parser, validator, estimator, Garmin mapper, and
  presentation layer accept `walk` and `rest`. All existing programs,
  examples, and tests use the final action set. `recovery` is documented as
  flexible active recovery.
- **Depends on:** Step 0.
- **Primary files:** `src/runplan/domain/steps.py`,
  `src/runplan/parsing/yaml_models.py`, `src/runplan/parsing/values.py`,
  `src/runplan/integrations/garmin/mapper.py`,
  `src/runplan/presentation/text.py`, `docs/program-prompt.md`,
  `docs/terminology.md`, examples in `docs/examples/`, related tests.
- **Test strategy:** Per-action unit tests, round-trip tests, regression tests
  for combinations of actions, Garmin mapping tests.

## Step 2 — Schema-neutral categorisation

- **Purpose:** Introduce `WorkoutForm` as an authoring value that never enters
  program YAML.
- **Done when:** A `WorkoutForm` domain value exists with the six forms (easy
  run, run/walk, recovery run, long run, tempo run, interval workout). Forms
  can be inferred from explicit workouts and assigned at recipe instantiation.
  No YAML change.
- **Depends on:** Step 1.
- **Primary files:** `src/runplan/domain/workout_form.py` (new),
  `src/runplan/domain/steps.py`, `docs/terminology.md`.
- **Test strategy:** Unit tests for form inference and explicit assignment.

## Step 3 — Recipe domain contract

- **Purpose:** Define `WorkoutRecipe` as a schedule-independent domain value
  with parameters and an instantiation function.
- **Done when:** `WorkoutRecipe` exists in `domain/recipes.py`, has no program,
  week, day, date, or Garmin state, and instantiates into an explicit workout
  with name, description, and steps. Instantiated workouts receive a
  `WorkoutForm` for UI and export visibility.
- **Depends on:** Step 2.
- **Primary files:** `src/runplan/domain/recipes.py` (new),
  `src/runplan/generation/workouts.py` (generalise selected builders),
  `src/runplan/parsing/yaml_models.py` (or equivalent serializer).
- **Test strategy:** Per-recipe tests for parameters, instantiation, and form
  assignment.

## Step 4 — Recipe catalogue

- **Purpose:** Ship a curated library of two to three recipes per category.
- **Done when:** At least 18 recipes exist covering all six categories. Each
  recipe instantiates to a valid workout and is covered by focused tests. The
  existing first-10K generator is unchanged.
- **Depends on:** Step 3.
- **Primary files:** `src/runplan/domain/recipes/` (new module tree) or
  `src/runplan/recipes/` with category submodules, `tests/test_recipes.py`
  (new).
- **Test strategy:** Per-recipe tests for steps, parameters, parameterised
  variants, and form assignment.

## Step 5 — Coaching context and recommendation engine

- **Purpose:** Provide a pure use case `recommend_workouts(context, target_day)`
  that returns a recommendation, alternatives, and reasoning.
- **Done when:** The function exists as a pure domain or application function,
  uses the key-workout rule and the easy-default rule, and returns a structured
  `WorkoutRecommendation`. It is independent of the web layer and the
  filesystem.
- **Depends on:** Step 4.
- **Primary files:** `src/runplan/application/coaching/` (new module group),
  `src/runplan/domain/recommendations.py` (new),
  `tests/test_coaching_recommendations.py`.
- **Test strategy:** Parametrised scenarios: low load, high load, key-workout
  conflict, recovery request, no preferences, no pace data, low readiness.

## Step 6 — `instantiate_recipe` use case

- **Purpose:** Connect recipes to program editing.
- **Done when:** An application operation accepts a recipe, parameters, and a
  target week/day; allocates a new workout ID; builds an explicit workout;
  inserts it into the raw YAML; and validates the complete program. It uses an
  injected repository port so the web layer is not required.
- **Depends on:** Step 5.
- **Primary files:** `src/runplan/application/recipes/instantiate.py` (new),
  new or updated port in `src/runplan/application/ports.py`,
  `tests/test_instantiate_recipe.py`.
- **Test strategy:** Use-case tests with an in-memory program repository and
  fixture-based programs.

## Step 7 — Studio: recipe-based add workout

- **Purpose:** Replace the current YAML-first add-workout dialog with a
  recipe selector that still submits the existing `add_workout` transaction
  and previews the resulting week.
- **Done when:** The calendar opens a category/recipe/dose selector that
  builds a starter workout, displays the category strip and the week preview,
  and saves through the existing complete-program validation path. Advanced
  YAML editing remains available.
- **Depends on:** Step 6.
- **Primary files:** `src/runplan/web_assets/index.html`,
  `src/runplan/web_assets/app.js`, `src/runplan/web_http.py`,
  `src/runplan/web_editing.py` (or new port), new endpoints,
  `src/runplan/web_projection.py`, `tests/test_web_recipes.py`.
- **Test strategy:** Server-side tests for new endpoints, asset-package tests,
  and manual UI scenarios for the selector.

## Step 8 — Coaching in the Studio UI

- **Purpose:** Add the check-in, recommendation, alternatives, and easy/hard
  adjustment to the add-workout flow.
- **Done when:** The UI recommends a workout with reasoning, offers
  alternatives, lets the user adjust the dose, and warns when a key workout
  would be placed next to another key workout. The advanced YAML editor
  remains available.
- **Depends on:** Step 7.
- **Primary files:** `src/runplan/web_assets/index.html`,
  `src/runplan/web_assets/app.js`, new server endpoints,
  `tests/test_web_coaching.py`.
- **Test strategy:** Tests for the recommendation and warning logic, asset
  package tests, manual UI scenarios.

## Step 9 — Reuse recipes in the first-10K generator

- **Purpose:** Refactor the first-10K generator to consume the shared recipe
  layer while keeping its phase, progression, and variety logic intact.
- **Done when:** The generator uses domain recipes for workout construction.
  Output is unchanged or intentionally improved with a documented version
  change. CLI behaviour and tests pass.
- **Depends on:** Step 8.
- **Primary files:** `src/runplan/generation/plan.py`,
  `src/runplan/generation/workouts.py`, `src/runplan/generation/variety.py`,
  `src/runplan/generation/placement.py`, related generator tests.
- **Test strategy:** Snapshot tests of generator output, regression tests of
  CLI invocations, integration tests of phase progression.

## Step 10 — Rolling everyday plan (first version)

- **Purpose:** Provide an always-on plan with a 14-day horizon, weekly
  reflection, and adaptive addition of new weeks.
- **Done when:** A use case exists that proposes the next 14 days based on the
  runner profile, broad goal, completed workouts, and recent load. The
  proposal is previewable as one extra working week that can be accepted,
  edited, or rejected. A CLI surface is available first.
- **Depends on:** Step 9.
- **Primary files:** `src/runplan/application/everyday/` (new),
  `src/runplan/generation/everyday.py` (new), `src/runplan/cli.py`, related
  tests.
- **Test strategy:** Deterministic scenarios: new runner, winter goal,
  post-holiday, travel week, injury return.

## Step 11 — Studio: rolling plan UI

- **Purpose:** Surface the proposed horizon in the UI, let the user accept,
  reject, or edit, and preserve completed workouts.
- **Done when:** The UI shows the suggested workouts with reasoning, lets the
  user accept or edit them, and saves through the existing program editing
  pipeline.
- **Depends on:** Step 10.
- **Primary files:** Studio UI, new server endpoints, related tests.
- **Test strategy:** End-to-end server tests for accept/reject/regenerate
  flows.

## Step 12 — Broader goals, preferences, and variation

- **Purpose:** Add runner preferences, broad-goal modulation, and variation
  across recipes without breaking the key-workout rule.
- **Done when:** A runner profile can hold preferences. Recommendations and
  the generator pick recipes using preferences. Variation is applied
  intentionally and documented.
- **Depends on:** Step 11.
- **Primary files:** `src/runplan/domain/preferences.py` (new), coaching
  module, generation module.
- **Test strategy:** Parametrised tests for preference influence and
  variation.

## Order

Step 0 → Step 1 → Step 2 → Step 3 → Step 4 → Step 5 → Step 6 → Step 7 →
Step 8 → Step 9 → Step 10 → Step 11 → Step 12.

Steps 9–12 are later opportunities that become practical only after Step 8.
Earlier steps must not assume UI features or use cases that do not exist yet.