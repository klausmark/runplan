# Prompt for generating a running program

This prompt describes the supported program format. When the format changes,
update the prompt together with the parser, examples, and tests.

Copy the text below, fill in the bracketed information, and send it to the
model that will generate the program.

---

You are an experienced running coach. Create a complete running program and
return it as one valid YAML file following the specification below.

## Runner and goal

- Runner: [describe the runner's current level]
- Goal: [for example, run 5 km continuously]
- Duration: [for example, 12 weeks]
- Training days per week: [for example, 3]
- First training week begins: [YYYY-MM-DD]
- Known paces: [race PR paces; current paces for, for example, 200 m, 400 m,
  1 km, and 2–3 km tempo blocks; typical easy and very easy pace; use a colon
  as in 5:12]
- Constraints: [injuries, age, preferred training days, or anything else]

Return YAML only. Do not write an explanation before or after the YAML.

## YAML structure

```yaml
program:
  id: 5k-beginner-12-weeks
  name: "Beginner 5K"
  short_name: B5K
  description: >-
    A progressive program for new runners.
  start_week: 2026-W32

weeks:
  - week: 1
    focus: "Adapting to easy run/walk intervals"
    workouts:
      - id: workout-1
        day: 1
        name: "Easy run/walk intervals"
        description: >-
          Run very easily and walk briskly during recoveries.
        steps:
          - warmup: 7m
          - repeat:
              count: 6
              steps:
                - run: 30s
                - recovery: 2m
          - cooldown: 5m
```

## Program fields

`program.id` is required and must be a stable machine-readable identifier.
Use lowercase ASCII letters, numbers, and hyphens only. Do not change the ID
merely because the program's name or content changes.

`program.name` is the human-readable program name.

`program.short_name` is required and provides a compact, human-readable plan
identifier for Garmin workout titles. Use 2-10 ASCII letters, numbers, and
hyphens with no spaces, preferably a memorable uppercase code such as `B5K`,
`HCA26`, or `CPH-HM`. It is presentation metadata, not a replacement for the
stable `program.id`. Runplan combines it with the plan week, workout name, and
estimated distance when syncing, for example
`B5K - W1 - Easy run/walk intervals - ~2.5k`.

`program.description` is optional text describing the runner, goal, and
progression.

`program.start_week` is required and uses ISO format `YYYY-Www`. Week 1 starts
on that calendar week's Monday, following Danish/ISO-8601 week numbering. A
workout date is calculated as:

```text
Monday of start week + ((week - 1) * 7) + (day - 1) days
```

## Weeks

`weeks` must contain every program week. Week numbers must start at 1, be in
ascending order, and be contiguous.

Each week has:

- `week`: required positive integer.
- `focus`: optional short description of the week's training focus.
- `workouts`: at least one workout, sorted by `day`.

## Workouts

Each workout has:

- `id`: required and unique within the week. Use stable IDs such as
  `workout-1`, `workout-2`, and `workout-3`.
- `day`: integer from 1 through 7, where 1 is the first day of the week,
  normally Monday, and 7 is Sunday. Two workouts cannot use the same day.
- `name`: required concise, human-readable description of the workout itself,
  such as `Easy run`, `800m intervals`, or `Marathon pace long run`. Do not add
  the program name, week number, or estimated distance; Runplan adds those to
  the Garmin title. Names may repeat in different weeks.
- `description`: optional concise instructions about intensity and execution.
- `steps`: required list containing at least one training step.

A workout's stable identity combines the program ID, week, and workout ID.

## Training steps

A regular step must have exactly one action and one end condition:

```yaml
steps:
  - warmup: 5m
  - run: 3m
  - recovery: 90s
  - cooldown: 5m
```

`walk` and `rest` follow the same end-condition rules as `run`:

```yaml
steps:
  - warmup: 5m
  - repeat:
      count: 6
      steps:
        - run: 2m
        - walk: 1m
  - cooldown: 5m
```

Supported actions are:

- `warmup`
- `run`
- `walk`
- `recovery`
- `rest`
- `cooldown`
- `repeat`

Use `walk` when planned walking is part of the workout, such as a run/walk
session, planned breaks on a long run, or a walking-only easy day. Use `rest`
when a pause where standing is acceptable is intended, such as recovery
between short fast intervals or after a hill sprint.

Use `recovery` for flexible active recovery between work intervals. It may
carry a pace, a note, or no extra guidance. When the exact movement matters,
prefer `walk` for walking and `rest` for standing pauses.

A repeat step has this structure:

```yaml
- repeat:
    count: 5
    steps:
      - run: 2m
      - recovery: 1m
```

`count` must be a positive integer, and `steps` must be a non-empty list.
Avoid unnecessarily deep nesting. Repeat children may use any supported
action, including `walk` and `rest`, so run/walk sessions can be expressed
cleanly.

## Time-based steps

The short form always represents time, so `run: 2m` means two minutes. Time
may also be explicit as `run: {time: 2m}`. Valid duration formats include:

- `30s`
- `90s`
- `2m`
- `1m30s`
- `1h`
- `00:30`
- `02:30`
- `01:02:30`

Every duration must be greater than zero.

## Distance-based steps

Put a distance in an explicit `distance` field because `m` would otherwise be
ambiguous between minutes and meters. A unit is required:

```yaml
- warmup: {distance: 1km}
- run: {distance: 400m}
- recovery: {distance: 200m}
- cooldown: {distance: 1.5km}
```

The units `m` and `km` are supported, including decimal values such as
`1.5km`. Time and distance may be freely combined, including inside repeats.
Every value must be greater than zero.

## Pace targets

A regular step may have an optional `pace` in minutes per kilometer. Put the
end condition (`time` or `distance`) and pace target in the same object:

```yaml
- run: {distance: 5km, pace: "5:00 min/km"}
- run: {time: 8m, pace: "4:30-4:45 min/km"}
```

Both a single pace and a range are supported. Always use `M:SS min/km` or
`M:SS-M:SS min/km`, quote the complete value, and put the faster boundary
first. Add a concrete target only when the runner's relevant training or race
pace is known; do not invent a pace from a general level description. Convert
the supplied paces into realistic ranges on the relevant `run` steps. Use
descriptions to emphasize that current condition, terrain, and weather take
priority.

## Workout forms and ordering

The following workout forms describe coaching intent. They are not required
YAML fields and must not be added as schema fields:

- Easy run: easy aerobic base training. A recovery run is an extra-easy easy
  run. Describe the effort, but do not add a structured `pace` field.
- Long run: the week's endurance run, mainly at easy intensity. Do not add a
  structured `pace` field, including on a faster finish.
- Interval workout: short or long work intervals separated by easy recovery.
  Only work intervals receive structured `pace`. Every recovery between
  intervals must be time-based, such as `recovery: {time: 2m}`; never use
  distance as the recovery end condition.
- Tempo run: controlled continuous blocks or longer repetitions. Only the
  tempo work receives structured `pace`.

Warmup and cooldown steps must never have a structured `pace`, regardless of
workout form. Recovery steps must never have `pace` either.

A long run, interval workout, or tempo run is a key workout. Never place two
key workouts consecutively, including across week boundaries. Always place at
least one easy or recovery run between them. Race day must not have a
structured `pace` field.

## Training requirements

- Create a cautious and realistic progression.
- Adapt the training to the described runner.
- Use run/walk intervals initially for new runners.
- Allow suitable recovery between training days.
- Include lighter weeks when appropriate.
- Normally begin with `warmup` and finish with `cooldown`.
- Describe easy running as slow enough for a short conversation.
- Use only features and step actions marked as supported.
- Prepare the runner for the goal in the final week without a sudden large
  increase in load.

## Technical requirements

- Return one complete valid YAML file without a Markdown code fence.
- Use the English field names exactly as specified.
- Write UTF-8 text and indent with spaces.
- Do not use YAML anchors, aliases, tags, or advanced YAML features.
- Do not add fields absent from this specification.
- Do not use `null` for required fields.
- Check IDs, week numbers, days, names, durations, distances, pace targets,
  and repeat groups.
- Check that the progression is realistic.
