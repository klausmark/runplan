# Runplan terminology

These terms are canonical in code, YAML, CLI output, documentation, and
maintained content.

| Concept | Canonical term |
|---|---|
| A complete training schedule | program |
| A numbered seven-day period | week |
| One training session | workout |
| One instruction inside a workout | step |
| Elapsed time | duration |
| Length covered | distance |
| Minutes per kilometer | pace |
| Opening preparation | warmup |
| Easy movement between work intervals | recovery |
| Planned walking as part of a workout | walk |
| Pause where standing is acceptable | rest |
| Closing easy movement | cooldown |
| A recursive group performed multiple times | repeat |
| An easy aerobic workout | easy run |
| Alternating running and planned walking intervals | run/walk |
| An extra-easy recovery jog | recovery run |
| A sustained controlled effort | tempo run |
| Repeated faster work with recoveries | interval workout |
| The longest aerobic workout of a week | long run |
| A version-neutral program that users copy with their own start week | template |
| The Studio listing of bundled templates | template catalog |
| The act of duplicating a template into a per-user program | copy template |
| The coaching purpose of a workout, shown in the UI but not stored in program YAML | category |
| A schedule-independent workout shape that instantiates into an explicit workout | recipe |

Use "sync" for reconciliation with Garmin, "preview" for a read-only rendering,
"export" for writing a presentation file, and "prune" only for explicitly
removing managed workouts outside the selected set.

Use `recovery` for flexible active recovery between work intervals. It is a
coaching term and may carry a pace, a note, or no extra guidance. Use `walk`
when planned walking is part of the workout and `rest` when standing is
acceptable. The runner may combine `walk`, `run`, and `recovery` to express
the same workout in different ways.

Categories and recipes are authoring concepts. They are not fields in program
YAML. Categories are shown to the runner as a label on workout cards and in
export headings, but they live in local application state rather than inside
the program file.

The **rolling everyday plan** is an always-on mode that proposes the next 14
days based on the runner's profile, a broad goal, completed workouts, and
recent load. The proposal is previewable as one extra working week that can be
accepted (written into the program YAML) or regenerated with different flags.
The CLI exposes `everyday propose` and `everyday accept`; the Studio surfaces
the same workflow in Step 11. Accepting the plan appends new workout blocks to
the existing program rather than writing a separate file, so the runner's
existing tracking and Garmin state remain intact.
