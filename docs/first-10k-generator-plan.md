# First 10K program generator implementation plan

Status: Ready for implementation

## Goal

Implement the complete MiniMax-powered **Complete your first 10K** program
generation MVP end to end. Continue through every implementation bid without
requesting intermediate approval. Do not declare the goal complete until every
checklist item is finished, every bid is committed separately after
`uv run python scripts/check.py` passes, documentation and the changelog are
updated, and the final worktree contains no uncommitted changes from this
implementation.

Implementation stops only for a real blocker that requires a user decision or
secret. A missing MiniMax key is not a blocker because automated tests use
fakes and mocked transports.

## User story

As a Runplan user, I want to describe my current running level, schedule, club
sessions, and races and receive a validated YAML draft for completing my first
10K, so that I can review and edit the program in Runplan's existing editor
before choosing whether to synchronize it with Garmin.

## Product contract

The generator is a new entry point into the existing Runplan workflow:

```text
Form input
  -> first 10K blueprint and user constraints
  -> MiniMax M3
  -> technical and coaching validation
  -> at most one repair attempt
  -> editable YAML draft
  -> explicit save
  -> existing calendar and editor
  -> existing Garmin preview and sync
```

Generation never saves a program or mutates Garmin automatically.

### Included in the MVP

- One blueprint: `Complete your first 10K`.
- MiniMax M3 as the only generation provider.
- A MiniMax Subscription Key supplied through the environment.
- Generation of new programs only.
- An optional main race date.
- A recommended duration of 8 to 16 weeks.
- An advanced custom duration of 4 to 52 weeks.
- Explicit training weekdays.
- Recurring running-club sessions.
- Intermediate B races.
- Additional user instructions without full system-prompt editing.
- YAML review before persistence.
- At most one automatic repair attempt for invalid model output.

### Excluded from the MVP

- A 10K time-improvement blueprint.
- Other goal distances or blueprints.
- Automatic adaptation based on completed Garmin activities.
- AI revision of an existing saved program.
- OpenAI or Codex OAuth.
- Full system-prompt editing.
- Background generation jobs or a queue.
- Automatic Garmin synchronization.
- Claims that generated programs are coach-approved.

## Standard generation flow

The web application adds a **Generate program** action beside the existing
upload action and in the empty-program state. The dialog presents three focused
sections and one collapsed **Advanced** section.

### Goal

- The blueprint is fixed to `Complete your first 10K`.
- The user can select a main race date or choose **I don't have a race date**.
- Runplan proposes the start week and duration.
- With 8 to 16 available weeks, the program uses the period through race week.
- With more than 16 available weeks, Runplan proposes a 16-week program that
  starts later.
- With fewer than 8 available weeks, Runplan shows a clear warning and exposes
  the custom-duration escape hatch under **Advanced**.
- The main race is an explicit 10K workout on the selected date.
- Without a race date, the default is 12 weeks starting in the next ISO week.
- Without a race date, the last week ends with a 10K test run.

### Current running

The standard form collects:

- Average weekly distance over the last four weeks.
- Current number of running days per week.
- Longest recent run as either distance or duration.
- An optional recent 5K result.
- An optional normal easy pace.
- Optional concise constraints or preferences.

Zero current weekly distance is valid. The blueprint then requires a cautious
run/walk start. A short plan combined with a very low starting level produces a
visible warning but remains available through **Advanced**.

### Weekly schedule

- The user selects explicit weekdays.
- Three running days is the default.
- The standard flow recommends three or four days.
- **Advanced** permits two to seven days.
- Runplan proposes one selected day as the long-run day.
- The user can change the proposed long-run day.
- Consecutive running days produce a warning rather than an absolute block.

### Running-club sessions

Any selected day can be marked as a recurring club session with:

- Weekday.
- Classification: `easy`, `long`, `quality`, or `unknown`.
- Expected distance or duration.
- An optional note about the usual session.

A club session occupies one selected running day and contributes to weekly
load. It normally repeats every week. A `quality` club session consumes the
week's quality slot. An `unknown` club session is treated conservatively as a
possible quality session. A main race or B race replaces a club session on the
same date.

## Advanced options

The collapsed **Advanced** section contains:

- A custom start week.
- A custom duration from 4 to 52 weeks.
- A maximum weekly distance.
- A maximum long-run distance.
- A progression profile: `cautious`, `balanced`, or `ambitious`.
- Zero or one quality session per week for this blueprint.
- B races.
- Additional generation instructions.

Defaults are:

| Field | Default |
| --- | --- |
| Duration without race date | 12 weeks |
| Running days | 3 |
| Progression | Balanced |
| Quality sessions | 0 |
| Long run | Easy effort |
| Structured pace targets | None unless the user supplies known pace data |

## B races

A B race contains:

- Date.
- Distance.
- Intensity: `all-out`, `controlled`, or `training run`.
- An optional note.

The B race must fall inside the program period, replaces the day's normal
workout, contributes to weekly load, and causes surrounding load to be reduced.
`all-out` and `controlled` consume the week's quality slot. The main race wins
any date conflict.

## Blueprint and coaching policy

The first 10K blueprint is a versioned coaching policy, not a complete example
YAML file. It defines:

- The goal and intended runner.
- Supported and recommended durations.
- Foundation, build, consolidation, and taper phases.
- Placement of easy runs, long runs, optional quality, club sessions, and
  races.
- Recovery-week expectations.
- Progression and maximum-load constraints.
- The required Runplan YAML contract.

The deterministic outline fixes weeks, weekdays, stable workout IDs, and
workout intent before MiniMax is called. MiniMax creates the detailed workout
steps and descriptions within that outline. The candidate validator maps the
result back to the outline instead of guessing intent from workout names.

### Progression limits

| Profile | Maximum normal increase |
| --- | --- |
| Cautious | 5 percent or 1 km |
| Balanced | 8 percent or 1.5 km |
| Ambitious | 10 percent or 2 km |

The larger of the percentage and small absolute allowance applies so that low
starting volumes can progress meaningfully.

Additional rules are:

- Week one normally stays between 80 and 110 percent of current weekly load.
- Zero or very low current load uses a separate cautious starting rule.
- At most three increasing weeks occur consecutively.
- Recovery weeks normally reduce load by 10 to 20 percent.
- Load after recovery must not jump materially above the previous peak.
- A long run normally increases by at most 1 km or 10 percent at a time.
- User-provided weekly and long-run maxima are never exceeded.
- A long run normally contributes no more than about 40 to 45 percent of the
  week's distance.
- Quality sessions do not occur on consecutive days.
- Club quality and B races consume the week's quality slot.
- Race week reduces other training load.
- The goal race is exactly 10 km and receives no invented pace target.

These are generation constraints, not general medical advice.

### Pace and intensity

- MiniMax must not invent a concrete pace.
- A known 5K result or easy pace may inform realistic targets.
- Easy runs and easy long runs primarily use effort descriptions.
- Warmup, cooldown, and recovery never receive structured pace targets.
- The standard program contains no quality session.
- **Advanced** can enable at most one quality session per week.
- Quality in a completion program should be light fartlek or controlled blocks,
  not aggressive track training.
- Without known pace data, descriptions communicate intensity instead of a
  Garmin pace target.

## MiniMax integration

The server reads one optional environment variable:

```dotenv
RUNPLAN_MINIMAX_API_KEY=...
```

The key is forwarded through Docker Compose but never returned to the browser,
written to YAML, or included in logs and exceptions. A single MiniMax account
is shared by the personal Runplan installation. Runplan starts normally when
the key is absent; only generation is unavailable.

Fixed MVP settings are:

- Endpoint: `https://api.minimax.io/v1/chat/completions`.
- Model: `MiniMax-M3`.
- Thinking: adaptive with reasoning returned separately.
- Non-streaming requests.
- No model tools.
- A fixed timeout, initially 120 seconds.
- A bounded response size.
- No hidden transport retries.
- At most one semantic repair attempt.

The provider remains behind an application port:

```python
class PlanGenerator(Protocol):
    def generate(self, prompt: str) -> str: ...
```

The production implementation uses MiniMax. Tests use a fake or mocked HTTP
transport and never contact a real account.

## Generation pipeline

1. Validate form input on both client and server.
2. Normalize dates, weeks, weekdays, club sessions, and races.
3. Build the deterministic first 10K outline.
4. Calculate recommendations and pre-generation warnings.
5. Build a prompt from the YAML contract, blueprint, outline, and user input.
6. Call MiniMax M3 and request YAML without explanatory text.
7. Remove at most one unambiguous YAML Markdown fence.
8. Parse with Runplan's existing YAML parser.
9. Convert the complete program to the existing typed domain models.
10. Validate the candidate against the outline and coaching constraints.
11. On failure, send the candidate and precise errors to MiniMax once.
12. Validate the repaired candidate through the same complete pipeline.
13. Return a remaining invalid candidate with diagnostics as an editable error
    draft.
14. Return a valid candidate with filename, summary, and warnings.
15. Persist only after the user selects **Add to Runplan**.

Prompts, model reasoning, raw output, and personal form input are not logged.

## YAML and persistence boundaries

Generated content uses the existing program format without a schema change:

- No generated `tracking` section.
- No required workout-type field.
- Stable workout IDs supplied by the deterministic outline.
- Main and B races are ordinary workouts.
- Club sessions are ordinary workouts with human-readable instructions.
- Runplan suggests a program ID and filename.
- The YAML is editable before persistence.
- The existing upload flow revalidates filename, program ID, size, and
  conflicts.

After saving, Runplan opens and activates the program in the existing calendar.
Editing, export, preview, and Garmin sync continue to use their current flows.

## Web API

New authenticated endpoints are:

```text
GET  /api/program-generation/status
POST /api/programs/generate
```

The status endpoint reveals only whether generation is configured. The
generation response has this shape:

```json
{
  "filename": "first-10k-2026.yaml",
  "content": "...",
  "warnings": [],
  "summary": {
    "weeks": 12,
    "workouts": 36
  }
}
```

Expected HTTP errors are:

| Status | Meaning |
| --- | --- |
| 400 | Invalid form input |
| 409 | A generation is already running for the user |
| 422 | Model output remains invalid after repair |
| 429 | MiniMax quota or rate limit reached |
| 503 | Generation is unconfigured or MiniMax is unavailable |
| 504 | MiniMax timed out |

Only one generation per Runplan user runs at a time. The existing upload API
remains the only persistence boundary.

## Privacy boundary

Only data needed for program generation is sent to MiniMax. Runplan does not
send Garmin credentials, Garmin tokens, web authentication secrets, names,
email addresses, previous Garmin activities, or unrelated program files.

The dialog explains that training information and any health information typed
by the user are sent to MiniMax. The prompt instructs the model not to repeat
private or medical details in program descriptions.

## Working contract for every bid

For each bid, the implementing agent must:

1. Read this roadmap and select the first incomplete bid.
2. Inspect `git status` and preserve all unrelated changes.
3. Implement only the current bid.
4. Run focused tests during development.
5. Mark the bid complete in this document.
6. Run `uv run python scripts/check.py` after all bid changes, including this
   checklist update.
7. Inspect `git status`, `git diff`, and recent commit history.
8. Commit only the bid's intended files with the specified English subject.
9. Continue directly to the next bid without requesting approval.

Do not commit when the complete check is red. Fix the issue and create the
planned commit without amending an earlier commit. Never include unrelated
worktree changes in a bid commit.

## Context recovery

After context compaction or a resumed session:

1. Read `AGENTS.md` and this roadmap.
2. Inspect `git status`, `git diff`, and recent commits.
3. Find the first unchecked bid.
4. If that bid has uncommitted changes, understand and continue them rather
   than restarting or reverting them.
5. Continue until the overall goal and definition of done are satisfied.

## Implementation bids

### [x] Bid 0: Persist the roadmap

Deliver this document with the goal, decisions, bid checklist, test contract,
and recovery procedure. Make no functional change.

Verification: Run the complete repository check.

Commit: `Document first 10K generator roadmap`

### [x] Bid 1: Add the generation input model

Add immutable dataclasses and enums for the provider-independent generation
request. Support the main race, current training, longest run in time or
distance, optional pace data, explicit weekdays, long-run day, club sessions,
B races, custom duration, maxima, progression, quality count, and additional
instructions. Add pure normalization, bounds, date conflicts, and automatic
start-week and duration suggestions.

Tests cover ISO boundaries, race dates, the default 12-week program, standard
and custom durations, invalid values, club sessions, and B races.

Commit: `Add first 10K generation inputs`

### [x] Bid 2: Build the first 10K blueprint and outline

Add the versioned blueprint and deterministic outline of weeks and workout
slots. Assign stable workout IDs and intents. Place club sessions before normal
workouts, apply race replacement precedence, reserve quality capacity
conservatively, and model foundation, build, consolidation, and taper phases.

Tests cover two to seven running days, every club classification, main races,
B races, conflicts, taper, and a final test run without a race date.

Commit: `Build first 10K generation outlines`

### [x] Bid 3: Validate generated 10K programs

Validate model output with the existing parser and map occurrences back to the
outline. Calculate load with existing estimates and enforce schedule, first
week, progression, recovery, maximum volume, long-run share, quality, club,
and race constraints. Return structured errors and warnings.

Tests cover valid candidates, every measurable violation, time- and
distance-based workouts, a zero-volume run/walk start, recovery rebound, and
missing or altered outline workouts.

Commit: `Validate generated 10K programs`

### [x] Bid 4: Add the MiniMax adapter

Add `PlanGenerator` to the application ports and implement a synchronous
MiniMax adapter with an injectable transport. Read
`RUNPLAN_MINIMAX_API_KEY`, use the fixed MVP endpoint and model, bound time and
output, map authentication, quota, timeout, and upstream errors, and ensure
secret redaction. Forward the optional key through Compose and document it in
`.env.example`. Do not prevent startup without a key.

Tests use a mocked transport and cover the request, response, all relevant
errors, and secret-safe diagnostics. No test contacts MiniMax.

Commit: `Add MiniMax plan generator adapter`

### [x] Bid 5: Generate validated program drafts

Add the application service that builds the prompt, calls the provider, strips
one optional YAML fence, parses and validates the candidate, and performs at
most one repair attempt. Return content, suggested filename, summary, warnings,
or an invalid editable draft with diagnostics. Never persist from this use
case and never log sensitive content.

Tests cover first-pass success, fenced YAML, successful repair, repeated
failure, empty and oversized output, naming, and the no-persistence boundary.

Commit: `Generate validated 10K program drafts`

### [x] Bid 6: Expose the program generation API

Add authenticated status and generation routes, parse requests into typed
input, inject generation separately from Garmin sync, serialize results, map
errors, and prevent concurrent generation for the same user. Preserve the
existing upload endpoint as the only save operation.

Tests cover authentication, configured and unconfigured status, successful
generation, every error class, concurrency, route ordering, and the absence of
program files before explicit upload.

Commit: `Expose program generation API`

### [x] Bid 7: Add the standard generation dialog

Add the responsive, accessible **Generate program** action and standard dialog.
Support race date or no date, current training, optional pace data, explicit
weekdays, proposed long-run day, loading, errors, warnings, editable YAML
review, and explicit persistence through the existing upload flow. Open and
activate the program after save. Never initiate Garmin sync.

Tests cover asset contracts, the standard request, capability state, loading,
errors, review before save, upload and activation, keyboard behavior, and
mobile layout.

Commit: `Add first 10K generation dialog`

### [ ] Bid 8: Add advanced generation constraints

Add the collapsed **Advanced** section with custom dates and duration, weekly
and long-run maxima, progression, quality count, dynamic club sessions,
dynamic B races, additional instructions, warnings, and the MiniMax privacy
notice. Do not expose the system prompt.

Tests cover serialization, adding and removing repeated fields, client-side
validation, conflicts, warnings, and narrow layouts.

Commit: `Add advanced 10K generation options`

### [ ] Bid 9: Add evaluation scenarios and hardening

Add 10 to 15 anonymized requests and fake model outputs spanning low and
moderate starting volume, two to five days, every club type, race and no-race
programs, B races, known and unknown pace, strict maxima, and custom durations.
Review logging and HTTP errors for sensitive content. An optional manual live
smoke command may exist but must never run in the automated test suite.

Commit: `Add 10K generation evaluation scenarios`

### [ ] Bid 10: Document AI-generated 10K programs

Document environment setup, the form and draft workflow, Garmin boundaries,
and the MiniMax privacy model in the README. Update durable design decisions,
the maintained generation prompt where required, the roadmap wishing well, and
`CHANGELOG.md` under `Unreleased`. Mark this final bid complete.

Commit: `Document AI-generated 10K programs`

## Definition of done

The overall goal is complete only when:

- All eleven bids are checked and committed.
- Every commit was created only after `uv run python scripts/check.py` passed.
- The MiniMax key remains server-side and is redacted from diagnostics.
- Runplan starts without MiniMax configuration.
- Generation produces a reviewable, editable draft.
- Generation never saves or synchronizes automatically.
- Club sessions, races, dates, and user constraints are validated.
- The standard flow remains simple and advanced controls remain collapsed.
- Desktop and mobile behavior are covered.
- Documentation and the changelog are current.
- The final complete check passes.
- All planned commits exist.
- No uncommitted changes from this implementation remain.
