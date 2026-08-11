from __future__ import annotations

from datetime import date
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml

from runplan.application.results import SyncResult
from runplan.web import (
    ProgramStore,
    RunplanUser,
    UserRegistry,
    WebError,
    WebSyncService,
)
from tests.helpers import program_data
from tests.web_helpers import MemoryStateRepository


class TestWebSyncService:
    @pytest.fixture(autouse=True)
    def sync_service(self, tmp_path: Path) -> None:
        self.root = tmp_path
        self.path = self.root / "plan.yaml"
        self.path.write_text(
            yaml.safe_dump(program_data(), allow_unicode=True, sort_keys=False), encoding="utf-8"
        )
        self.repository = MemoryStateRepository()
        self.store = ProgramStore(self.root, repository=self.repository)
        self.client_factory = Mock(return_value=object())
        self.service = WebSyncService(
            self.store,
            repository=self.repository,
            client_factory=self.client_factory,
            today=lambda: date(2026, 12, 30),
        )

    def test_preview_uses_default_weeks_without_contacting_garmin(self) -> None:
        preview = self.service.preview("plan.yaml")
        assert [1, 2] == preview["plan"]["weeks"]
        assert ["missed", "create", "schedule", "create", "schedule"] == [
            action["kind"] for action in preview["plan"]["actions"]
        ]
        assert 64 == len(preview["confirmationToken"])
        self.client_factory.assert_not_called()

    def test_preview_default_limits_to_current_plus_next_week(self) -> None:
        from datetime import timedelta

        from tests.helpers import program_data

        data = program_data()
        data["weeks"].append(
            {
                "week": 3,
                "focus": "Extra week",
                "workouts": [
                    {
                        "id": "extra",
                        "day": 1,
                        "name": "Week 3 - Extra",
                        "description": "Extra workout",
                        "steps": [{"run": {"distance": "3km"}}],
                    }
                ],
            }
        )
        self.path.write_text(
            yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8"
        )

        preview = self.service.preview("plan.yaml")

        assert [1, 2] == preview["plan"]["weeks"]
        third_week_start = date(2026, 12, 28) + timedelta(weeks=2)
        third_week_end = third_week_start + timedelta(days=6)
        action_dates = {
            action["date"] for action in preview["plan"]["actions"] if action.get("date")
        }
        assert action_dates, "preview should include actions with dates"
        assert not any(
            third_week_start.isoformat() <= d <= third_week_end.isoformat() for d in action_dates
        ), "no actions should target week 3"
        self.client_factory.assert_not_called()

    def test_confirmed_sync_returns_structured_results(self) -> None:
        preview = self.service.preview("plan.yaml")
        result = SyncResult("characterization-plan", 1)
        result.add("schedule", "Mixed", workout_id=42, date="2026-12-28")
        with patch("runplan.web.synchronize_program_weeks", return_value=[result]):
            response = self.service.execute(
                "plan.yaml", {"confirmationToken": preview["confirmationToken"]}
            )
        self.client_factory.assert_called_once_with()
        assert [1, 2] == response["weeks"]
        assert "schedule" == response["results"][0]["actions"][0]["kind"]

    def test_changed_plan_rejects_stale_confirmation(self) -> None:
        preview = self.service.preview("plan.yaml")
        loaded = self.store.get("plan.yaml")
        self.store.edit(
            "plan.yaml", {"revision": loaded["revision"], "program": {"name": "Changed plan"}}
        )
        with pytest.raises(WebError) as context:
            self.service.execute("plan.yaml", {"confirmationToken": preview["confirmationToken"]})
        assert context.value.status == 409
        self.client_factory.assert_not_called()

    def test_preview_includes_a_workout_marked_for_deletion(self) -> None:
        state = self.repository.load("characterization-plan")
        state["workouts"]["week-01/removed"] = {
            "name": "Removed workout",
            "status": "scheduled",
            "workout_id": 42,
            "schedule_id": 43,
            "date": "2027-01-01",
            "pending_deletion": True,
        }

        preview = self.service.preview("plan.yaml")

        cleanup = [
            action for action in preview["plan"]["actions"] if action.get("workout_id") == 42
        ]
        assert ["unschedule", "delete"] == [action["kind"] for action in cleanup]

    def test_garmin_error_is_actionable(self) -> None:
        preview = self.service.preview("plan.yaml")
        self.client_factory.side_effect = RuntimeError("login unavailable")
        with pytest.raises(WebError) as context:
            self.service.execute("plan.yaml", {"confirmationToken": preview["confirmationToken"]})
        assert context.value.status == 502
        assert "login unavailable" in str(context.value)

    def test_user_profiles_have_isolated_state_and_confirmation_tokens(self) -> None:
        alice = RunplanUser(
            "alice",
            "Alice",
            self.root / "alice.toml",
            self.root / "alice-tokens",
            self.root / "alice-state",
        )
        bob = RunplanUser(
            "bob", "Bob", self.root / "bob.toml", self.root / "bob-tokens", self.root / "bob-state"
        )
        service = WebSyncService(
            self.store,
            users=UserRegistry([alice, bob]),
            client_factory=self.client_factory,
            today=lambda: date(2026, 12, 30),
        )
        alice_state = service.repository_for("alice").load("characterization-plan")
        alice_state["workouts"]["week-01/mixed"] = {
            "status": "scheduled",
            "date": "2026-12-28",
            "schedule_id": 42,
        }
        service.repository_for("alice").save("characterization-plan", alice_state)
        alice_preview = service.preview("plan.yaml", "alice")
        bob_preview = service.preview("plan.yaml", "bob")
        assert alice_preview["confirmationToken"] != bob_preview["confirmationToken"]
        assert "alice" == alice_preview["userId"]
        assert "bob" == bob_preview["userId"]
        assert [action["kind"] for action in alice_preview["plan"]["actions"]] != [
            action["kind"] for action in bob_preview["plan"]["actions"]
        ]

    def test_delete_program_skips_garmin_login_when_state_is_empty(self) -> None:
        self.client_factory.reset_mock()

        result = self.service.delete_program(None, "plan.yaml")

        self.client_factory.assert_not_called()
        assert result == {
            "deleted": "plan.yaml",
            "activeProgramCleared": False,
            "garminCleanedUp": False,
        }
        assert not self.path.exists()

    def test_delete_program_calls_garmin_when_state_has_workout_id(self) -> None:
        from tests.fakes import FakeGarmin

        fake = FakeGarmin()
        self.client_factory = Mock(return_value=fake)
        self.service = WebSyncService(
            self.store,
            repository=self.repository,
            client_factory=self.client_factory,
            today=lambda: date(2026, 12, 30),
        )
        state = self.repository.load("characterization-plan")
        state["workouts"]["week-01/mixed"] = {
            "name": "Mixed",
            "status": "scheduled",
            "workout_id": 42,
            "schedule_id": 43,
            "date": "2026-12-28",
        }
        self.repository.save("characterization-plan", state)

        result = self.service.delete_program(None, "plan.yaml")

        self.client_factory.assert_called_once_with()
        assert result["garminCleanedUp"] is True
        assert result["deleted"] == "plan.yaml"
        assert not self.path.exists()

    def test_delete_program_logs_in_when_state_has_only_schedule_id(self) -> None:
        from tests.fakes import FakeGarmin

        fake = FakeGarmin()
        self.client_factory = Mock(return_value=fake)
        self.service = WebSyncService(
            self.store,
            repository=self.repository,
            client_factory=self.client_factory,
            today=lambda: date(2026, 12, 30),
        )
        state = self.repository.load("characterization-plan")
        state["workouts"]["week-01/easy"] = {
            "name": "Easy",
            "status": "scheduled",
            "schedule_id": 17,
            "date": "2026-12-29",
        }
        self.repository.save("characterization-plan", state)

        result = self.service.delete_program(None, "plan.yaml")

        self.client_factory.assert_called_once_with()
        assert result["garminCleanedUp"] is True

    def test_delete_program_raises_not_found_for_missing_file(self) -> None:
        with pytest.raises(WebError) as error:
            self.service.delete_program(None, "missing.yaml")
        assert error.value.status == 404
