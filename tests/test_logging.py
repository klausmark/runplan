from __future__ import annotations

import logging
import os
import tempfile
import unittest
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import yaml

from runplan.cli import parse_arguments
from runplan.integrations.garmin.logging_client import LoggingGarminClient
from runplan.logging_config import configure_server_logging
from runplan.state.json_repository import new_state
from runplan.web import ProgramStore
from tests.helpers import program_data


class MemoryRepository:
    def load(self, program_id: str) -> dict:
        return new_state(program_id)

    def save(self, program_id: str, state: dict) -> None:
        pass

    def delete(self, program_id: str) -> None:
        pass


class FakeGarmin:
    def get_workouts(self, start: int, limit: int) -> list[dict]:
        return []

    def get_scheduled_workouts(self, year: int, month: int) -> dict:
        return {"calendarItems": []}

    def get_activity(self, activity_id: str) -> dict:
        return {"activityId": activity_id}

    def upload_running_workout(self, workout) -> dict:
        return {"workoutId": 42}

    def schedule_workout(self, workout_id: int, scheduled_date: str) -> dict:
        return {"workoutScheduleId": 84}

    def unschedule_workout(self, schedule_id: int) -> None:
        pass

    def delete_workout(self, workout_id: int) -> None:
        pass


class ServerLoggingTests(unittest.TestCase):
    def tearDown(self) -> None:
        logger = logging.getLogger("runplan")
        logger.handlers.clear()
        logger.addHandler(logging.NullHandler())
        logger.setLevel(logging.NOTSET)

    def test_server_logging_filters_levels_and_writes_to_configured_stdout(self) -> None:
        output = StringIO()
        configure_server_logging("INFO", stream=output)
        logger = logging.getLogger("runplan.test")

        logger.debug("hidden")
        logger.info("visible event=save")

        rendered = output.getvalue()
        self.assertIn("INFO runplan.test visible event=save", rendered)
        self.assertNotIn("hidden", rendered)

    def test_log_formatter_redacts_secrets_in_messages_and_tracebacks(self) -> None:
        output = StringIO()
        configure_server_logging("DEBUG", stream=output)
        logger = logging.getLogger("runplan.test")

        try:
            raise RuntimeError(
                "email runner@example.com password=hunter2 token=abc123 "
                "path=/srv/users/klaus/credentials.toml"
            )
        except RuntimeError:
            logger.exception("Authentication failed for runner@example.com")

        rendered = output.getvalue()
        for secret in ("runner@example.com", "hunter2", "abc123", "credentials.toml"):
            self.assertNotIn(secret, rendered)
        self.assertIn("<redacted-email>", rendered)
        self.assertIn("<redacted>", rendered)

    def test_garmin_mutations_and_exceptions_are_logged_with_ids(self) -> None:
        output = StringIO()
        configure_server_logging("INFO", stream=output)
        client = LoggingGarminClient(FakeGarmin(), user_id="klaus")
        workout = type("Workout", (), {"workoutName": "Easy run"})()

        created = client.upload_running_workout(workout)
        client.schedule_workout(created["workoutId"], "2026-07-30")
        client.unschedule_workout(84)
        client.delete_workout(42)

        rendered = output.getvalue()
        self.assertIn(
            "Garmin workout created user=klaus workout_name='Easy run' workout_id=42", rendered
        )
        self.assertIn("schedule_id=84 date=2026-07-30", rendered)
        self.assertIn("Garmin unschedule_workout succeeded user=klaus schedule_id=84", rendered)
        self.assertIn("Garmin delete_workout succeeded user=klaus workout_id=42", rendered)

        class BrokenGarmin(FakeGarmin):
            def delete_workout(self, workout_id: int) -> None:
                raise RuntimeError("remote exploded")

        with self.assertRaisesRegex(RuntimeError, "remote exploded"):
            LoggingGarminClient(BrokenGarmin(), user_id="klaus").delete_workout(99)
        self.assertIn("Garmin delete_workout failed user=klaus workout_id=99", output.getvalue())
        self.assertIn("RuntimeError: remote exploded", output.getvalue())

    def test_yaml_upload_and_user_edit_are_logged_without_yaml_content(self) -> None:
        output = StringIO()
        configure_server_logging("INFO", stream=output)
        with tempfile.TemporaryDirectory() as directory:
            store = ProgramStore(Path(directory), repository=MemoryRepository())
            content = yaml.safe_dump(program_data(), sort_keys=False)
            uploaded = store.upload("plan.yaml", content)
            store.edit(
                "plan.yaml",
                {
                    "revision": uploaded["revision"],
                    "program": {"name": "Secret training name"},
                },
            )

        rendered = output.getvalue()
        self.assertIn("YAML program uploaded", rendered)
        self.assertIn("YAML program saved", rendered)
        self.assertIn("changes=program.name", rendered)
        self.assertNotIn("weeks:", rendered)

    def test_serve_log_level_uses_environment_and_cli_override(self) -> None:
        with patch.dict(os.environ, {"RUNPLAN_LOG_LEVEL": "warning"}):
            from_environment = parse_arguments(["serve"])
            explicit = parse_arguments(["serve", "--log-level", "debug"])

        self.assertEqual("WARNING", from_environment.log_level)
        self.assertEqual("DEBUG", explicit.log_level)

        with patch.dict(os.environ, {"RUNPLAN_LOG_LEVEL": "verbose"}):
            with self.assertRaises(SystemExit):
                parse_arguments(["serve"])


if __name__ == "__main__":
    unittest.main()
