"""Compatibility checks for facades retained during structural refactoring."""

import unittest

import runplan
import runplan.application as application
import runplan.application.sync as sync
import runplan.cli as cli
import runplan.parsing.yaml_loader as yaml_loader
import runplan.users as users
import runplan.web as web


class PublicFacadeTests(unittest.TestCase):
    def test_root_exports_remain_available(self) -> None:
        expected = {
            "Program",
            "ProgramExport",
            "WeekSelection",
            "build_program_export",
            "delete_all_managed",
            "export_pdf",
            "load_program",
            "load_program_model",
            "reconcile_program",
            "run_sync",
            "sync_program_week",
        }

        self.assertLessEqual(expected, set(runplan.__all__))
        for name in expected:
            self.assertTrue(
                callable(getattr(runplan, name)) or isinstance(getattr(runplan, name), type)
            )

    def test_application_sync_facade_retains_use_cases(self) -> None:
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

        self.assertLessEqual(expected, set(sync.__all__))
        self.assertIs(application.plan_program_weeks, sync.plan_program_weeks)

    def test_adapter_facades_retain_documented_entrypoints(self) -> None:
        self.assertLessEqual(
            {"build_parser", "main", "prepare_sync_selections", "run_sync"}, set(cli.__all__)
        )
        self.assertLessEqual(
            {"load_program", "load_program_model", "normalize_workout"}, set(yaml_loader.__all__)
        )
        self.assertLessEqual(
            {"RunplanUser", "UserRegistry", "WebError", "load_user_registry"}, set(users.__all__)
        )
        self.assertLessEqual(
            {"ProgramStore", "WebSyncService", "make_handler", "serve"}, set(web.__all__)
        )


if __name__ == "__main__":
    unittest.main()
