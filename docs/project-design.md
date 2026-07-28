# Runplan: product design and architecture

This document records durable product and architecture decisions. Immediate
work belongs in [PLAN.md](../PLAN.md).

## Vision

Runplan is a flexible tool for creating, validating, previewing, exporting, and
syncing structured running programs. It consists of three equal product areas:

1. A training-philosophy-neutral engine and CLI.
2. Maintained prompts that can guide either an LLM or a person.
3. General programs that work out of the box and remain easy to customize.

The CLI is the first interface, but domain logic and use cases must not depend
on terminals, local files, or Garmin. The next interface is a web API and
frontend, beginning with high-level program editing and access to the CLI's
validation, preview, export, and sync capabilities. Program YAML is portable
source content; sync status and history are application data and stay outside
YAML.

The web frontend uses progressive disclosure. Program metadata and workout
scheduling have focused visual controls, while an individual workout can be
opened in a YAML editor. A form-based workout builder is a later capability.
Generic programs are immutable source content: editing one creates a personal
copy. Personalized LLM generation is also later and produces a reviewable,
validated draft rather than content that is synced automatically.

## Web planning experience

The weekly Monday-to-Sunday calendar is the primary planning surface. Each day
has one workout slot. Moving a workout to an empty day fills the slot; moving it
to an occupied day swaps the two workouts. Multiple workouts on one day are not
part of the default model. They may be introduced later through an explicit
opt-in program setting.

Workout cards show estimated distance and duration, and week headers show total
estimated distance. Values that depend on fallback pace are visibly marked as
approximate. The web frontend uses the same estimation implementation as
Garmin titles, previews, and exports so totals cannot drift between surfaces.

Calendar movement supports pointer interaction first, with touch and keyboard
alternatives required before the workflow is complete. Moves retain stable
workout IDs and content. Save, validation, and Garmin sync state must be
distinct and unambiguous, and reversible local edits should offer undo.

The complete planning workflow must work on mobile as well as desktop and
tablet. On narrow screens, weeks and days may change layout or use deliberate
horizontal navigation, but workout information, movement, dialogs, sync, and
primary actions must remain available without relying on hover or a precision
pointer.

The frontend supports light and dark themes. On first use it follows the
operating system preference; an explicit choice is remembered in the browser.
A familiar sun/moon-style toggle sits at the top-right of the page, remains
keyboard and screen-reader accessible, and communicates both the active theme
and the theme that activating it will select.

On the first visit, the browser requires selection of a server-configured
Runplan user. When none exist, the dialog can create the first user from only a
lowercase username and full name; the server persists non-secret configuration
and derives isolated credential, token, and state paths. Garmin credentials are
added separately before sync. The browser remembers the selected user locally,
while each user's active program is persisted in the server-side user registry
and shared by the web frontend and CLI. Opening a valid program updates that
setting; `runplan user set-plan USER FILE` provides the equivalent CLI action.
This selection is convenience state, not authentication or program ownership.

Garmin sync is a separate confirmed action, never an implicit consequence of
saving the plan. It uses the CLI's selection and synchronization use cases,
shows a structured diff before confirmation, and reports progress, results,
and actionable errors. Credentials remain on the server.

The trusted-network web application exposes multiple server-configured Runplan
users without an application login. Each user has a stable non-secret ID,
display name, Garmin credentials-file path, Garmin token-store directory, and
isolated sync state. The settings UI may submit Garmin credentials to the
server, but saved passwords and Garmin tokens are never returned to the browser.
Each user also owns configurable estimation defaults, initially fallback pace,
which must be applied consistently to web summaries, exports, Garmin titles,
and sync previews. All
Garmin operations resolve the supplied user ID against server configuration and
partition clients, state, and future concurrency locks by user. This is user
selection, not authentication or authorization: anyone who can reach the
application can operate every configured user. Consequently this mode must
remain limited to a trusted private network or sit behind an external
authentication and TLS proxy.

The editing sequence deliberately progresses from calendar summaries to sync
and high-level plan editing. A structured form-based workout editor comes last;
the focused YAML editor remains the advanced editing path.

The interaction model draws on training calendars such as Runna and
TrainingPeaks for calendar movement and dense planning, and on Home Assistant's
progressive disclosure between visual controls and YAML. These are references,
not requirements to reproduce their movement limits or interfaces.

## Current architecture

The former monolith has been removed. The package uses these boundaries:

```text
src/runplan/
  domain/          models, step behavior, and domain errors
  application/     preview, selection, sync, results, and ports
  parsing/         YAML and human-readable value parsing
  exporters/       presentation-file exporters
  integrations/    Garmin adapters and mapping
  presentation/    human-readable and machine-readable formatters
  state/           state repository implementations
  cli.py            argument parsing and top-level orchestration
  cli_sync.py       compatibility path for single-week sync behavior
```

Dependencies point inward:

```text
CLI / future API
       |
       v
application use cases <--- ports <--- Garmin, state, and export adapters
       |
       v
     domain
```

Rules:

- `domain` imports no Garmin, ReportLab, CLI, filesystem, or environment code.
- `application` works with domain models and injected protocols.
- Garmin objects exist only inside the Garmin adapter.
- Exporters should consume one renderer-independent view model.
- The CLI translates arguments into use cases, chooses a formatter, and prints
  the result. It contains no business rules.
- Credentials, state locations, and output paths do not exist as globals in the
  core.
- Interfaces remain synchronous initially. A hosted system may run them as
  background jobs without making the entire domain asynchronous.

## Flexible program format

Workout type is not a required field. Runplan must represent new workout forms
without requiring a new enum or release. Names, descriptions, and generic
recursive steps carry the intent.

The engine enforces structural requirements needed for safe parsing, rendering,
export, and sync:

- Valid fields, units, positive values, and unique stable IDs.
- Deterministic dates, ordering, and recursive step semantics.
- Precise validation locations.
- No assumptions about the frequency or order of workout forms.

Coaching rules primarily belong in maintained prompts and curated programs.
Rules such as placing easy runs between key workouts, time-based interval
recoveries, and pace targets only on interval or tempo work may later become
opt-in lint profiles. They are not mandatory schema fields.

Unknown optional metadata should be preserved if round-trip editing is added.
A format-version field should be introduced only for an actual incompatible
schema change.

## English language policy

English is canonical for:

- Python names, docstrings, comments, exceptions, and user-facing messages.
- YAML field names and maintained program content.
- CLI help, human-readable output, machine-readable keys, and exported labels.
- Tests, fixtures, README files, architecture documents, and prompts.

Published program and workout IDs remain stable because changing an ID changes
sync identity. The bundled IDs were translated before the catalog had active
sync state. User-authored content may contain any language and must retain
Unicode support. Machine-readable values and JSON keys remain stable across
wording changes.

Canonical product vocabulary is defined in
[terminology.md](terminology.md).

## Prompt collection

Prompts are product content, not copies scattered through unrelated files. The
collection should combine reusable base rules with goal- and situation-specific
guidance, while every published prompt remains independently copyable.

A maintained prompt should:

- Collect goals, dates, history, weekdays, volume, known paces, injury
  considerations, and preferences without inventing missing data.
- Separate technical format requirements from coaching recommendations.
- Require realistic progression, recovery, and explicit handling of uncertainty.
- Explain supported duration, distance, pace, and repeat syntax.
- Require validation by Runplan before sync.

Planned prompt families include 5K, 10K, half marathon, marathon, return after
a break, limited training days, and adapting an existing program. Future
commands may expose them as `runplan prompt list` and `runplan prompt show`.

## Curated programs

The repository should contain general programs that can be used directly and
remain easy to copy and edit. They must state assumptions about runner level,
weekly volume, intensity, and progression.

Every published program should have:

- A stable ID, title, short Garmin title identifier, goal, intended runner,
  duration, and training frequency.
- A complete valid YAML document using only supported syntax.
- No personal dates or data that make sense for only one runner.
- A generated human-readable preview.
- Automated validation and export coverage.
- A short limitations note and a lightweight coaching review record.

Personal programs remain useful fixtures but should live outside the general
catalog without being deleted.

## Week selection and safe sync

Preview, sync, and export should share one `WeekSelection` model supporting:

- explicit weeks, comma-separated weeks and ranges, and the named values
  `current`, `next`, and `all` through `--select-weeks`;
- rolling sync of the current complete plan week plus N subsequent weeks
  through `--weeks-ahead N`, defaulting to 1 for sync.

Selectors are mutually exclusive. Ranges are normalized, sorted, deduplicated,
and validated against the program. Relative selection uses the program start
date and an injected clock.

Sync is additive by default:

- Create, update, reuse, and schedule selected workouts.
- Preserve already synced weeks outside the selection.
- Never delete something merely because it was not selected.
- Remove owned objects whose identity no longer exists in the full active plan.

Removal requires explicit `--prune` intent. Runplan shows the structured diff
and asks for confirmation; `--yes` is the explicit non-interactive alternative.
Pruning is calculated against the union of every selected week and deletes only
future active records whose ownership is verified. Completed history, missed
workouts, and recorded activities are preserved locally. Independently of
prune, normal sync removes owned Garmin calendar entries and uploaded workout
templates after a workout becomes completed or missed. It then clears those
remote IDs locally while retaining activity IDs and actual results. State is
persisted after each externally successful operation so retries can continue
safely.

Each real sync builds one ephemeral Garmin inventory. Workout templates are
paginated once, relevant calendar months are fetched once each, and activity
summaries are reused within the operation. Reconciliation, terminal cleanup,
orphan cleanup, and selected-week synchronization share this snapshot and
update it after mutations. This keeps external calls proportional to Garmin
pages and relevant months rather than multiplying them by sync phase or week.

Every real sync first reconciles historical managed schedules. A Garmin
`associatedActivityId`, or an activity summary whose
`metadataDTO.associatedWorkoutId` matches the managed workout, marks a workout
completed. The completed record includes Garmin's actual distance and total
duration; a past occurrence without an
associated activity becomes missed. Both are terminal for automatic sync and
prune. Their owned Garmin schedule and workout template are automatically
cleaned up, but recorded activities are never deleted. Compact terminal history
remains in local state so later syncs cannot recreate it and future reporting
can compare planned and completed training.
Selected occurrences are also compared with Garmin before synchronization, so
an association on the current day or after local state loss is still recorded
as completed. Matching requires tracked Garmin IDs or valid ownership metadata.
An ID persisted after a Runplan create response is authoritative ownership even
if the remote object is later edited. Selected changed objects are replaced by
creating and scheduling the corrected template before deleting the old one; a
missing tracked object is recreated. Valid ownership metadata is sufficient to
clean an untracked orphan for the current user and active program. Other users,
other programs, and unmarked untracked objects are never adopted or deleted.

User-based CLI sync resolves the active program, credentials, tokens, default
pace, state directory, and ownership ID from the selected profile. `sync --all`
processes profiles sequentially, skips profiles without an active program, and
continues after failures while returning a failure status for a partial batch.

## Recoverable Garmin ownership

The user's YAML embeds synchronization knowledge and completed results, but is
not the sole proof that Runplan owns a Garmin object. Every Garmin workout
created or updated by Runplan must carry a versioned ownership envelope in a
strictly delimited suffix of its description. The visible workout title remains
human-readable. The envelope contains enough stable information to reconstruct
identity and verify content after local state is lost: the full program ID,
source week and workout ID, planned occurrence date, and canonical content
hash. The representation must be ASCII-safe, escaped deterministically, small
enough for Garmin's verified description limit, and preserved unchanged by a
Garmin create/read round trip. Parsing an unknown future version is an explicit
unsupported result, never a best-effort interpretation.

Recovery is a distinct import operation, not a side effect of ordinary sync.
For one selected Garmin profile and local program, it reads all Garmin workout
templates and calendar occurrences covering the program date range, parses
valid ownership envelopes, joins templates to schedules and associated
activities, and compares them with the current compiled local plan. It first
returns a reviewable, non-mutating diff. Explicit confirmation atomically
rebuilds the profile-and-program state with recovered remote IDs, dates,
content hashes, and lifecycle evidence. Repeating recovery against unchanged
Garmin data is idempotent.

The implemented `v1` envelope is an unpadded base64url encoding of canonical,
compact JSON in a `[runplan:v1:<payload>]` description suffix. Its fields are
the stable Runplan owner ID (`o`), program ID (`p`), source week (`w`), workout
ID (`i`), planned date (`d`), and SHA-256 content hash (`h`). The CLI exposes
preview plus `--yes`; the web flow lives under user settings and requires a
fresh confirmation token before the per-user program state is replaced.

Recovery is conservative. A valid ownership envelope is required for automatic
adoption; a matching title, short name, human description, date, or workout
shape is insufficient. Duplicate identities, multiple schedules, metadata and
remote-content hash disagreement, missing local workout keys, unsupported
versions, and incomplete historical evidence are conflicts or unresolved
records for review. Recovery never changes or deletes Garmin data. Legacy
Runplan workouts without envelopes may be listed as candidates but cannot be
claimed automatically; a later confirmed normal sync can migrate them by
writing current ownership metadata.

## Export

PDF, HTML, and Markdown should render the same normalized information:

- Program metadata and selected week range.
- A heading such as `Week 3 (2026-08-10 to 2026-08-16)`.
- Workout headings using weekdays rather than repeated ISO dates.
- Workout description, known duration and distance, nested steps, and pace
  targets.

One renderer-independent export view model should prevent the formats from
drifting.

HTML must be standalone, semantic, printable, free of JavaScript and external
assets, and must escape all user content. Markdown must be deterministic
CommonMark with indented repeat groups and no HTML-only dependencies. Exporters
write files but do not choose programs or perform sync.

## Web and hosted boundaries

The web frontend must call the same application use cases as the CLI rather
than reproduce domain behavior in browser code. Keep these boundaries explicit:

- No request or user state in module globals.
- Garmin credentials and clients can be instantiated per user.
- State storage sits behind a repository port and includes a version.
- Use cases accept serializable input and return serializable results.
- Sync operations expose progress, structured errors, and idempotency keys.
- Concurrent syncs for the same user and program can be locked.
- Domain time uses explicit time zones and an injected clock.
- HTML output can serve as a server-rendered preview.
- Credentials, tokens, generated plans, and audit data have explicit ownership
  and tenant boundaries.
- Garmin ownership metadata and recovered sync state are scoped by Runplan user
  as well as program; recovery for one user cannot observe or adopt another
  user's objects.
- Browser clients never receive Garmin credentials or tokens.
- Program writes use document revisions or equivalent optimistic concurrency;
  a stale browser must not silently overwrite a newer revision.
- Supported visual edits and workout YAML edits round-trip without losing
  unknown optional metadata or changing stable program and workout IDs.
- External actions remain separate from document saves. Garmin sync always
  exposes a structured dry-run diff and requires the same explicit intent as
  the CLI.

## Quality requirements

- No test contacts a real Garmin account.
- External objects use stable internal keys.
- Parser errors identify the precise YAML location.
- Domain behavior has strong unit coverage; adapters use contract or integration
  tests with fakes.
- Date tests cover month and year boundaries, leap years, and time zones.
- Exporters escape user content correctly.
- Logging must never expose credentials, tokens, or unnecessary health data.
- Every migration remains releasable without leaving the main branch broken.

## Open decisions

1. Keep CLI state in JSON until hosting, or move early to SQLite?
2. Add reusable workout templates across weeks, or retain explicit workouts for
   readability and version control?
3. Should editing a program ID create a new program, or be a supported rename
   operation with state migration?
4. Should opt-in lint profiles live in Runplan, the prompt collection, or
   separate community packages?
5. What coaching review and source notes should accompany published programs?
6. Ship the catalog inside the Python package or as a separately versioned
   content package?
7. Which YAML round-trip representation can preserve unknown metadata and, if
   required, comments and formatting while supporting safe structured edits?
