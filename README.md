# Runplan

Runplan validates, previews, exports, and syncs YAML-based running programs.
The bundled beginner plan starts with workouts such as:

- 7 minutes of brisk walking
- 6 × (30 seconds of very easy running + 2 minutes of walking)
- 5 minutes of easy walking

## Run the web frontend

Runplan Studio requires one shared web password. Generate the recommended
salted verifier, copy the output, and set it before starting the server:

```bash
uv run runplan hash-password
export RUNPLAN_WEB_PASSWORD_HASH='pbkdf2_sha256:600000:...:...'
uv run runplan serve
```

For a small temporary setup, `RUNPLAN_WEB_PASSWORD` may contain the raw
password instead. Set exactly one password variable; missing, empty, invalid,
or double configuration stops server startup. The verifier is
password-equivalent and must still be kept secret. There is no minimum password
length, but a strong passphrase is recommended.

To make it reachable from other machines on a trusted private network, listen
on all interfaces:

```bash
uv run runplan serve --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000`. The first visit shows a password field. A
successful login sets a 10-year HttpOnly, SameSite cookie, so the same browser
does not ask again unless site data is removed or the configured password
changes. Each Runplan user has an isolated directory under
`~/.local/share/runplan/programs` by default. A new user starts without programs
and can upload a valid `.yaml` or `.yml` plan in the web frontend. Set
`RUNPLAN_PROGRAM_DIR` or pass `--program-dir` to use a different server-side
root directory. It supports plan name,
description, and start-week editing, drag-and-drop workout scheduling, workout
creation and editing through validated YAML, deletion with confirmation, and
YAML, Markdown, and PDF downloads. Empty calendar days provide a valid starter
workout and an inline reference for the supported step, duration, distance,
pace, and repeat syntax. A week must retain at least one workout. Deleting a
previously synchronized workout queues its Garmin cleanup for the next reviewed
and confirmed sync rather than contacting Garmin immediately.
Completed workouts are locked in the calendar and cannot be dragged, moved, or
swapped on desktop or mobile. Change their `day` directly in YAML only when a
completed history entry genuinely needs correction.

### Generate a first 10K program

Runplan Studio can use MiniMax M3 to generate a **Complete your first 10K**
program. Generation is optional: the server starts normally without a key, but
the generation action remains unavailable. To enable it for a local server, set
the MiniMax Subscription Key only in the server environment:

```bash
export RUNPLAN_MINIMAX_API_KEY='your-subscription-key'
uv run runplan serve
```

For Docker Compose, set `RUNPLAN_MINIMAX_API_KEY` in the local `.env` file. The
key is passed to the container and is never sent to the browser or written to a
program.

Select **Generate program**, enter the current weekly training, longest recent
run, available weekdays, long-run day, and optional race date, then generate the
draft. Runplan recommends a period and builds a fixed calendar outline before
MiniMax fills in the workout details. The collapsed **Advanced** section covers
custom periods, running-club sessions, B races, progression, weekly and long-run
limits, optional quality sessions, known pace data, and extra guidance.

The result opens as validated, editable YAML. Review the warnings and complete
program, make any needed edits, and select **Save program** only when it is
ready. Generation itself neither saves the draft nor contacts Garmin. Saving
adds the program to the existing calendar; Garmin changes still require the
normal preview and explicit sync confirmation. Generated training is not a
substitute for individual medical or coaching advice.

Only the supplied training details, dates, constraints, club sessions, races,
pace data, and additional guidance needed to create the program are sent to
MiniMax. Health information included in additional guidance is therefore also
sent to MiniMax. Runplan does not send Garmin credentials or tokens, Studio
authentication secrets, names, email addresses, previous Garmin activities, or
unrelated program files. The server keeps the MiniMax key private, omits request
bodies and generated YAML from logs, and returns fixed provider error messages.

`runplan serve` writes operational logs to stdout for container and service
log collectors. `INFO` is the default and includes YAML changes, user and plan
changes, Garmin mutations, sync summaries, and server lifecycle events. Use
`DEBUG` for Garmin reads and HTTP access details, or raise the threshold to
`WARNING`, `ERROR`, or `CRITICAL`:

```bash
uv run runplan serve --log-level DEBUG
RUNPLAN_LOG_LEVEL=WARNING uv run runplan serve
```

The CLI option overrides `RUNPLAN_LOG_LEVEL`. Recoverable missing or changed
Garmin IDs are warnings; failed external operations and request exceptions are
errors. Logs include safe identifiers and dates but redact e-mail addresses,
passwords, tokens, secret paths, request bodies, YAML content, and Garmin
payloads. Rotation and retention are delegated to Docker, systemd, or the
surrounding runtime.

Markdown and PDF downloads are generated from the YAML source and are not
written into the source checkout. CLI exports should likewise use an output
path in the server data or download directory.

Remote login requires HTTPS by default. A reverse proxy must overwrite
`X-Forwarded-Proto`, be the only external ingress, and be enabled with
`RUNPLAN_WEB_TRUST_PROXY=true`. Direct localhost HTTP remains available for
development. `RUNPLAN_WEB_REQUIRE_HTTPS=false` exists for explicit test setups,
but the browser challenge uses Web Crypto, which browsers normally expose only
on HTTPS and localhost. Challenge-response avoids sending the password itself,
but HTTP still cannot protect against an active attacker replacing JavaScript.

### Run with Docker Compose

Create the local configuration and set `RUNPLAN_HOST_IP` to the Docker host
interface. Use `127.0.0.1` when a reverse proxy on the same host is the public
entrypoint. Set the desired host port and web password verifier in `.env`:

```bash
cp .env.example .env
# Edit .env before continuing. Find the Tailscale address with: tailscale ip -4
```

Then build and start Runplan in the background:

```bash
docker compose up -d --build
```

Open the HTTPS URL exposed by the reverse proxy, or the configured local URL.
Programs, users, Garmin credentials and tokens, and sync state are persisted in
the bind-mounted `runplan-data` directory. Stop the container without deleting
that data with:

```bash
docker compose down
```

Compose requires both binding values and fails instead of listening on an
unintended interface when either is missing. With, for example,
`RUNPLAN_HOST_IP=127.0.0.1` and `RUNPLAN_HOST_PORT=8080`, Runplan is available
to a reverse proxy on `http://127.0.0.1:8080`. Set
`RUNPLAN_WEB_TRUST_PROXY=true` only when that proxy replaces
`X-Forwarded-Proto` and prevents direct external access to the Runplan port.

#### Automatic Docker host deployment

The files in `deploy/` can update a dedicated production checkout from
`origin/main` every five minutes. The deployment script serializes runs, allows
only fast-forward updates, and builds the candidate while the current container
continues running. It tags images with the full Git commit, switches containers
only after the build succeeds, and waits for the Docker health check. If startup
or the optional external health check fails, it restores the previous image and
Git commit. A failed commit is not attempted again until a different commit is
available or its marker is removed manually.

The host needs Git, Docker Engine, Docker Compose with `--wait` support, and
`flock`. Use a dedicated checkout because automatic rollback resets tracked
files to the previously deployed commit. The checkout may contain the ignored
production `.env` and `runplan-data` directory, but tracked files must not have
local modifications.

The supplied systemd service expects the checkout at `/srv/runplan` and a
`runplan-deploy` user with access to Docker. Membership in the `docker` group is
effectively root access; use a dedicated host or another appropriately secured
Docker access mechanism. After cloning the repository and creating `.env`, adapt
the paths and user in `deploy/runplan-deploy.service` if necessary, then install
the units:

```bash
sudo install -m 0644 deploy/runplan-deploy.service /etc/systemd/system/
sudo install -m 0644 deploy/runplan-deploy.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start runplan-deploy.service
sudo systemctl enable --now runplan-deploy.timer
```

Optionally configure the tracked branch and an externally visible health URL in
`/etc/runplan-deploy.env`:

```dotenv
RUNPLAN_DEPLOY_REMOTE=origin
RUNPLAN_DEPLOY_BRANCH=main
RUNPLAN_DEPLOY_HEALTH_URL=https://runplan.example.com/api/health
```

Without `RUNPLAN_DEPLOY_HEALTH_URL`, the deployment still waits for the image's
internal `/api/health` check. With it, `curl` must also be installed. Inspect the
timer and deployment logs with:

```bash
systemctl list-timers runplan-deploy.timer
systemctl status runplan-deploy.service
journalctl -u runplan-deploy.service
```

To retry the same commit after correcting an external problem, remove its marker
and start the service:

```bash
sudo rm /var/lib/runplan-deploy/failed-commit
sudo systemctl start runplan-deploy.service
```

Rollback deliberately covers the Git checkout and container image only. It does
not restore `runplan-data`. If a release writes a persisted format that the
previous image cannot read, automatic rollback may not recover service. Take a
separate protected backup or filesystem snapshot before releases that migrate
stored data. The data contains Garmin credentials, tokens, and health-related
training history and must not be placed in an image or public backup.

On the first visit, the browser asks which configured Runplan user to use. If
the server has no users yet, the same dialog creates the first one from a
lowercase username and full name. It remembers the user choice in browser-local
storage and persists each user's active program in the server-side user
registry, shared with the CLI. Use the user selector in the header to switch
later.

The web server supports separate Garmin accounts behind the one shared Runplan
Studio password. These profiles are selectors, not separate login identities.
Set `RUNPLAN_USERS_FILE` to a TOML file outside the project:

```toml
[[users]]
id = "sample-runner"
name = "Sample Runner"
credentials_file = "secrets/sample-runner.toml"
token_store = "tokens/sample-runner"
state_dir = "state/sample-runner"

[[users]]
id = "runner-two"
name = "Runner Two"
credentials_file = "secrets/runner-two.toml"
token_store = "tokens/runner-two"
state_dir = "state/runner-two"
```

Relative paths are resolved from the users file. Each credentials file uses the
same `email` and `password` fields described below. Token stores and sync state
are isolated by user. Credential and storage paths stay on the server. A user's
settings dialog can save Garmin email and password; the server never returns a
saved password to the browser, and leaving the password blank preserves it.
Anyone who knows the shared password can view or change every configured user's
settings and sync their Garmin account. If `RUNPLAN_USERS_FILE` is unset,
Runplan uses `~/.config/runplan/users.toml`. When that file does not exist, the
web UI can create it and the first user. A user created in the UI receives these
server-side paths automatically:

```text
~/.config/runplan/users/<username>/credentials.toml
~/.config/runplan/users/<username>/tokens/
~/.config/runplan/users/<username>/state/
```

Only the users configuration is created immediately. Add `email` and `password`
through User settings before that user performs the first Garmin sync. The same
dialog configures `default_pace`, which Runplan uses for that user's web totals,
exports, Garmin titles, and sync calculations whenever a step has no explicit
pace. It defaults to `RUNPLAN_DEFAULT_PACE`, or `6:00 min/km` when the environment
variable is unset. CLI commands continue using the existing Garmin environment
variables and single-user default paths.

## Requirements

Runplan requires Python 3.13 or newer and uses
[`uv`](https://docs.astral.sh/uv/) for Python, virtual environments, and
dependencies.

```bash
uv python install 3.13
uv sync
```

Dependencies are defined in `pyproject.toml`, while `uv.lock` pins the exact
versions. A `requirements.txt` file is therefore not needed.

## Development checks

Run formatting, lint, and the complete test suite with one command:

```bash
uv run python scripts/check.py
```

Pytest is available directly with `uv run pytest`. The complete test suite uses
pytest-style tests and fixtures. The development principles are documented in
[development-standards.md](docs/development-standards.md).

## Select and preview a user's active program

Programs are isolated below the configured program root by user ID. Select the
active program once; the web frontend updates the same setting whenever a user
opens another program:

```bash
uv run runplan user set-plan klaus marathon.yaml
```

Preview the active program without contacting Garmin:

```bash
uv run runplan sync klaus --dry-run
```

A program file contains every program week. Runplan validates the complete
program and selects the requested week or weeks. Dates are calculated from
`program.start_week`, the week number, and the workout's `day`. Start weeks use
ISO format (`YYYY-Www`); weeks begin on Monday, matching Danish calendar weeks.

Preview explicit plan week 1:

```bash
uv run runplan sync klaus --select-weeks 1 --dry-run
```

The default output is a concise human-readable overview of weekdays,
durations, steps, and planned sync changes. Use JSON for debugging or
automation:

```bash
uv run runplan sync klaus --select-weeks 1 --dry-run --output json
```

Select several weeks with `--select-weeks 1,3,5-7`, or pass `current`, `next`,
or `all` to the same option.

## Time, distance, and pace

Steps can end after a duration or distance. The short form represents time;
distance is explicit so `m` never ambiguously means both minutes and meters:

```yaml
steps:
  - warmup: 10m
  - repeat:
      count: 5
      steps:
        - run: {distance: 400m, pace: "4:30-4:45 min/km"}
        - recovery: {time: 90s}
  - cooldown: {distance: 1km}
```

Supported distance units are `m` and `km`. Preview and PDF output show known
time and distance separately; Runplan does not infer one from a pace. See
`docs/examples/distance-workout.yaml` for a complete example.

A regular step may have an optional pace target in minutes per kilometer:

```yaml
- run: {distance: 5km, pace: "5:00 min/km"}
- run: {time: 8m, pace: "4:30-4:45 min/km"}
```

The quotes are required so YAML does not interpret the colon. Garmin receives
the target as a pace zone and can warn when the runner leaves that range.

## Garmin login

Each configured Runplan user has an isolated credentials file, token store,
sync state directory, default pace, and active program. A user created through
the web interface receives the paths documented above. Its credentials file
contains:

```text
~/.config/runplan/users/klaus/credentials.toml
```

The file must contain:

```toml
email = "name@example.com"
password = "your-password"
```

On PowerShell, create the directory and file like this after inserting your
own credentials:

```powershell
New-Item -ItemType Directory -Force "$HOME/.config/runplan"
@'
email = "name@example.com"
password = "your-password"
'@ | Set-Content -Encoding utf8 "$HOME/.config/runplan/credentials.toml"
```

Then sync the current plan week and the following plan week:

```bash
uv run runplan sync klaus
```

The configured credentials and token paths must remain outside the project.
Sync every configured user's active program sequentially with:

```bash
uv run runplan sync --all
```

Users without an active program are reported and skipped. Other users continue
after a failure; the command returns a non-zero status when any attempted sync
fails.

## Sync behavior

Runplan creates and schedules all selected workouts. Sync is additive by
default: managed workouts outside the selection are preserved. With no selector,
sync behaves as `--weeks-ahead 1`: it selects the complete current plan week and
the following plan week. `--weeks-ahead 0` selects only the current plan week.
The program's `start_week` anchors these calculations.

Use `--select-weeks` for an explicit selection such as `3`, `1,3,5-7`,
`current`, `next`, or `all`. It is mutually exclusive with `--weeks-ahead`.

Every real sync first reconciles tracked historical workouts and compares the
selected plan occurrences with Garmin's scheduled workouts. A Garmin activity
association marks a workout completed, including when Garmin exposes that link
only as `metadataDTO.associatedWorkoutId` on the activity summary and including
on the current day. Actual distance and total duration are stored with the
completed workout in the user's YAML. Past
workouts without an activity become missed; current and future workouts remain
active. Completed and missed workouts are retained in local history and are
never recreated. During sync, Runplan automatically removes their tracked Garmin
calendar entries and uploaded workout templates;
it never deletes the recorded activity. The local Garmin workout and schedule
IDs are then cleared while the activity ID and actual result remain. Run legacy file-based reconciliation
without scheduling new workouts with:

The web calendar can also link a `Missed` workout to one or more Garmin runs
manually. Open **Edit** on a missed or completed workout to select unlinked runs
from the workout's exact date, add more runs, or remove an activity associated
automatically during sync. YAML changes and activity selections are saved with
separate buttons so one kind of edit cannot silently overwrite the other.
Runplan sums the selected activities' distance and duration and stores the
earliest start as the completion time. These links exist only in Runplan: Garmin
activities are never edited, and an activity already linked inside the active
plan is not offered again. Workout deletion remains available in the same
**Edit** dialog.

```bash
uv run runplan reconcile ~/.local/share/runplan/programs/morgan-example-5k.yaml
```

Use `--prune` only when future managed workouts outside the selected set should
be removed. Runplan previews the diff and asks for confirmation. For controlled
non-interactive automation, use `--prune --yes`. Completed history, missed
workouts, recorded activities, and unowned Garmin workouts are never pruned.
Terminal Garmin schedules and workout templates are cleaned automatically by
the normal sync flow and do not require `--prune`.

Runplan stores lifecycle state, Garmin IDs, and completed results in a
system-managed `tracking` section on each workout in the user's YAML. Week and
program totals use actual values for completed workouts, zero for missed or
retired workouts, and estimates for remaining workouts. Local tracking is the
sole source of Garmin ownership: once Runplan stores a workout or schedule ID,
that object remains managed even if it is edited remotely. Changed objects are
replaced from the plan, and missing objects are recreated with new IDs. Garmin
descriptions contain only the human-readable plan description. Without a
locally stored ID, Runplan creates a new object instead of adopting one by
title or description.

Legacy JSON state is migrated into YAML on the next successful write. Lost YAML
tracking cannot be reconstructed automatically from Garmin.

Each program has a compact `program.short_name`. Runplan generates Garmin
workout titles as `<short_name> - W<week> - <workout name> - <distance>`, for
example `HCA26 - W3 - 800m intervals - 10.8k`. A `~` marks a distance that
requires an assumed pace for time-based steps. Keep YAML workout names focused
on the workout itself; do not include the plan name, week, or distance.

## Delete a complete program from Garmin

First preview the managed workouts that would be removed:

```bash
uv run runplan sync klaus --delete-all --dry-run
```

Then delete the program's active schedules and workout templates:

```bash
uv run runplan sync klaus --delete-all --yes
```

`--yes` is required for an actual deletion. This command does not delete
recorded running activities, completed or missed local history, or workouts
that cannot be verified as belonging to the program. It does remove verified
Garmin schedules and uploaded templates for completed and missed workouts.

## Render a program in the terminal

The `text` format writes a detailed program directly to stdout. No `--output`
option is needed:

```bash
uv run runplan export ~/.local/share/runplan/programs/morgan-example-5k.yaml --format text
uv run runplan export ~/.local/share/runplan/programs/morgan-example-5k.yaml --format text --select-weeks 3-5
```

Text and file exports use `--select-weeks` with the same explicit expressions as
sync. These select Monday-to-Sunday presentation weeks, even when a presentation
week contains workouts from two source YAML weeks. With no selector, export
includes the complete program.

The YAML `start_week` uses Danish/ISO calendar weeks (`YYYY-Www`). Each program
week starts on Monday, and `day` is numbered 1 through 7 from Monday to Sunday.

## Export a program as PDF

Export the complete program without logging in to Garmin:

```bash
uv run runplan export ~/.local/share/runplan/programs/morgan-example-5k.yaml --format pdf --output ~/.local/share/runplan/programs/morgan-example-5k.pdf
```

The export contains program metadata, selected weeks, workout weekdays,
descriptions, and steps. An existing output file is overwritten only with
`--force`.

## Export as HTML or Markdown

HTML exports are standalone documents with embedded styling. Markdown exports
use deterministic CommonMark and can be committed or processed by other tools:

```bash
uv run runplan export ~/.local/share/runplan/programs/morgan-example-5k.yaml --format html --output ~/.local/share/runplan/programs/morgan-example-5k.html
uv run runplan export ~/.local/share/runplan/programs/morgan-example-5k.yaml --format markdown --output ~/.local/share/runplan/programs/morgan-example-5k.md
```

Both formats support the same week selectors and `--force` behavior as PDF.

Program and weekly totals are estimates. A step's explicit pace is used when
available. Otherwise Runplan uses the fallback pace from
`RUNPLAN_DEFAULT_PACE`, which defaults to `6:00 min/km`. For example:

```bash
RUNPLAN_DEFAULT_PACE="5:45 min/km" uv run runplan export ~/.local/share/runplan/programs/morgan-example-5k.yaml --format text
```

Distance-only steps use pace to estimate duration. Time-only running, warmup,
and cooldown steps use pace to estimate distance. A time-based recovery is a
pause: it contributes duration but no inferred running distance. Pace ranges
use their midpoint.

Runplan accepts complete program files containing `program` and `weeks`. The
format and the maintained generation prompt are documented in
`docs/program-prompt.md`.

Note: the Garmin API is unofficial and may change without notice.
