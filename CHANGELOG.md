# Changelog

Notable changes for users and integrators are documented in this file.

The project follows Semantic Versioning. During initial development, intentional breaking
changes may be released in a new minor version.

## Unreleased

- Added four Nike Run Club training plan templates (5K, 10K, half-marathon,
  marathon) bundled as static YAML under `src/runplan/templates/programs/`.
  The Studio empty state now offers a **Browse templates** button that lists
  the catalog and lets the user copy any template into their own programs
  with a chosen start week. New HTTP endpoints `GET /api/templates`,
  `GET /api/templates/<id>`, and `POST /api/templates/<id>/copy` back the
  catalog. The Python API exposes `runplan.templates.list_templates`,
  `get_template`, `copy_template`, `template_yaml`, `default_start_week`,
  and the `TEMPLATE_CATALOG` constant. The templates are unofficial
  adaptations; pace targets stay in step notes so Garmin Connect receives
  the runner's own pace when applied.
- Replaced the topbar **Upload program** button with a split **Add program**
  button. The primary action uploads a YAML file; the dropdown arrow opens
  a small menu with **Upload YAML file** and **Browse templates** so the
  template catalog is reachable from any state, not only when the program
  list is empty. Upload and template copy now run through one
  **Add a program** dialog with two tabs, and both flows automatically set
  the new program as the active one.
- Made the workout card the primary interaction surface. Click or tap opens
  the edit dialog; press and drag moves the workout. The explicit Edit and
  Move buttons were removed, and the move dialog was retired. The card is
  keyboard-activatable with Enter or Space and uses one pointer-event code
  path for both mouse and touch.
- Showed a structured, read-only overview of the workout's steps when the
  Edit dialog opens. The YAML editor remains the deliberate escape hatch and
  is unchanged. The overview is the first step toward editing workouts
  directly in the UI rather than only in YAML.
- Added an optional watch-facing `note` field to every step in YAML. The note
  replaces the default Garmin step label (`Very easy run`, `Warm up`, `Walk`,
  `Cool down`) and is also rendered in previews, PDF, HTML, and Markdown
  exports. Notes are plain text, must be non-empty, and are capped at 140
  characters so the watch face can render them.
- Added a deterministic first 10K program generator. The `runplan
  generation` module accepts a typed request and returns a validated Runplan
  program that round-trips through the existing parser. The `runplan
  generate first-10k` command writes the produced YAML to stdout or to a
  file. The coaching rules are encoded in code and cite the peer-reviewed
  evidence collected in `docs/generation-first-10k-evidence.md`.
- Added an optional systemd-driven Docker host deployment that polls Git,
  retains commit-tagged images, waits for health, and restores the previous
  image and checkout when deployment fails.
- Improved Docker rebuild caching by installing locked production dependencies
  before copying frequently changed application source files.
- Moved Garmin activity management above the workout YAML editor, collapsed
  YAML by default when editing an existing workout, and included validation and
  saving in the collapsible editor.
- Prevented completed workouts from being dragged, moved, swapped, or moved through
  undo in the web calendar; direct YAML editing remains available as an escape hatch.
- Added manual linking of one or more same-day Garmin runs to missed workouts.
  Linked activities can also be added to or removed from completed workouts;
  Runplan sums their distance and duration without changing Garmin data.
- Renamed the workout card action to **Edit** and moved Garmin activity linking
  into that dialog alongside YAML editing and workout deletion.
- Added YAML-based workout creation from empty calendar days, including a valid
  starter template and an in-dialog syntax reference.
- Added confirmed workout deletion while deferring cleanup of synchronized
  Garmin objects to the next reviewed sync.
- Added one shared password gate for Runplan Studio with persistent browser
  authorization, HTTPS-aware cookies, challenge-response login, and basic
  in-memory rate limiting.
- Added `runplan hash-password` and Docker environment configuration for the
  recommended salted password verifier.
