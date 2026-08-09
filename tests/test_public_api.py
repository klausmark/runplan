"""Compatibility checks for facades retained during structural refactoring."""

import runplan
import runplan.application as application
import runplan.application.sync as sync
import runplan.cli as cli
import runplan.parsing.yaml_loader as yaml_loader
import runplan.users as users
import runplan.web as web


def test_root_exports_remain_available() -> None:
    expected = {
        "Program",
        "ProgramExport",
        "TEMPLATE_CATALOG",
        "TemplateCopyError",
        "TemplateMetadata",
        "WeekSelection",
        "build_program_export",
        "copy_template",
        "default_start_week",
        "delete_all_managed",
        "export_pdf",
        "get_template",
        "list_templates",
        "load_program",
        "load_program_model",
        "reconcile_program",
        "run_sync",
        "sync_program_week",
        "template_yaml",
    }

    assert expected <= set(runplan.__all__)
    assert all(
        callable(getattr(runplan, name))
        or isinstance(getattr(runplan, name), type)
        or isinstance(getattr(runplan, name), tuple)
        for name in expected
    )


def test_application_sync_facade_retains_use_cases() -> None:
    expected = {
        "cleanup_terminal_workouts",
        "delete_managed_workouts",
        "plan_program_weeks",
        "reconcile_program",
        "reconcile_selected_program",
        "synchronize_program_week",
        "synchronize_program_weeks",
        "workout_content_hash",
    }

    assert expected <= set(sync.__all__)
    assert application.plan_program_weeks is sync.plan_program_weeks


def test_adapter_facades_retain_documented_entrypoints() -> None:
    assert {"build_parser", "main", "prepare_sync_selections", "run_sync"} <= set(cli.__all__)
    assert {"load_program", "load_program_model", "normalize_workout"} <= set(yaml_loader.__all__)
    assert {"RunplanUser", "UserRegistry", "WebError", "load_user_registry"} <= set(users.__all__)
    assert {"ProgramStore", "WebSyncService", "make_handler", "serve"} <= set(web.__all__)
