# Runplan

Runplan validates, previews, exports, and syncs YAML-based running programs.
The bundled beginner plan starts with workouts such as:

- 7 minutes of brisk walking
- 6 × (30 seconds of very easy running + 2 minutes of walking)
- 5 minutes of easy walking

## Run the web frontend

Start the unauthenticated web MVP for access from the same machine:

```bash
uv run runplan serve
```

To make it reachable from other machines on a trusted private network, listen
on all interfaces:

```bash
uv run runplan serve --host 0.0.0.0 --port 8000
```

Open `http://SERVER-IP:8000`. The web frontend lists valid `.yaml` and `.yml`
files from `~/.local/share/runplan/programs` by default and creates that
directory when needed. Set `RUNPLAN_PROGRAM_DIR` or pass `--program-dir` to use
a different server-side data location. It supports plan name,
description, and start-week editing, drag-and-drop workout scheduling, focused
workout YAML editing, and YAML, Markdown, and PDF downloads.

Markdown and PDF downloads are generated from the YAML source and are not
written into the source checkout. CLI exports should likewise use an output
path in the server data or download directory.

The initial server has no authentication. Do not expose it directly to the
public internet. Use it only on a trusted network or behind a reverse proxy that
provides authentication and TLS. Authentication and per-user ownership are
tracked as required follow-up work in `PLAN.md`.

### Run with Docker Compose

Create the local configuration and set `RUNPLAN_HOST_IP` to an address assigned
to the Docker host, such as its Tailscale IPv4 address. Set the desired host
port in `RUNPLAN_HOST_PORT`:

```bash
cp .env.example .env
# Edit .env before continuing. Find the Tailscale address with: tailscale ip -4
```

Then build and start Runplan in the background:

```bash
docker compose up -d --build
```

Open `http://RUNPLAN_HOST_IP:RUNPLAN_HOST_PORT` using the values from `.env`.
Programs, users, Garmin credentials and tokens, and sync state are persisted in
the `runplan-data` Docker volume. Stop the container without deleting that data
with:

```bash
docker compose down
```

Compose requires both binding values and fails instead of listening on an
unintended interface when either is missing. With, for example,
`RUNPLAN_HOST_IP=100.64.0.1` and `RUNPLAN_HOST_PORT=8080`, Runplan is available
at `http://100.64.0.1:8080` only through that host interface. Use an
authenticated TLS reverse proxy for public exposure, since Runplan itself has
no authentication.

On the first visit, the browser asks which configured Runplan user to use. If
the server has no users yet, the same dialog creates the first one from a
lowercase username and full name. It remembers the choice and the most recently
opened program for each user in browser-local storage. Use the user selector in
the header to switch later.

The web server supports separate Garmin accounts without adding a Runplan login.
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
With no Runplan authentication, anyone who can access the web app can view or
change every configured user's settings and sync their Garmin account, so the
trusted network restriction remains essential. If `RUNPLAN_USERS_FILE` is unset,
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

## Preview a program without uploading it

```bash
uv run runplan sync ~/.local/share/runplan/programs/morgan-example-5k.yaml --dry-run
```

A program file contains every program week. Runplan validates the complete
program and selects the requested week or weeks. Dates are calculated from
`program.start_week`, the week number, and the workout's `day`. Start weeks use
ISO format (`YYYY-Www`); weeks begin on Monday, matching Danish calendar weeks.

Preview explicit plan week 1:

```bash
uv run runplan sync ~/.local/share/runplan/programs/morgan-example-5k.yaml --select-weeks 1 --dry-run
```

The default output is a concise human-readable overview of weekdays,
durations, steps, and planned sync changes. Use JSON for debugging or
automation:

```bash
uv run runplan sync ~/.local/share/runplan/programs/morgan-example-5k.yaml --select-weeks 1 --dry-run --output json
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

Create the credentials file outside the project. Its default location is:

```text
~/.config/runplan/credentials.toml
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
uv run runplan sync ~/.local/share/runplan/programs/morgan-example-5k.yaml
```

Set `GARMIN_CREDENTIALS_FILE` to use another location. The file must remain
outside the project directory. The Garmin library stores login tokens
separately in `~/.garminconnect`.

## Sync behavior

Runplan creates and schedules all selected workouts. Sync is additive by
default: managed workouts outside the selection are preserved. With no selector,
sync behaves as `--weeks-ahead 1`: it selects the complete current plan week and
the following plan week. `--weeks-ahead 0` selects only the current plan week.
The program's `start_week` anchors these calculations.

Use `--select-weeks` for an explicit selection such as `3`, `1,3,5-7`,
`current`, `next`, or `all`. It is mutually exclusive with `--weeks-ahead`.

Every real sync first reconciles tracked historical workouts with Garmin.
Workouts linked to an activity become completed; past workouts without an
activity become missed. Completed and missed workouts are retained in local
history and are never recreated or pruned automatically. Run reconciliation
without scheduling new workouts with:

```bash
uv run runplan reconcile ~/.local/share/runplan/programs/morgan-example-5k.yaml
```

Use `--prune` only when future managed workouts outside the selected set should
be removed. Runplan previews the diff and asks for confirmation. For controlled
non-interactive automation, use `--prune --yes`. Completed history, missed
workouts, past schedules, and unowned Garmin workouts are never pruned.

Runplan stores Garmin IDs, names, and descriptions in
`~/.local/state/runplan/<program-id>.json`. Keep this file while the program is
active because it enables safe reuse and cleanup. New and updated Garmin
workouts also contain a compact Runplan ownership marker at the end of the
description. It contains the non-secret Runplan user ID and plan/workout
identity, never Garmin credentials. The CLI defaults to `local-default`; set a
stable installation value with `RUNPLAN_OWNER_ID` or `sync --owner-id` and use
the same value for recovery.

If local state is lost after a reinstall, preview recovery from Garmin with:

```bash
uv run runplan rebuild-state ~/.local/share/runplan/programs/morgan-example-5k.yaml --owner-id local-default
```

Review the JSON report, then repeat with `--yes` to atomically rebuild local
state. The web UI exposes the same review flow under **User settings → Recover
sync state** and uses the selected Runplan user's stable ID. Recovery is
read-only toward Garmin, ignores markers owned by other Runplan users, and
lists unmarked legacy workouts without adopting them.

Each program has a compact `program.short_name`. Runplan generates Garmin
workout titles as `<short_name> - W<week> - <workout name> - <distance>`, for
example `HCA26 - W3 - 800m intervals - 10.8k`. A `~` marks a distance that
requires an assumed pace for time-based steps. Keep YAML workout names focused
on the workout itself; do not include the plan name, week, or distance.

## Delete a complete program from Garmin

First preview the managed workouts that would be removed:

```bash
uv run runplan sync ~/.local/share/runplan/programs/morgan-example-5k.yaml --delete-all --dry-run
```

Then delete the program's active schedules and workout templates:

```bash
uv run runplan sync ~/.local/share/runplan/programs/morgan-example-5k.yaml --delete-all --yes
```

`--yes` is required for an actual deletion. This command does not delete
recorded running activities, completed or missed history, or workouts that
cannot be verified as belonging to the program.

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
