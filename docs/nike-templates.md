# Nike Run Club training plan templates

Runplan bundles four training plan templates adapted from the public Nike Run
Club training plans for the 5K, 10K, half-marathon, and marathon distances. The
templates are stored as static YAML files under
`src/runplan/templates/programs/`. They are exposed through the Python
`runplan.templates` module and through the Runplan Studio catalog at
`/api/templates`.

## Status

The Runplan templates are **unofficial adaptations** of the Nike Run Club
training plans. They preserve Nike's coaching language, workout names, and the
weekly structure of the original plans, while converting distances to metric
units and encoding the runs as standard Runplan workouts.

The pacing targets in the original plans refer to a "Pace Chart" that depends
on the runner's recent race performances or self-assessment. Runplan does not
assume a fixed pace for any runner and keeps every pace reference in the
`note` field of each step. Garmin Connect therefore receives no implicit pace
zones until the runner adds their own. The watch face still shows the
original Nike wording (for example, `1:00 at 5K Pace`).

## Files

| File | Weeks | Workouts / week | Goal distance | Long-run day | Race week |
|---|---|---|---|---|---|
| `nike-5k.yaml` | 8 | 5 | 5 km | Saturday | Yes |
| `nike-10k.yaml` | 8 | 5 | 10 km | Saturday | Yes |
| `nike-half-marathon.yaml` | 14 | 5 | 21.1 km | Saturday (race Sunday) | Yes |
| `nike-marathon.yaml` | 18 | 5 | 42.2 km | Sunday (race Sunday) | Yes |

The 5K and 10K plans follow the same weekly shape: two Recovery Runs, two
Speed Runs, and one Long Run. The half-marathon plan uses NRC Guided Run
workout names and one time-based Long Run (week 12, 60 minutes). The marathon
plan uses three Recovery Runs, one Speed Run, and one Long Run each week,
with three range Long Runs that the runner can scale to feel (the templates
encode the midpoint distance in the run step and keep the range wording in the
note).

## Conventions

- `program.id` is the version-neutral template id (`nike-5k`, `nike-10k`,
  `nike-half-marathon`, `nike-marathon`). A copy receives a per-user id of the
  form `<template-id>-<start-week>` so that each user keeps a stable Garmin
  identity after copying.
- `short_name` follows the 2-10 character Runplan rule (`N5K`, `N10K`,
  `NHM`, `NMAR`). It appears in every Garmin workout title as
  `<SHORT> - W<week> - <workout name> - <distance>`.
- Every step carries an optional `note` that holds the original Nike wording.
  This keeps the watch-facing copy faithful to Nike's instructions.
- The day distribution follows the order of Nike's source PDF (for example,
  `Mon Recovery · Tue Speed · Wed Recovery · Thu Speed · Sat Long` for the
  5K plan). Users can rearrange, delete, or replace workouts after copying.

## Adding a new template

The catalog is intentionally small and code-driven:

1. Drop a YAML file in `src/runplan/templates/programs/`.
2. Add the file name to `TEMPLATE_FILENAMES` in
   `src/runplan/templates/catalog.py`.
3. Extend `_program_distance` so the catalog exposes a goal distance and
   label.
4. Re-export any new public helpers in
   `src/runplan/templates/__init__.py` and `src/runplan/__init__.py`.
5. Extend the tests under `tests/test_nike_templates_*.py`.

No new CLI command is needed: the templates are surfaced exclusively through
the Studio catalog. The Garmin sync and export flows remain unchanged because
each template is a regular Runplan YAML program.
