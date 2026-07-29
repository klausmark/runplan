from contextlib import redirect_stdout
from io import StringIO

import pytest

from runplan import sync_program_week
from tests.fakes import FakeGarmin
from tests.helpers import compiled_week


class SyncTestBase:
    @pytest.fixture(autouse=True)
    def isolated_state_directory(self, tmp_path, monkeypatch) -> None:
        monkeypatch.setenv("GARMIN_STATE_DIR", str(tmp_path))

    def sync(self, client: FakeGarmin, week: int = 1):
        program, compiled = compiled_week(week)
        with redirect_stdout(StringIO()):
            sync_program_week(client, program, compiled)
        return program, compiled

    @staticmethod
    def old_record() -> dict:
        return {
            "week": 9,
            "workout_id": 99,
            "schedule_id": 199,
            "date": "2026-11-01",
            "name": "Old workout",
            "description": "Owned description",
        }
