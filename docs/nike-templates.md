# Nike Run Club training plan templates

Runplan bundles four training plan templates adapted from the public Nike Run
Club training plans for the 5K, 10K, half-marathon, and marathon distances. The
templates are stored as static YAML files under
`src/runplan/templates/programs/`. They are exposed through the Python
`runplan.templates` module and through the Runplan Studio catalog at
`/api/templates`.

## Source material

The original Nike Run Club training plans that informed these templates are
preserved under `docs/source/nike/`:

- `Nike-Run-Club-5K-Training-Plan.md`
- `Nike-Run-Club-10K-Training-Plan.md`
- `Nike-Run-Club-Half-Marathon-Training-Plan-Audio-Guided-Runs.md`
- `Nike-Run-Club-Marathon-Training-Plan.md`

These are reference documents retained for traceability; the actual bundled
templates live as structured YAML so they can be edited, synced to Garmin
Connect, and surfaced through the Studio.

## Status

The Runplan templates are **unofficial adaptations** of the Nike Run Club
training plans. They preserve Nike's coaching language, workout names, and the
weekly structure of the original plans, while converting distances to metric
units and encoding the runs as standard Runplan workouts.

### Personalised pacing

The pacing targets in the original plans refer to a "Pace Chart" that depends
on the runner's recent race performances. Runplan resolves every pace at
sync time from a single runner-controlled input:

* The runner sets their **5K best** (a measured race time such as `27:00`)
  and a **Garmin pace zone tolerance** (default `5` seconds per kilometer)
  in the Runplan Studio user settings.
* Every step in the template that carries a symbolic `pace_type` is
  resolved to a concrete pace zone using Riegel's formula at exponent
  `1.07`. Race distances use the predicted race pace; tempo and recovery
  add fixed offsets of `20 s/km` and `60 s/km` to the 5K pace.
* The Garmin workout payload receives a real pace target with the
  configured tolerance. The watch face still shows the original Nike
  wording (for example, `1:00 at 5K Pace`), but the underlying step
  carries a precise pace zone.
* A runner who edits `five_k_best` (or changes the pace zone tolerance)
  sees every future workout step refresh automatically; already-synced
  Garmin workouts are flagged as `Changed since sync` and replaced on the
  next confirmed sync.

For runners who want a fixed target, the pace zone tolerance accepts `0`
to disable widening. For runners who prefer to type an absolute pace, a
step can also carry an explicit `pace: "5:00-5:10 min/km"` value; that
target wins over the symbolic intensity.

## Files

| File | Weeks | Workouts / week | Goal distance | Long-run day | Race week | Pace chart cols |
|---|---|---|---|---|---|---|
| `nike-5k.yaml` | 8 | 5 | 5 km | Saturday | Yes | 7 |
| `nike-10k.yaml` | 8 | 5 | 10 km | Saturday | Yes | 7 |
| `nike-half-marathon.yaml` | 14 | 5 | 21.1 km | Saturday (race Sunday) | Yes | 7 |
| `nike-marathon.yaml` | 18 | 5 | 42.2 km | Sunday (race Sunday) | Yes | 7 |

The 5K and 10K plans follow the same weekly shape: two Recovery Runs, two
Speed Runs, and one Long Run. The half-marathon plan uses NRC Guided Run
workout names and one time-based Long Run (week 12, 60 minutes). The marathon
plan uses three Recovery Runs, one Speed Run, and one Long Run each week,
with three range Long Runs that the runner can scale to feel (the templates
encode the midpoint distance in the run step and keep the range wording in the
note).

## Coaching guide

Every template carries a structured `program.coaching:` block that mirrors
the original Nike Run Club coaching content. The block has the following keys
(all optional, but every bundled Nike template fills the full set):

| Key | Type | Purpose |
|---|---|---|
| `tagline` | text | Short tagline printed above the guide (e.g. "Speed, endurance, recovery and motivation"). |
| `intro_sections` | list of `{title, body}` | "A Great Coach" and "It's Not Just About Running" intros. |
| `plan_tips` | list of `{title, body}` or `{title, items}` | "This plan works for you", "Training starts when you start", "Tools to take you farther". |
| `weekly_workouts` | list of `{title, body}` | Definitions of Speed Runs, Long Runs, Recovery Runs, Rest Days. |
| `pace_chart` | object | Nike Run Club Pace Chart with intro, columns, 15 rows, and 2 worked examples. Columns are listed with label and description. |
| `glossary` | list of `{term, definition}` | Types of Runs (Progression, Intervals, Fartlek, Hills, Tempo Run). The half-marathon plan adds "Audio Guided Run". |
| `pace_types` | list of `{name, effort, description}` | Best / 1K / 5K / 10K / Tempo / Recovery pace. |
| `things_to_know` | list of strings | Three bullets about how to use the paces. |
| `situational_advice` | list of `{title, body}` | The eight "If you..." advice blocks. |

The Studio renders the block as a collapsible **Coaching guide** section
above the calendar. Markdown, HTML and PDF exports all render the guide as
their first page (after the cover).

### Pace chart units

The pace chart is **metric** (min/km) for every column except the first.
The runner finds their row by personal-best 1K time, then reads the
target paces directly in min/km:

- `1K best` stays in minutes per kilometer so the row matches a runner's
  known 1K PR.
- `5K best / avg km`, `10K best / avg km`, `Half marathon best / avg km` and
  `Marathon best / avg km` keep the original race time in `h:mm` or `h:mm:ss`
  and compute the per-kilometer pace from that time and the race distance
  (rounded to the nearest 5 seconds) using Riegel 1.07. For example, a
  runner whose 1K best is `5:00 min/km` gets a predicted 5K of `27:55`
  with an average pace of `5:35 min/km`.
- `Tempo min/km` and `Recovery min/km` are pure pace values derived from
  the 5K pace (`+20 s/km` and `+60 s/km`).

The worked examples report target paces for each runner's row so the
runner can copy the values directly into Garmin Connect.

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

1. Drop a YAML file in `src/runplan/templates/programs/` with a `program`
   block that includes both weeks and a `coaching:` block.
2. Add the file name to `TEMPLATE_FILENAMES` in
   `src/runplan/templates/catalog.py`.
3. Extend `_program_distance` so the catalog exposes a goal distance and
   label.
4. Re-export any new public helpers in
   `src/runplan/templates/__init__.py` and `src/runplan/__init__.py`.
5. Extend the tests under `tests/test_nike_templates_*.py` and
   `tests/test_coaching_*.py`.

No new CLI command is needed: the templates are surfaced exclusively through
the Studio catalog. The Garmin sync and export flows remain unchanged because
each template is a regular Runplan YAML program.
