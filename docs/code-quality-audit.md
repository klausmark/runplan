# Runplan structural responsibility audit

This audit maps structural size signals to Runplan's single-responsibility standards. The
baseline was measured at commit `511f534` with:

```bash
uv run python scripts/audit_structure.py
```

The script reports source spans, not logical statements. A signal requires review; it is not
proof of poor design and never fails the quality check. Re-run it after structural changes.
Use `--all` to print the complete production inventory.

## Baseline summary

| Area | Total | Signals |
| --- | ---: | ---: |
| Production modules | 41 | 6 at or above 300 lines |
| Production functions and methods | 221 | 32 at or above 40 lines |
| Production classes | 34 | 6 at or above 100 lines or 8 methods |

The strongest complexity signals from a supplementary McCabe review align with the size
signals: `make_handler` (37), `run_sync` (30), `normalize_workout` (28), and
`synchronize_program_week` (26). Complexity is supporting evidence, not a configured gate.

## Module assessment

| Lines | Module | Responsibility assessment | Priority |
| ---: | --- | --- | --- |
| 1005 | `web.py` | Mixes document storage, editing, exports, sync orchestration, and HTTP routing | Split first |
| 899 | `application/sync.py` | Mixes reconciliation, planning, execution, cleanup, deletion, and CLI output | Split first |
| 459 | `exporters/pdf.py` | One PDF concern, but nearly all layout responsibilities live in one function | Extract collaborators |
| 452 | `cli.py` | One adapter layer, but parser construction and several command families change independently | Split by command area |
| 372 | `parsing/yaml_loader.py` | One parsing pipeline, but validation, normalization, selection, and model construction are fused | Split by parser phase |
| 308 | `users.py` | Mixes user registry, active-plan state, credentials, TOML persistence, and an HTTP error | Split persistence concerns |

Modules below 300 lines currently have no module-size signal. The method-level findings below
still apply to them.

## Function and method assessment

### Responsibility should be split

| Lines | Function or method | Main responsibilities currently combined |
| ---: | --- | --- |
| 354 | `export_pdf` | Document setup, fonts, styles, headers, footers, week layout, and workout layout |
| 241 | `synchronize_program_week` | Remote discovery, matching, upload, scheduling, persistence, and cleanup safety |
| 228 | `make_handler` | Handler construction, error policy, routing, body parsing, and response serialization |
| 197 | `cli_sync.run_sync` | Preview, confirmation, prune, delete, login, sync, and terminal rendering |
| 118 | `load_program` | Program validation, week validation, selection, date calculation, and normalization |
| 107 | `normalize_workout` | Field validation, step normalization, metadata handling, and workout construction |
| 107 | `ProgramStore.get` | Document loading, view-model construction, totals, lifecycle state, and sync status |
| 93 | `plan_program_weeks` | Input validation, remote/state comparison, cleanup planning, and action construction |
| 85 | `synchronize_program_weeks` | Batch validation, per-week execution, and cross-week cleanup coordination |
| 81 | `cleanup_terminal_workouts` | Remote verification, unscheduling, deletion, and state checkpointing |
| 72 | `WebSyncService.execute` | Confirmation validation, dependency creation, execution, logging, and response mapping |
| 67 | `RunplanHandler.do_POST` | Dispatches unrelated user, program, settings, edit, sync, and export operations |
| 64 | `RunplanHandler._get` | Dispatches assets and unrelated read endpoints |
| 61 | `ProgramStore.edit` | Concurrency validation, metadata editing, moves, workout replacement, persistence, and logging |
| 50 | `ProgramStore._lifecycle` | State lookup, content comparison, date comparison, and display-state derivation |

### Large or complex, but predominantly cohesive

| Lines | Function or method | Assessment |
| ---: | --- | --- |
| 109 | `scheduled_items_for_dates` | One calendar-query operation; extract pagination and response normalization for readability |
| 81 | `build_program_export` | One export view-model transformation; extract workout and totals mapping |
| 78 | `reconcile_selected_program` | One selected-program reconciliation workflow |
| 75 | `reconcile_program` | One whole-program reconciliation workflow |
| 75 | `format_program_html` | One renderer; smaller section renderers would improve navigation |
| 64 | `build_parser` | One parser-construction task; split command builders as the CLI grows |
| 63 | `prepare_sync_selections` | One selection preparation pipeline; extract enrichment/compilation steps |
| 61 | `delete_managed_workouts` | One guarded deletion workflow |
| 60 | `YamlStateRepository.save` | One persistence operation; extract document mutation and atomic write |
| 59 | `load_user_registry` | One load operation; extract entry validation/construction |
| 54 | `format_program_markdown` | One renderer; section helpers are optional |
| 51 | `build_preview` | One preview view-model transformation |
| 51 | `ProgramStore.upload` | One upload workflow; validation and naming can become helpers |
| 49 | `parse_duration` | One value parser with intentionally supported legacy forms |
| 47 | `program_model` | One normalized-model construction step |
| 47 | `format_program_text` | One text renderer |
| 45 | `estimate_steps` | One recursive estimation operation |

## Class assessment

| Lines | Methods | Class | Responsibility assessment |
| ---: | ---: | --- | --- |
| 452 | 15 | `ProgramStore` | Split storage, editing, lifecycle projection, and export behavior |
| 218 | 9 | nested `RunplanHandler` | HTTP adapter is cohesive, but endpoint families need separate handlers/controllers |
| 175 | 12 | `UserRegistry` | Split registry operations, credentials, and TOML persistence |
| 171 | 8 | `WebSyncService` | Retain sync facade; inject dependency factories and extract execution/response mapping |
| 114 | 9 | `LoggingGarminClient` | Cohesive logging decorator; no split currently justified |
| 114 | 5 | `YamlStateRepository` | Cohesive repository; simplify `load` and `save` internally |

`WeekSelection` is 84 lines with seven methods and remains cohesive around one immutable
selection concept. It has no current class signal.

## Recommended refactoring sequence

1. Separate HTTP routing from program document operations in `web.py`, preserving endpoints.
2. Separate sync planning from mutation execution and cleanup, preserving application APIs
   through compatibility wrappers.
3. Replace `cli_sync.run_sync` branching with focused command workflows.
4. Decompose PDF layout into style, page decoration, week, and workout renderers.
5. Split user registry, credential storage, and configuration persistence.
6. Split CLI command builders and YAML parser phases when those areas next change.

Each refactoring should be behavior-preserving, use the existing characterization tests, and
land independently from feature work.

## Test overview

| Lines | Test module | Future migration boundary |
| ---: | --- | --- |
| 1226 | `test_sync_characterization.py` | Split by planning, execution, cleanup, state, and Garmin boundary after production seams exist |
| 853 | `test_web.py` | Split by assets, program documents, user registry, sync service, and HTTP adapter |
| 386 | `test_program_characterization.py` | Keep parser behavior together initially; migrate scenario groups module by module |
| 253 | `test_cli_selection.py` | Natural unit for one complete pytest migration |

The largest individual test is 69 lines. Large tests generally describe multi-step safety
scenarios, so they should be shortened only when fixtures or domain helpers improve the story.
Do not split assertions that jointly describe one outcome.
