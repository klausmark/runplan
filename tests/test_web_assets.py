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
        assert 'openModal($("#user-dialog"))' in script
        assert 'id="user-settings-dialog"' in html
        assert 'id="user-settings-five-k-best"' in html
        assert 'id="user-settings-pace-zone"' in html
        assert 'id="user-settings-garmin-password"' in html
        assert "hasGarminPassword" in script
        assert "fiveKBest" in script
        assert "paceZoneSecondsPerKm" in script

    def test_empty_program_state_and_yaml_upload_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="empty-programs"' in html
        assert 'id="program-file-input"' in html
        assert "showEmptyPrograms()" in script
        assert 'request("/api/programs", {' in script
        assert "filename: file.name" in script
        assert "async function activateProgram(" in script
        assert 'openAddProgramDialog("upload")' in script
        assert 'openAddProgramDialog("templates")' in script

    def test_template_browser_button_and_dialog_are_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="empty-browse-templates-button"' in html
        assert 'id="add-program-dialog"' in html
        assert 'id="add-program-button"' in html
        assert 'id="add-program-toggle"' in html
        assert 'id="add-program-menu"' in html
        assert 'data-tab="upload"' in html
        assert 'data-tab="templates"' in html
        assert 'id="template-detail"' in html
        assert 'id="template-start-week"' in html
        assert "function openAddProgramDialog(" in script
        assert "function switchAddProgramTab(" in script
        assert 'request("/api/templates")' in script
        assert "/api/templates/${encodeURIComponent(templateId)}/copy" in script
        assert "async function activateProgram(" in script
        assert ".template-card" in styles
        assert ".split-button" in styles
        assert ".add-program-dialog" in styles

    def test_coaching_guide_section_is_packaged(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="coaching-guide"' in html
        assert 'id="coaching-body"' in html
        assert 'id="coaching-eyebrow"' in html
        assert "function renderCoachingGuide(" in script
        assert ".coaching-guide" in styles
        assert ".coaching-pace-chart" in styles
        assert "renderCoachingGuide(program.program.coaching)" in script

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

    def test_garmin_sync_uses_confirmation_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="sync-preview-dialog"' in html
        assert 'id="sync-preview-confirm"' in html
        assert 'id="sync-preview-cancel"' in html
        assert "renderSyncPreview" in script
        assert "openModal(dialog)" in script
        assert "dialog.close" in script
        assert "syncPreviewDialog" not in script
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

    def test_add_workout_dialog_uses_a_recipe_selector_with_a_week_preview(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="add-workout-builder"' in html
        assert 'id="recipe-categories"' in html
        assert 'id="recipe-detail"' in html
        assert 'id="recipe-select"' in html
        assert 'id="recipe-dose-form"' in html
        assert 'id="recipe-totals"' in html
        assert 'id="week-preview"' in html
        assert 'id="week-preview-days"' in html
        assert 'request("/api/recipes")' in script
        assert "/api/recipes/preview" in script
        assert "renderRecipeDetail" in script
        assert "renderRecipeDoseForm" in script
        assert "renderWeekPreview" in script
        assert "scheduleRecipePreview" in script
        assert "DEFAULT_RECIPE_FORM" in script
        assert ".recipe-categories" in styles
        assert ".recipe-dose" in styles
        assert ".week-preview-day" in styles

    def test_add_workout_dialog_keeps_the_advanced_yaml_editor_as_escape_hatch(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="workout-yaml-details"' in html
        assert "Advanced: Edit workout YAML" in html
        assert 'id="workout-yaml"' in html
        assert "novalidate" in html
        assert "function buildRecipeYaml(" in script
        assert '$("#workout-yaml").value = state.workout.recipe.yaml' in script

    def test_add_workout_save_branch_still_uses_the_existing_add_workout_payload(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        submit_index = script.index('$("#workout-form").addEventListener("submit"')
        submit_block = script[submit_index : script.index("\n", submit_index + 400)]
        assert "add_workout: { week: state.workout.week" in submit_block
        assert 'yaml: $("#workout-yaml").value' in submit_block

    def test_workout_deletion_uses_a_named_confirmation_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="delete-workout-dialog"' in html
        assert 'id="delete-workout-title"' in html
        assert "during the next reviewed and confirmed sync" in script
        assert "delete_workout: { week: state.workout.week" in script
        assert "deleteButton.disabled = onlyWorkout" in script
        assert "only workout and cannot be deleted" in script

    def test_program_deletion_uses_a_named_confirmation_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="delete-program-dialog"' in html
        assert 'id="delete-program-title"' in html
        assert 'id="delete-program-button"' in html
        assert "permanently removes the YAML file" in script
        assert "state.program.program.name" in script
        assert 'method: "DELETE"' in script
        assert "#settings-dialog footer .danger" in styles

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
        assert "function openWorkout(" in script
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
        assert "card.draggable = workout.can_move" not in script
        assert "card.dataset.moveable = String(workout.can_move)" in script
        assert "if (workout.can_move)" in script
        assert "cell.dataset.moveLocked = String(workout?.can_move === false)" in script
        assert 'candidate?.dataset.moveLocked === "true" ? null : candidate' in script
        assert "function canMoveRequest(" in script
        assert "Completed workouts can only be moved by editing YAML directly." in script
        assert "Beginning drag on a completed workout" not in script

    def test_card_click_opens_edit_dialog(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'edit.textContent = "Edit →"' not in script
        assert 'class="edit-workout"' not in script
        assert "openWorkout(week, workout)" in script
        assert 'content.addEventListener("click"' in script
        assert 'content.className = "workout-content"' in script
        assert "event.preventDefault()" in script

    def test_card_keyboard_activation_opens_edit_dialog(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'content.setAttribute("role", "button")' in script
        assert "content.tabIndex = 0" in script
        assert 'event.key === "Enter"' in script
        assert 'event.key === " "' in script

    def test_drag_handle_activates_pointer_drag(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'handle.className = "workout-drag-handle"' in script
        assert 'handle.addEventListener("pointerdown"' in script
        assert 'card.addEventListener("pointerdown"' not in script
        assert 'card.addEventListener("dragstart"' not in script
        assert 'card.addEventListener("touchstart"' not in script
        assert 'addEventListener("dragover"' not in script
        assert 'addEventListener("drop"' not in script
        assert 'document.addEventListener("pointermove"' in script
        assert 'document.addEventListener("pointerup"' in script
        assert "> MOVE_THRESHOLD" in script
        assert "MOVE_THRESHOLD = 6" in script

    def test_drag_handle_tap_and_keyboard_activation_offer_move_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'id="move-dialog"' in html
        assert 'id="move-form"' in html
        assert 'id="move-week"' in html
        assert 'id="move-day"' in html
        assert 'handle.setAttribute("aria-label", `Move ${workout.name}`)' in script
        assert 'handle.addEventListener("click"' in script
        assert "function openMove(" in script
        assert "function updateMoveDayOptions(" in script
        assert '$("#move-form").addEventListener("submit"' in script
        assert "occupant?.can_move === false" in script

    def test_pointer_drag_renames_touch_helpers(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert "cancelTouchDrag" not in script
        assert "beginTouchDrag" not in script
        assert "moveTouchDrag" not in script
        assert "endTouchDrag" not in script
        assert "touchById" not in script
        assert "function cancelPointerDrag(" in script
        assert "function beginPointerDrag(" in script
        assert "function movePointerDrag(" in script
        assert "function endPointerDrag(" in script

    def test_touch_drag_uses_long_press_to_avoid_swallowing_taps(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert "TOUCH_LONG_PRESS_MS = 350" in script
        assert "TOUCH_CANCEL_DISTANCE = 10" in script
        assert 'event.pointerType !== "mouse"' in script
        assert "window.setTimeout(activatePointerDrag, TOUCH_LONG_PRESS_MS)" in script
        begin_block = script[
            script.index("function beginPointerDrag(") : script.index(
                "function activatePointerDrag("
            )
        ]
        assert "TOUCH_LONG_PRESS_MS" in begin_block
        move_block = script[
            script.index("function movePointerDrag(") : script.index("function endPointerDrag(")
        ]
        assert "TOUCH_CANCEL_DISTANCE" in move_block
        assert "cancelPointerDrag()" in move_block
        end_block = script[
            script.index("function endPointerDrag(") : script.index("function cancelPointerDrag(")
        ]
        assert "TOUCH_CANCEL_DISTANCE" in end_block
        cancel_block = script[
            script.index("function cancelPointerDrag(") : script.index(
                '\ndocument.addEventListener("pointermove"'
            )
        ]
        assert "window.clearTimeout(drag.timer)" in cancel_block

    def test_pointer_capture_only_after_drag_activates(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        begin_block = script[
            script.index("function beginPointerDrag(") : script.index(
                "function activatePointerDrag("
            )
        ]
        assert "setPointerCapture" not in begin_block
        activate_block = script[
            script.index("function activatePointerDrag(") : script.index(
                "function positionPointerGhost("
            )
        ]
        assert "drag.handle.setPointerCapture(drag.pointerId)" in activate_block
        cancel_block = script[
            script.index("function cancelPointerDrag(") : script.index(
                '\ndocument.addEventListener("pointermove"'
            )
        ]
        assert "releasePointerCapture" in cancel_block

    def test_only_drag_handle_blocks_native_touch_gestures(self) -> None:
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert ".workout-drag-handle" in styles
        assert "touch-action: none" in styles
        assert '.workout[data-moveable="true"] { touch-action: none' not in styles
        activate_block = script[
            script.index("function activatePointerDrag(") : script.index(
                "function positionPointerGhost("
            )
        ]
        assert "touchAction" not in activate_block
        cancel_block = script[
            script.index("function cancelPointerDrag(") : script.index("\nfunction openMove(")
        ]
        assert "touchAction" not in cancel_block

    def test_click_suppression_only_after_a_real_drag(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        end_block = script[
            script.index("function endPointerDrag(") : script.index("function cancelPointerDrag(")
        ]
        assert "suppressClick" in end_block
        assert (
            "const threshold = drag.isTouch ? TOUCH_CANCEL_DISTANCE : MOVE_THRESHOLD" in end_block
        )
        assert "Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > threshold" in end_block
        assert 'drag.handle.dataset.suppressClick = "true"' in end_block

    def test_workout_overview_section_is_present_in_edit_dialog(self) -> None:
        html = (ASSET_DIR / "index.html").read_text(encoding="utf-8")
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert 'id="workout-overview"' in html
        assert 'id="workout-steps"' in html
        assert 'id="workout-overview-title"' in html
        assert "function renderWorkoutSteps(" in script
        assert "function setWorkoutOverview(" in script
        assert "setWorkoutOverview(workout.steps)" in script
        assert ".workout-overview" in styles
        assert ".workout-step-pace" in styles
        assert ".workout-step-note" in styles

    def test_workout_overview_is_hidden_in_add_workout_mode(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        add_start = script.index("function openAddWorkout(")
        next_function = script.index("\nfunction ", add_start + 1)
        add_section = script[add_start:next_function]
        assert "setWorkoutOverview(null)" in add_section

    def test_workout_overview_renders_steps_without_innerHTML(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        index = script.index("function renderStepList(")
        block = script[index : script.index("function renderWorkoutSteps(", index)]
        assert "innerHTML" not in block
        assert "createElement" in block
        assert "textContent" in block

    def test_dialog_backdrop_click_closes_every_modal(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert "function openModal(" in script
        assert "setupDialogChrome()" in script
        assert 'querySelectorAll("dialog")' in script
        click_block = script[
            script.index('dialog.addEventListener("click"') : script.index(
                "});", script.index('dialog.addEventListener("click"')
            )
        ]
        assert "event.target !== dialog" in click_block
        assert 'dialog.close("backdrop")' in click_block
        cancel_block = script[
            script.index('dialog.addEventListener("cancel"') : script.index(
                "});", script.index('dialog.addEventListener("cancel"')
            )
        ]
        assert 'dialog.id === "user-dialog"' in cancel_block
        assert "!state.user" in cancel_block

    def test_user_dialog_remains_mandatory_before_selection(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        assert 'addEventListener("cancel", (event) =>' not in script
        block = script[
            script.index('dialog.addEventListener("cancel"') : script.index(
                "});", script.index('dialog.addEventListener("cancel"')
            )
        ]
        assert "user-dialog" in block

    def test_body_scroll_is_locked_while_a_dialog_is_open(self) -> None:
        script = (ASSET_DIR / "app.js").read_text(encoding="utf-8")
        styles = (ASSET_DIR / "styles.css").read_text(encoding="utf-8")
        assert "function lockBodyScroll(" in script
        assert "function unlockBodyScroll(" in script
        assert "openDialogCount" in script
        assert 'document.body.classList.add("dialog-open")' in script
        assert 'document.body.classList.remove("dialog-open")' in script
        assert "body.dialog-open" in styles
        assert "overflow: hidden" in styles.split("body.dialog-open", 1)[1].split("}", 1)[0]
        sync_start = script.index("async function syncGarmin()")
        sync_end = script.index("\nfunction ", sync_start + 1)
        sync_block = script[sync_start:sync_end]
        assert "openModal(dialog)" in sync_block
