from __future__ import annotations

from io import BytesIO
from pathlib import Path
from unittest.mock import Mock

from runplan.web import (
    ASSET_DIR,
    ProgramStore,
    make_handler,
)
from tests.web_helpers import fake_authenticator


class TestWebAsset:
    def test_password_gate_is_packaged_and_precedes_studio_initialization(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")

        assert 'id="auth-form"' in html
        assert 'id="auth-password" type="password"' in html
        assert 'autocomplete="current-password"' in html
        assert 'class="auth-pending"' in html
        assert 'request("/api/auth/status")' in script
        assert 'request("/api/auth/challenge")' in script
        assert 'request("/api/auth/login"' in script
        assert "window.crypto.subtle.deriveKey" in script
        assert script.rstrip().endswith("initializeAuthentication();")
        assert 'localStorage.setItem("runplan_auth"' not in script

    def test_runplan_favicon_is_packaged_and_linked(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        favicon = (ASSET_DIR / "favicon.svg").read_text(encoding="utf-8")
        assert 'rel="icon" type="image/svg+xml" href="/favicon.svg"' in html
        assert '<img class="brand-mark" src="/favicon.svg" width="34" height="34" alt="">' in html
        assert '<span class="brand-mark">R</span>' not in html
        assert 'fill="#1d6b4d"' in favicon
        assert '<g transform="rotate(-4 32 32)">' in favicon
        assert 'fill="#fff" fill-rule="evenodd"' in favicon
        assert "l9 7-6 6-9-7-4-3" in favicon
        assert "stroke=" not in favicon

    def test_favicon_is_served_as_svg(self, tmp_path: Path) -> None:
        store = ProgramStore(tmp_path)
        handler = object.__new__(make_handler(store, authenticator=fake_authenticator()))
        handler.path = "/favicon.svg"
        handler.client_address = ("127.0.0.1", 1234)
        handler.headers = {}
        handler.wfile = BytesIO()
        handler.send_response = Mock()
        handler.send_header = Mock()
        handler.end_headers = Mock()

        handler._get()

        handler.send_response.assert_called_once_with(200)
        handler.send_header.assert_any_call("Content-Type", "image/svg+xml; charset=utf-8")
        assert handler.wfile.getvalue().startswith(b"<svg")

    def test_theme_control_and_dark_palette_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="theme-button"' in html
        assert 'localStorage.getItem("runplan-theme")' in html
        assert 'localStorage.setItem("runplan-theme"' in script
        assert '[data-theme="dark"]' in styles
        assert 'notify("Workout moved' not in script
        assert 'notify("Plan settings saved' not in script

    def test_user_choice_is_local_and_active_program_is_server_backed(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="user-dialog"' in html
        assert 'id="user-select"' in html
        assert 'id="add-user-button"' in html
        assert 'id="user-cancel"' in html
        assert '$("#add-user-button").addEventListener' in script
        assert 'const USER_STORAGE_KEY = "runplan-user"' in script
        assert "`runplan-program:${userId}`" in script
        assert "state.user.activeProgram" in script
        assert "/active-program" in script
        assert 'request("/api/users")' in script
        assert '$("#user-dialog").showModal()' in script
        assert 'id="user-settings-dialog"' in html
        assert 'id="user-settings-default-pace"' in html
        assert 'id="user-settings-garmin-password"' in html
        assert "hasGarminPassword" in script

    def test_empty_program_state_and_yaml_upload_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="empty-programs"' in html
        assert 'id="program-file-input"' in html
        assert "showEmptyPrograms()" in script
        assert 'request("/api/programs", {' in script
        assert "filename: file.name" in script

    def test_standard_first_10k_generation_dialog_is_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")

        assert 'id="generate-program-button"' in html
        assert 'id="empty-generate-program-button"' in html
        assert 'id="generation-dialog"' in html
        assert 'aria-labelledby="generation-dialog-title"' in html
        assert "Complete your first 10K" in html
        assert "I don't have a race date" in html
        assert 'value="tuesday" checked' in html
        assert 'value="thursday" checked' in html
        assert 'value="sunday" checked' in html
        assert 'id="generation-long-run-day"' in html
        assert 'id="generation-yaml"' in html
        assert 'id="generation-filename"' in html
        assert '<details id="generation-advanced"' in html

        request_start = script.index("function standardGenerationRequest()")
        request_end = script.index("function fillDraftMessages", request_start)
        standard_request = script[request_start:request_end]
        assert "averageWeeklyKm" in standard_request
        assert "runDaysPerWeek" in standard_request
        assert "longestRecentRun" in standard_request
        assert "recent5KDurationMinutes" in standard_request
        assert "easyPace" in standard_request
        assert 'progression: $("#generation-progression").value' in standard_request
        assert (
            'qualitySessionsPerWeek: Number($("#generation-quality-sessions").value)'
            in standard_request
        )
        assert "if (startWeek) generationRequest.startWeek = startWeek" in standard_request
        assert "if (durationWeeks !== null)" in standard_request
        assert 'request("/api/programs/generate", {' in script
        assert 'request("/api/programs", {' in script
        assert "await loadPrograms(savedFilename)" in script
        assert "/active-program" in script
        assert (
            "syncGarmin"
            not in script[request_start : script.index("function fillUserSelects", request_start)]
        )

        assert 'request("/api/program-generation/status")' in script
        assert "button.disabled = !configured" in script
        assert "Program generation is not configured on this server" in script
        assert (
            "catch (_)"
            in script[script.index("async function loadGenerationStatus") : request_start]
        )
        assert "state.generation.submitting" in script
        assert 'button.textContent = "Generating…"' in script
        assert "error.status === 422" in script
        assert '$("#generation-dialog").showModal()' in script
        assert '$("#generation-dialog").addEventListener("cancel"' in script
        assert '$("#generation-review-view").classList.contains("hidden")' in script
        assert ".generation-dialog footer" in styles
        assert "position: sticky" in styles
        assert "@media (max-width: 760px)" in styles

    def test_advanced_generation_constraints_and_interactions_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")

        advanced_start = html.index('id="generation-advanced"')
        advanced_end = html.index("</details>", advanced_start)
        advanced = html[advanced_start:advanced_end]
        assert " open" not in html[advanced_start : html.index(">", advanced_start)]
        assert "<summary>Advanced</summary>" in advanced
        assert 'id="generation-start-week" type="week"' in advanced
        assert 'id="generation-duration" type="number" min="4" max="52" step="1"' in advanced
        assert 'id="generation-maximum-weekly-km" type="number" min="0.1"' in advanced
        assert 'id="generation-maximum-long-run-km" type="number" min="0.1"' in advanced
        assert '<option value="balanced" selected>Balanced</option>' in advanced
        assert '<option value="0" selected>0</option>' in advanced
        assert 'id="generation-club-rows"' in advanced
        assert 'id="generation-b-race-rows"' in advanced
        assert 'maxlength="1000"' in advanced
        generation_dialog = html[
            html.index('id="generation-dialog"') : html.index(
                "</dialog>", html.index('id="generation-dialog"')
            )
        ]
        assert "sent to MiniMax" in generation_dialog
        assert "sent to MiniMax" not in advanced
        assert "does not send credentials or activity history" in generation_dialog
        assert "system prompt" not in advanced.lower()

        assert "function isoWeekMonday(value)" in script
        assert "Date.UTC(year, 0, 4)" in script
        assert "generationRequest.startWeek = startWeek" in script
        assert "generationRequest.maximumWeeklyKm = maximumWeeklyKm" in script
        assert "generationRequest.maximumLongRunKm = maximumLongRunKm" in script
        assert "generationRequest.additionalInstructions = additionalInstructions" in script
        assert "generationRequest.clubSessions = clubSessions" in script
        assert "generationRequest.bRaces = bRaces" in script
        assert "amount: { [amountKind]:" in script
        assert 'maxlength="500"' in script
        assert 'value="training-run"' in script
        assert 'aria-label="Remove recurring club session"' in script
        assert 'aria-label="Remove B race"' in script
        assert "row.remove()" in script

        assert "updateGenerationClubDays()" in script
        assert 'document.querySelectorAll(".generation-club-weekday")' in script
        assert "Each club session must use a different training weekday." in script
        assert "Each B race must use a different date." in script
        assert "input.min = start" in script
        assert "input.max = end" in script
        assert "below 8 weeks" in script
        assert "above 16 weeks" in script
        assert "contains consecutive training days" in script
        assert "main race takes precedence" in script
        assert '$("#generation-advanced").open = false' in script
        assert '$("#generation-club-rows").replaceChildren()' in script
        assert '$("#generation-b-race-rows").replaceChildren()' in script

        assert ".generation-advanced" in styles
        assert ".repeated-row" in styles
        assert "grid-template-columns: 1fr" in styles
        mobile = styles[styles.index("@media (max-width: 760px)") :]
        assert ".repeated-heading" in mobile
        assert ".repeated-row .row-wide" in mobile

    def test_past_weeks_are_locally_persisted_collapsible_details(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'document.createElement("details")' in script
        assert 'document.createElement("summary")' in script
        assert "addDays(startDate, 6) < today" in script
        assert "runplan-week-open:${userId}:${programId}:${week}" in script
        assert 'section.open ? "open" : "closed"' in script
        assert ".week:not([open]) > .week-heading" in styles
        assert ".week-heading:focus-visible" in styles
        assert "prefers-reduced-motion" in styles

    def test_recovery_ui_is_not_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="recovery-button"' not in html
        assert 'id="recovery-dialog"' not in html
        assert "/sync/recovery" not in script
        assert "recoveryPreview" not in script

    def test_garmin_sync_is_one_click_without_review_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="sync-dialog"' not in html
        assert "syncPreview" not in script
        assert '$("#sync-button").addEventListener("click", syncGarmin)' in script
        assert "confirmationToken: preview.confirmationToken" in script
        assert 'button.textContent = "Checking…"' in script
        assert 'button.textContent = "Syncing…"' in script
        assert 'button.textContent = "Done"' in script
        assert "}, 2000);" in script
        assert "showError(error.message)" in script

    def test_yaml_editor_uses_horizontal_scrolling_instead_of_wrapping(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert '<details id="workout-yaml-details" class="yaml-details">' in html
        assert "Advanced: Edit workout YAML" in html
        assert 'id="workout-yaml" class="code-editor" wrap="off"' in html
        assert "overflow-x: auto" in styles
        assert "white-space: pre" in styles

    def test_workout_yaml_disclosure_matches_the_editor_mode(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        details_start = html.index('id="workout-yaml-details"')
        details_end = html.index("</details>", details_start)
        assert html.index('id="workout-activities"') < details_start
        assert details_start < html.index('id="save-workout-button"') < details_end
        assert '$("#workout-yaml-details").open = false;' in script
        assert '$("#workout-yaml-details").open = true;' in script

    def test_calendar_undo_and_explicit_operation_states_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="app-status"' in html
        assert 'id="undo-move"' in html
        assert "async function undoLastMove()" in script
        assert "state.undoMove = { fromWeek: toWeek" in script
        assert script.count("userId: state.user.id") >= 4
        assert "payload.workout || payload.add_workout" in script
        assert 'setAppStatus("garmin", "Syncing Garmin…")' in script
        assert '[data-status="failed"]' in styles
        assert 'showError("Saved' not in script

    def test_calendar_can_add_workouts_from_empty_days_with_yaml_help(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="workout-yaml-reference"' in html
        assert "Workout YAML syntax" in html
        assert "warmup" in html and "repeat" in html and "pace" in html
        assert 'add.className = "add-workout"' in script
        assert "function workoutTemplate(week, day)" in script
        assert "id: ${nextWorkoutId(week)}" in script
        assert "add_workout: { week: state.workout.week" in script
        assert ".add-workout" in styles

    def test_workout_deletion_uses_a_named_confirmation_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="delete-workout-dialog"' in html
        assert 'id="delete-workout-title"' in html
        assert "during the next reviewed and confirmed sync" in script
        assert "delete_workout: { week: state.workout.week" in script
        assert "deleteButton.disabled = onlyWorkout" in script
        assert "only workout and cannot be deleted" in script

    def test_workout_activity_checklist_manages_same_day_links(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="activity-link-dialog"' not in html
        assert 'id="workout-activities"' in html
        assert 'id="activity-apply"' in html
        assert 'id="activity-unlink-dialog"' not in html
        assert "Show ±3 days" not in html
        assert "workout.can_manage_activities" in script
        assert "windowDays" not in script
        assert "activityIds" in script
        assert "activity-links" in script
        assert 'checkbox.type = "checkbox"' in script
        assert 'edit.textContent = "Edit →"' in script
        assert '$("#activity-apply").disabled = yamlChanged' in script
        assert '$("#save-workout-button").disabled = activitiesChanged' in script
        assert ".activity-candidate" in styles

    def test_mobile_header_uses_a_compact_menu_and_bottom_sheet(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'class="topbar-primary"' in html
        assert 'id="mobile-menu-button"' in html
        assert 'id="mobile-menu-backdrop"' in html
        assert 1 == html.count("data-theme-toggle")
        assert "function setMobileMenu(open" in script
        assert 'event.key === "Escape"' in script
        assert "updateHeaderForScroll" not in script
        assert ".topbar.menu-open .topbar-actions-shell" in styles
        assert "body.mobile-menu-open .mobile-menu-backdrop" in styles
        assert "prefers-reduced-motion: reduce" in styles

    def test_completed_workouts_are_locked_out_of_every_calendar_move_path(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert "card.draggable = workout.can_move" in script
        assert "if (workout.can_move)" in script
        assert "cell.dataset.moveLocked = String(workout?.can_move === false)" in script
        assert 'candidate?.dataset.moveLocked === "true" ? null : candidate' in script
        assert "function canMoveRequest(" in script
        assert "Completed workouts can only be moved by editing YAML directly." in script
        assert ".workout-locked" in styles
