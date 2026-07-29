const state = { users: [], user: null, program: null, dragged: null, touchDrag: null, workout: null, move: null, undoMove: null };
const $ = (selector) => document.querySelector(selector);
const TOUCH_DRAG_DELAY = 350;
const TOUCH_CANCEL_DISTANCE = 10;
const USER_STORAGE_KEY = "runplan-user";
const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
let studioInitialized = false;

function storedValue(key) {
  try { return window.localStorage.getItem(key); } catch (_) { return null; }
}

function storeValue(key, value) {
  try { window.localStorage.setItem(key, value); } catch (_) {}
}

function programStorageKey(userId) { return `runplan-program:${userId}`; }
function weekOpenStorageKey(userId, programId, week) { return `runplan-week-open:${userId}:${programId}:${week}`; }
function userQuery() { return `user=${encodeURIComponent(state.user.id)}`; }

async function request(url, options = {}) {
  const response = await fetch(url, options);
  const type = response.headers.get("content-type") || "";
  const body = type.includes("json") ? await response.json() : null;
  if (!response.ok) {
    const error = new Error(body?.error || `Request failed (${response.status})`);
    error.status = response.status;
    if (response.status === 401 && !url.startsWith("/api/auth/")) showLogin();
    throw error;
  }
  return body;
}

function showLogin(message = "") {
  document.body.classList.remove("authenticated");
  document.body.classList.add("auth-pending");
  const error = $("#auth-error");
  error.textContent = message;
  error.classList.toggle("hidden", !message);
  $("#auth-password").focus();
}

function showStudio() {
  document.body.classList.add("authenticated");
  document.body.classList.remove("auth-pending");
}

function decodeBase64Url(value) {
  const padded = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  return Uint8Array.from(atob(padded), character => character.charCodeAt(0));
}

function encodeBase64Url(value) {
  const binary = Array.from(new Uint8Array(value), byte => String.fromCharCode(byte)).join("");
  return btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

async function passwordProof(password, challenge) {
  if (!window.isSecureContext || !window.crypto?.subtle) {
    throw new Error("Runplan login requires HTTPS or localhost.");
  }
  const material = await window.crypto.subtle.importKey(
    "raw",
    new TextEncoder().encode(password),
    "PBKDF2",
    false,
    ["deriveKey"],
  );
  const key = await window.crypto.subtle.deriveKey(
    {
      name: "PBKDF2",
      salt: decodeBase64Url(challenge.salt),
      iterations: challenge.iterations,
      hash: "SHA-256",
    },
    material,
    { name: "HMAC", hash: "SHA-256", length: 256 },
    false,
    ["sign"],
  );
  return encodeBase64Url(
    await window.crypto.subtle.sign("HMAC", key, decodeBase64Url(challenge.nonce)),
  );
}

async function initializeAuthentication() {
  try {
    const status = await request("/api/auth/status");
    if (!status.authenticated) {
      showLogin();
      return;
    }
    showStudio();
    if (!studioInitialized) {
      studioInitialized = true;
      await initialize();
    }
  } catch (error) {
    showLogin(error.message);
  }
}

function setAppStatus(kind, label, detail = null) {
  $("#app-status").dataset.status = kind;
  $("#save-status").textContent = label;
  $("#start-week").textContent = detail ?? (state.program ? `Starts ${state.program.program.start_week}` : "");
}

function setSaveFailure(error) {
  setAppStatus(error.status === 422 ? "validation" : "failed", error.status === 422 ? "Validation failed" : "Save failed");
}

function updateUndoControl() {
  $("#undo-move").classList.toggle("hidden", !state.undoMove);
}

function clearUndoMove() {
  state.undoMove = null;
  updateUndoControl();
}

function showEmptyPrograms() {
  state.program = null;
  clearUndoMove();
  $("#program-name").textContent = "No programs yet";
  $("#program-description").textContent = "Upload a YAML running program to get started.";
  $("#calendar").replaceChildren();
  $("#empty-programs").classList.remove("hidden");
  $("#app-status").classList.add("hidden");
  $("#program-select").disabled = true;
  for (const selector of ["#sync-button", "#settings-button", "#export-button"]) {
    $(selector).disabled = true;
  }
}

function showProgramControls() {
  $("#empty-programs").classList.add("hidden");
  $("#app-status").classList.remove("hidden");
  $("#program-select").disabled = false;
  for (const selector of ["#sync-button", "#settings-button", "#export-button"]) {
    $(selector).disabled = false;
  }
}

function showError(message) {
  const notice = $("#notice");
  notice.textContent = message;
  notice.classList.remove("hidden");
  window.clearTimeout(showError.timer);
  showError.timer = window.setTimeout(() => notice.classList.add("hidden"), 8000);
}

const systemTheme = window.matchMedia("(prefers-color-scheme: dark)");

function savedTheme() {
  try {
    const value = window.localStorage.getItem("runplan-theme");
    return value === "light" || value === "dark" ? value : null;
  } catch (_) {
    return null;
  }
}

function applyTheme(theme, persist = false) {
  document.documentElement.dataset.theme = theme;
  if (persist) {
    try { window.localStorage.setItem("runplan-theme", theme); } catch (_) {}
  }
  const dark = theme === "dark";
  document.querySelectorAll("[data-theme-toggle]").forEach((button) => {
    button.textContent = dark ? "☾" : "☀";
    button.setAttribute("aria-pressed", String(dark));
    button.setAttribute("aria-label", `${dark ? "Dark" : "Light"} theme active. Switch to ${dark ? "light" : "dark"} theme`);
    button.title = `Switch to ${dark ? "light" : "dark"} theme`;
  });
}

applyTheme(document.documentElement.dataset.theme || (systemTheme.matches ? "dark" : "light"));
document.querySelectorAll("[data-theme-toggle]").forEach((button) => button.addEventListener("click", () => {
  applyTheme(document.documentElement.dataset.theme === "dark" ? "light" : "dark", true);
}));
systemTheme.addEventListener("change", (event) => {
  if (!savedTheme()) applyTheme(event.matches ? "dark" : "light");
});

const mobileLayout = window.matchMedia("(max-width: 760px)");

function setMobileMenu(open, returnFocus = true) {
  const active = mobileLayout.matches && open;
  const shell = $(".topbar-actions-shell");
  $(".topbar").classList.toggle("menu-open", active);
  document.body.classList.toggle("mobile-menu-open", active);
  $("#mobile-menu-button").setAttribute("aria-expanded", String(active));
  shell.inert = mobileLayout.matches && !active;
  shell.setAttribute("aria-hidden", String(mobileLayout.matches && !active));
  $("main").inert = active;
  $(".topbar-primary").inert = active;
  if (mobileLayout.matches) {
    shell.setAttribute("role", "dialog");
    shell.setAttribute("aria-modal", "true");
    shell.setAttribute("aria-label", "Runplan menu");
  } else {
    shell.removeAttribute("role");
    shell.removeAttribute("aria-modal");
    shell.removeAttribute("aria-label");
  }
  if (active) {
    shell.querySelector("select, button")?.focus();
  } else if (returnFocus && mobileLayout.matches) {
    $("#mobile-menu-button").focus();
  }
}

setMobileMenu(false, false);
mobileLayout.addEventListener("change", () => setMobileMenu(false, false));
$("#mobile-menu-button").addEventListener("click", () => setMobileMenu(true, false));
$("#mobile-menu-close").addEventListener("click", () => setMobileMenu(false));
$("#mobile-menu-backdrop").addEventListener("click", () => setMobileMenu(false));
$(".top-actions").addEventListener("click", (event) => {
  const button = event.target.closest("button");
  if (button && button.id !== "export-button" && !button.matches("[data-theme-toggle]")) setMobileMenu(false, false);
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && $(".topbar").classList.contains("menu-open")) setMobileMenu(false);
});

function dateLabel(iso) {
  return new Intl.DateTimeFormat("en", { day: "numeric", month: "short" }).format(new Date(`${iso}T12:00:00`));
}

function addDays(iso, days) {
  const value = new Date(`${iso}T00:00:00Z`);
  value.setUTCDate(value.getUTCDate() + days);
  return value.toISOString().slice(0, 10);
}

function localIsoDate(value = new Date()) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

function isPastWeek(startDate, today = localIsoDate()) {
  return addDays(startDate, 6) < today;
}

function storedWeekOpen(userId, programId, week) {
  const value = storedValue(weekOpenStorageKey(userId, programId, week));
  if (value === "open") return true;
  if (value === "closed") return false;
  return null;
}

function distanceLabel(meters, approximate = false) {
  const kilometers = meters / 1000;
  const value = new Intl.NumberFormat("en", { maximumFractionDigits: 1 }).format(kilometers);
  return `${approximate ? "~" : ""}${value} km`;
}

function durationLabel(seconds, approximate = false) {
  const minutes = Math.round(seconds / 60);
  const hours = Math.floor(minutes / 60);
  const remainder = minutes % 60;
  const value = hours ? `${hours}h${remainder ? ` ${remainder}m` : ""}` : `${remainder}m`;
  return `${approximate ? "~" : ""}${value}`;
}

const workoutStatusLabels = {
  planned: "Planned",
  scheduled: "Scheduled",
  completed: "Completed",
  missed: "Missed",
  retired: "Retired",
  changed: "Changed since sync",
};

let syncButtonResetTimer = null;

async function syncGarmin() {
  const button = $("#sync-button");
  const file = state.program.file;
  const userId = state.user.id;
  setMobileMenu(false, false);
  window.clearTimeout(syncButtonResetTimer);
  button.disabled = true;
  button.textContent = "Checking…";
  setAppStatus("garmin", "Checking Garmin…");
  try {
    const preview = await request(
      `/api/programs/${encodeURIComponent(file)}/sync/preview?user=${encodeURIComponent(userId)}`
    );
    button.textContent = "Syncing…";
    setAppStatus("garmin", "Syncing Garmin…");
    await request(`/api/programs/${encodeURIComponent(file)}/sync`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId, confirmationToken: preview.confirmationToken }),
    });
    if (state.user.id === userId && state.program?.file === file) await loadProgram(file);
    setAppStatus("garmin", "Garmin synced");
    button.textContent = "Done";
    button.disabled = true;
    syncButtonResetTimer = window.setTimeout(() => {
      button.textContent = "Sync Garmin";
      button.disabled = !state.program;
    }, 2000);
  } catch (error) {
    showError(error.message);
    button.textContent = "Sync Garmin";
    button.disabled = false;
    setAppStatus("failed", "Garmin sync failed");
  }
}

function render(program) {
  cancelTouchDrag();
  state.program = program;
  showProgramControls();
  $("#program-name").textContent = program.program.name;
  $("#program-description").textContent = program.program.description || "No program description";
  setAppStatus("saved", "Saved");
  updateUndoControl();
  const calendar = $("#calendar");
  calendar.replaceChildren(...program.weeks.map((week) => {
    const section = document.createElement("details");
    section.className = "week";
    const savedOpen = storedWeekOpen(state.user.id, program.program.id, week.week);
    section.open = savedOpen ?? !isPastWeek(week.start_date);
    const heading = document.createElement("summary");
    heading.className = "week-heading";
    const title = document.createElement("h2");
    title.textContent = `Week ${week.week}`;
    const details = document.createElement("div");
    details.className = "week-details";
    const focus = document.createElement("p");
    focus.textContent = week.focus || "";
    const total = document.createElement("strong");
    total.className = "week-distance";
    total.textContent = `${distanceLabel(week.effective_distance_meters, week.distance_is_approximate)} · ${durationLabel(week.effective_duration_seconds, week.distance_is_approximate)}`;
    details.append(focus, total);
    heading.append(title, details);
    const days = document.createElement("div");
    days.className = "days";
    for (let day = 1; day <= 7; day += 1) {
      const cell = document.createElement("div");
      cell.className = "day";
      cell.dataset.week = week.week;
      cell.dataset.day = day;
      const workout = week.workouts.find((item) => item.day === day);
      const label = document.createElement("div");
      label.className = "day-label";
      const dayName = document.createElement("span");
      dayName.textContent = WEEKDAYS[day - 1];
      const date = document.createElement("span");
      date.textContent = dateLabel(addDays(week.start_date, day - 1));
      label.append(dayName, date);
      cell.append(label);
      if (workout) {
        cell.append(workoutCard(week.week, workout));
      } else {
        const add = document.createElement("button");
        add.className = "add-workout";
        add.type = "button";
        add.textContent = "+ Add workout";
        add.setAttribute("aria-label", `Add workout to week ${week.week}, ${WEEKDAYS[day - 1]}`);
        add.addEventListener("click", () => openAddWorkout(week.week, day));
        cell.append(add);
      }
      cell.addEventListener("dragover", (event) => { event.preventDefault(); cell.classList.add("drag-over"); });
      cell.addEventListener("dragleave", () => cell.classList.remove("drag-over"));
      cell.addEventListener("drop", () => moveWorkout(week.week, day, cell));
      days.append(cell);
    }
    section.append(heading, days);
    section.addEventListener("toggle", (event) => {
      if (!event.isTrusted) return;
      storeValue(
        weekOpenStorageKey(state.user.id, program.program.id, week.week),
        section.open ? "open" : "closed",
      );
    });
    return section;
  }));
}

function workoutCard(week, workout) {
  const card = document.createElement("article");
  card.className = "workout";
  card.draggable = true;
  const title = document.createElement("h3");
  title.textContent = workout.name.replace(/^Week \d+\s*-\s*/, "");
  const status = document.createElement("span");
  status.className = `workout-status status-${workout.status}`;
  status.textContent = workoutStatusLabels[workout.status] || workout.status;
  const description = document.createElement("p");
  description.textContent = workout.description || "Structured workout";
  const summary = document.createElement("div");
  summary.className = "workout-summary";
  const shownDistance = workout.totals_are_actual ? workout.actual_distance_meters : workout.estimated_distance_meters;
  const shownDuration = workout.totals_are_actual ? workout.actual_duration_seconds : workout.estimated_duration_seconds;
  const totalsKind = workout.totals_are_actual ? "Actual" : "Planned";
  summary.textContent = `${totalsKind} · ${distanceLabel(shownDistance, workout.totals_are_actual ? false : workout.distance_is_approximate)} · ${durationLabel(shownDuration, workout.totals_are_actual ? false : workout.duration_is_approximate)}`;
  const edit = document.createElement("button");
  edit.className = "edit-workout";
  edit.type = "button";
  edit.textContent = "Edit YAML →";
  edit.addEventListener("click", () => openWorkout(week, workout));
  const move = document.createElement("button");
  move.className = "move-workout";
  move.type = "button";
  move.textContent = "↕ Move";
  move.title = "Hold and drag the card, or tap to choose a day";
  move.setAttribute("aria-label", `Move ${workout.name}`);
  move.addEventListener("click", () => openMove(week, workout));
  const actions = document.createElement("div");
  actions.className = "workout-actions";
  actions.append(move, edit);
  card.addEventListener("dragstart", () => { state.dragged = { week, workoutId: workout.id }; card.style.opacity = ".45"; });
  card.addEventListener("dragend", () => { state.dragged = null; card.style.opacity = ""; });
  card.addEventListener("touchstart", (event) => beginTouchDrag(event, card, week, workout), { passive: true });
  card.addEventListener("contextmenu", (event) => {
    if (state.touchDrag?.card === card) event.preventDefault();
  });
  card.append(status, title, summary, description, actions);
  return card;
}

function touchById(touches, identifier) {
  return Array.from(touches).find((touch) => touch.identifier === identifier);
}

function beginTouchDrag(event, card, week, workout) {
  if (event.touches.length !== 1 || event.target.closest("button")) return;
  const touch = event.changedTouches[0];
  cancelTouchDrag();
  state.touchDrag = {
    identifier: touch.identifier,
    card,
    week,
    workoutId: workout.id,
    day: workout.day,
    startX: touch.clientX,
    startY: touch.clientY,
    x: touch.clientX,
    y: touch.clientY,
    active: false,
    target: null,
    ghost: null,
    scrollFrame: null,
    timer: window.setTimeout(activateTouchDrag, TOUCH_DRAG_DELAY),
  };
}

function activateTouchDrag() {
  const drag = state.touchDrag;
  if (!drag) return;
  const bounds = drag.card.getBoundingClientRect();
  const ghost = drag.card.cloneNode(true);
  ghost.className = "workout touch-drag-ghost";
  ghost.style.width = `${bounds.width}px`;
  drag.offsetX = drag.startX - bounds.left;
  drag.offsetY = drag.startY - bounds.top;
  drag.ghost = ghost;
  drag.active = true;
  drag.card.classList.add("touch-drag-source");
  document.body.classList.add("touch-dragging");
  document.body.append(ghost);
  positionTouchGhost(drag.x, drag.y);
  updateTouchTarget(drag.x, drag.y);
  drag.scrollFrame = window.requestAnimationFrame(autoScrollTouchDrag);
  navigator.vibrate?.(25);
}

function positionTouchGhost(x, y) {
  const drag = state.touchDrag;
  if (!drag?.ghost) return;
  drag.ghost.style.transform = `translate3d(${x - drag.offsetX}px, ${y - drag.offsetY}px, 0)`;
}

function updateTouchTarget(x, y) {
  const drag = state.touchDrag;
  if (!drag?.active) return;
  const target = document.elementFromPoint(x, y)?.closest(".day") || null;
  if (target === drag.target) return;
  drag.target?.classList.remove("touch-drag-over");
  drag.target = target;
  drag.target?.classList.add("touch-drag-over");
}

function autoScrollTouchDrag() {
  const drag = state.touchDrag;
  if (!drag?.active) return;
  const edge = 72;
  const speed = drag.y < edge ? -10 : drag.y > window.innerHeight - edge ? 10 : 0;
  if (speed) {
    window.scrollBy(0, speed);
    updateTouchTarget(drag.x, drag.y);
  }
  drag.scrollFrame = window.requestAnimationFrame(autoScrollTouchDrag);
}

function moveTouchDrag(event) {
  const drag = state.touchDrag;
  if (!drag) return;
  const touch = touchById(event.touches, drag.identifier);
  if (!touch) return;
  drag.x = touch.clientX;
  drag.y = touch.clientY;
  if (!drag.active) {
    if (Math.hypot(touch.clientX - drag.startX, touch.clientY - drag.startY) > TOUCH_CANCEL_DISTANCE) {
      cancelTouchDrag();
    }
    return;
  }
  event.preventDefault();
  positionTouchGhost(touch.clientX, touch.clientY);
  updateTouchTarget(touch.clientX, touch.clientY);
}

async function endTouchDrag(event) {
  const drag = state.touchDrag;
  if (!drag || !touchById(event.changedTouches, drag.identifier)) return;
  if (!drag.active) {
    cancelTouchDrag();
    return;
  }
  event.preventDefault();
  const target = drag.target;
  const fromWeek = drag.week;
  const workoutId = drag.workoutId;
  const sameDay = target && Number(target.dataset.week) === drag.week && Number(target.dataset.day) === drag.day;
  cancelTouchDrag();
  if (!target || sameDay) return;
  try {
    await persistMove(fromWeek, workoutId, Number(target.dataset.week), Number(target.dataset.day));
  } catch (error) {
    setSaveFailure(error);
    showError(error.message);
  }
}

function cancelTouchDrag() {
  const drag = state.touchDrag;
  if (!drag) return;
  window.clearTimeout(drag.timer);
  if (drag.scrollFrame) window.cancelAnimationFrame(drag.scrollFrame);
  drag.target?.classList.remove("touch-drag-over");
  drag.card.classList.remove("touch-drag-source");
  drag.ghost?.remove();
  document.body.classList.remove("touch-dragging");
  state.touchDrag = null;
}

document.addEventListener("touchmove", moveTouchDrag, { passive: false });
document.addEventListener("touchend", endTouchDrag, { passive: false });
document.addEventListener("touchcancel", cancelTouchDrag);

function openMove(week, workout) {
  state.move = { week, workoutId: workout.id, day: workout.day };
  $("#move-title").textContent = `Move ${workout.name.replace(/^Week \d+\s*-\s*/, "")}`;
  $("#move-week").replaceChildren(...state.program.weeks.map((item) => {
    const option = document.createElement("option");
    option.value = item.week;
    option.textContent = `Week ${item.week}`;
    option.selected = item.week === week;
    return option;
  }));
  $("#move-day").value = workout.day;
  $("#move-dialog").showModal();
}

async function persistMove(fromWeek, workoutId, toWeek, toDay) {
  const source = state.program.weeks.find((week) => week.week === fromWeek)?.workouts.find((workout) => workout.id === workoutId);
  if (!source) throw new Error("Workout no longer exists at its original position.");
  setAppStatus("saving", "Saving move…");
  const updated = await request(`/api/programs/${encodeURIComponent(state.program.file)}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      userId: state.user.id,
      revision: state.program.revision,
      move: { from_week: fromWeek, workout_id: workoutId, to_week: toWeek, to_day: toDay },
    }),
  });
  render(updated);
  state.undoMove = { fromWeek: toWeek, workoutId, toWeek: fromWeek, toDay: source.day };
  updateUndoControl();
}

async function undoLastMove() {
  if (!state.undoMove) return;
  const move = state.undoMove;
  clearUndoMove();
  setAppStatus("saving", "Undoing move…");
  try {
    const source = state.program.weeks.find((week) => week.week === move.fromWeek)?.workouts.find((workout) => workout.id === move.workoutId);
    if (!source) throw new Error("The moved workout is no longer available to undo.");
    const updated = await request(`/api/programs/${encodeURIComponent(state.program.file)}`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId: state.user.id,
        revision: state.program.revision,
        move: { from_week: move.fromWeek, workout_id: move.workoutId, to_week: move.toWeek, to_day: move.toDay },
      }),
    });
    render(updated);
  } catch (error) {
    state.undoMove = move;
    updateUndoControl();
    setSaveFailure(error);
    showError(error.message);
  }
}

async function moveWorkout(toWeek, toDay, cell) {
  cell.classList.remove("drag-over");
  if (!state.dragged || (state.dragged.week === toWeek && state.program.weeks.find(w => w.week === toWeek).workouts.find(w => w.id === state.dragged.workoutId)?.day === toDay)) return;
  try {
    await persistMove(state.dragged.week, state.dragged.workoutId, toWeek, toDay);
  } catch (error) { setSaveFailure(error); showError(error.message); }
}

function openWorkout(week, workout) {
  state.workout = { mode: "edit", week, workoutId: workout.id, name: workout.name };
  $("#workout-title").textContent = workout.name;
  $("#workout-yaml-reference").classList.add("hidden");
  const weekWorkouts = state.program.weeks.find((item) => item.week === week).workouts;
  const onlyWorkout = weekWorkouts.length === 1;
  $("#workout-editor-help").textContent = `The workout ID is stable and cannot be changed. Tracking is editable and affects Garmin sync and actual totals. The complete program is validated before saving.${onlyWorkout ? " This is the week's only workout and cannot be deleted." : ""}`;
  const deleteButton = $("#delete-workout-button");
  deleteButton.classList.remove("hidden");
  deleteButton.disabled = onlyWorkout;
  deleteButton.title = deleteButton.disabled ? "A week must contain at least one workout." : "";
  $("#save-workout-button").textContent = "Validate & save";
  $("#workout-yaml").value = workout.yaml;
  $("#workout-dialog").showModal();
}

function nextWorkoutId(week) {
  const ids = new Set(week.workouts.map((workout) => workout.id));
  let number = 1;
  while (ids.has(`workout-${number}`)) number += 1;
  return `workout-${number}`;
}

function workoutTemplate(week, day) {
  return `id: ${nextWorkoutId(week)}
day: ${day}
name: New workout
description: Describe the purpose and intensity.
steps:
  - warmup: 10m
  - run: 20m
  - cooldown: 5m
`;
}

function openAddWorkout(weekNumber, day) {
  const week = state.program.weeks.find((item) => item.week === weekNumber);
  state.workout = { mode: "add", week: weekNumber };
  $("#workout-title").textContent = `Add workout · Week ${weekNumber}, ${WEEKDAYS[day - 1]}`;
  $("#workout-editor-help").textContent = "Start with the valid template below. You may change every field, including the day, before validation.";
  $("#workout-yaml-reference").classList.remove("hidden");
  $("#delete-workout-button").classList.add("hidden");
  $("#save-workout-button").textContent = "Validate & add";
  $("#workout-yaml").value = workoutTemplate(week, day);
  $("#workout-dialog").showModal();
}

async function saveEdit(payload) {
  clearUndoMove();
  const validatesWorkout = payload.workout || payload.add_workout;
  setAppStatus(validatesWorkout ? "validation" : "saving", validatesWorkout ? "Validating…" : "Saving…");
  const updated = await request(`/api/programs/${encodeURIComponent(state.program.file)}`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ userId: state.user.id, revision: state.program.revision, ...payload })
  });
  render(updated);
}

async function loadPrograms() {
  try {
    const result = await request(`/api/programs?${userQuery()}`);
    const select = $("#program-select");
    select.replaceChildren(...result.programs.map((program) => {
      const option = document.createElement("option"); option.value = program.file; option.textContent = program.name; return option;
    }));
    if (!result.programs.length) {
      showEmptyPrograms();
      return;
    }
    const active = state.user.activeProgram;
    const saved = storedValue(programStorageKey(state.user.id));
    const selected = result.programs.some((program) => program.file === active)
      ? active
      : result.programs.some((program) => program.file === saved)
        ? saved
        : result.programs[0].file;
    await loadProgram(selected);
  } catch (error) { showError(error.message); $("#program-name").textContent = "Programs unavailable"; }
}

async function uploadProgram(file) {
  if (!file) return;
  if (!/\.ya?ml$/i.test(file.name)) {
    showError("Choose a .yaml or .yml file.");
    return;
  }
  try {
    setAppStatus("saving", "Uploading…");
    await request("/api/programs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId: state.user.id,
        filename: file.name,
        content: await file.text(),
      }),
    });
    storeValue(programStorageKey(state.user.id), file.name);
    await loadPrograms();
  } catch (error) {
    if (state.program) setSaveFailure(error);
    showError(error.message);
  } finally {
    $("#program-file-input").value = "";
  }
}

async function loadProgram(file) {
  clearUndoMove();
  const program = await request(`/api/programs/${encodeURIComponent(file)}?${userQuery()}`);
  const active = await request(`/api/users/${encodeURIComponent(state.user.id)}/active-program`, {
    method: "POST", headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename: file }),
  });
  state.user = active.user;
  state.users = state.users.map((user) => user.id === state.user.id ? state.user : user);
  render(program);
  $("#program-select").value = file;
  storeValue(programStorageKey(state.user.id), file);
}

function fillUserSelects() {
  for (const select of [$("#user-select"), $("#user-choice")]) {
    select.replaceChildren(...state.users.map((user) => {
      const option = document.createElement("option");
      option.value = user.id;
      option.textContent = user.name;
      return option;
    }));
  }
}

function showUserDialog(createUser = false) {
  const optional = Boolean(state.user);
  if (createUser) {
    $("#new-username").value = "";
    $("#new-full-name").value = "";
  }
  $("#user-dialog-title").textContent = createUser ? (optional ? "Create another user" : "Create the first user") : "Choose your user";
  $("#user-dialog-help").textContent = createUser
    ? (optional ? "Create a separate profile with its own Garmin credentials and sync state." : "This server has no users yet. Create one to start planning; Garmin credentials can be added before the first sync.")
    : "Your choice and your most recent program are remembered only in this browser.";
  $("#existing-user-fields").classList.toggle("hidden", createUser);
  $("#new-user-fields").classList.toggle("hidden", !createUser);
  $("#user-choice").required = !createUser;
  $("#new-username").required = createUser;
  $("#new-full-name").required = createUser;
  $("#user-submit").textContent = createUser ? "Create user" : "Continue";
  $("#user-cancel").classList.toggle("hidden", !optional);
  $("#user-dialog").dataset.mode = createUser ? "create" : "select";
  $("#user-dialog").showModal();
}

async function selectUser(userId, persist = true) {
  const user = state.users.find((candidate) => candidate.id === userId);
  if (!user) throw new Error("The selected Runplan user is no longer available.");
  state.user = user;
  state.program = null;
  $("#user-select").value = user.id;
  if (persist) storeValue(USER_STORAGE_KEY, user.id);
  await loadPrograms();
}

async function initialize() {
  try {
    const result = await request("/api/users");
    state.users = result.users || [];
    fillUserSelects();
    if (!state.users.length) {
      showUserDialog(true);
      return;
    }
    const saved = storedValue(USER_STORAGE_KEY);
    if (state.users.some((user) => user.id === saved)) {
      await selectUser(saved, false);
    } else {
      showUserDialog(false);
    }
  } catch (error) {
    showError(error.message);
    $("#program-name").textContent = "Runplan unavailable";
  }
}

$("#program-select").addEventListener("change", (event) => {
  setMobileMenu(false, false);
  loadProgram(event.target.value).catch(error => showError(error.message));
});
for (const selector of ["#upload-program-button", "#empty-upload-program-button"]) {
  $(selector).addEventListener("click", () => $("#program-file-input").click());
}
$("#program-file-input").addEventListener("change", (event) => {
  uploadProgram(event.target.files[0]);
});
$("#user-select").addEventListener("change", (event) => {
  setMobileMenu(false, false);
  selectUser(event.target.value).catch(error => showError(error.message));
});
$("#add-user-button").addEventListener("click", () => showUserDialog(true));
$("#user-cancel").addEventListener("click", () => $("#user-dialog").close());
$("#user-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    if ($("#user-dialog").dataset.mode === "create") {
      const result = await request("/api/users", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          username: $("#new-username").value,
          fullName: $("#new-full-name").value,
        }),
      });
      state.users.push(result.user);
      fillUserSelects();
      await selectUser(result.user.id);
    } else {
      await selectUser($("#user-choice").value);
    }
    $("#user-dialog").close();
  } catch (error) { showError(error.message); }
});
$("#user-dialog").addEventListener("cancel", (event) => {
  if (!state.user) event.preventDefault();
});
$("#settings-button").addEventListener("click", () => {
  $("#settings-name").value = state.program.program.name;
  $("#settings-short-name").value = state.program.program.short_name;
  $("#settings-description").value = state.program.program.description || "";
  $("#settings-start-week").value = state.program.program.start_week;
  $("#settings-dialog").showModal();
});
$("#user-settings-button").addEventListener("click", async () => {
  try {
    const settings = await request(`/api/users/${encodeURIComponent(state.user.id)}/settings`);
    $("#user-settings-username").value = settings.id;
    $("#user-settings-full-name").value = settings.fullName;
    $("#user-settings-default-pace").value = settings.defaultPace;
    $("#user-settings-garmin-email").value = settings.garminEmail;
    $("#user-settings-garmin-password").value = "";
    $("#user-settings-garmin-password").required = !settings.hasGarminPassword;
    $("#user-settings-password-help").textContent = settings.hasGarminPassword
      ? "A password is saved. Leave blank to keep it."
      : "No password is saved yet.";
    $("#user-settings-dialog").showModal();
  } catch (error) { showError(error.message); }
});
$("#sync-button").addEventListener("click", syncGarmin);
$("#undo-move").addEventListener("click", undoLastMove);
document.querySelectorAll("dialog .close").forEach(button => button.addEventListener("click", () => button.closest("dialog").close()));
$("#settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try { await saveEdit({ program: { name: $("#settings-name").value, short_name: $("#settings-short-name").value, description: $("#settings-description").value || null, start_week: $("#settings-start-week").value } }); $("#settings-dialog").close(); }
  catch (error) { setSaveFailure(error); showError(error.message); }
});
$("#user-settings-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    const result = await request(`/api/users/${encodeURIComponent(state.user.id)}/settings`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        fullName: $("#user-settings-full-name").value,
        defaultPace: $("#user-settings-default-pace").value,
        garminEmail: $("#user-settings-garmin-email").value,
        garminPassword: $("#user-settings-garmin-password").value,
      }),
    });
    state.users = state.users.map((user) => user.id === result.user.id ? result.user : user);
    state.user = result.user;
    fillUserSelects();
    $("#user-select").value = state.user.id;
    $("#user-settings-dialog").close();
    if (state.program) await loadProgram(state.program.file);
  } catch (error) { showError(error.message); }
});
$("#workout-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const change = state.workout.mode === "add"
    ? { add_workout: { week: state.workout.week, yaml: $("#workout-yaml").value } }
    : { workout: { week: state.workout.week, workout_id: state.workout.workoutId, yaml: $("#workout-yaml").value } };
  try { await saveEdit(change); $("#workout-dialog").close(); }
  catch (error) { setSaveFailure(error); showError(error.message); }
});

$("#delete-workout-button").addEventListener("click", () => {
  $("#delete-workout-title").textContent = `Delete ${state.workout.name}?`;
  $("#delete-workout-message").textContent = "This removes the workout from the plan. If it was synchronized, its Garmin schedule and workout will be removed during the next reviewed and confirmed sync.";
  $("#delete-workout-dialog").showModal();
});

$("#delete-workout-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  try {
    await saveEdit({
      delete_workout: { week: state.workout.week, workout_id: state.workout.workoutId },
    });
    $("#delete-workout-dialog").close();
    $("#workout-dialog").close();
  } catch (error) { setSaveFailure(error); showError(error.message); }
});
$("#move-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  if (!state.move) return;
  const toWeek = Number($("#move-week").value);
  const toDay = Number($("#move-day").value);
  if (state.move.week === toWeek && state.move.day === toDay) {
    $("#move-dialog").close();
    return;
  }
  try {
    await persistMove(state.move.week, state.move.workoutId, toWeek, toDay);
    $("#move-dialog").close();
    state.move = null;
  } catch (error) {
    setSaveFailure(error);
    showError(error.message);
  }
});
$("#export-button").addEventListener("click", () => $("#export-options").classList.toggle("hidden"));
document.querySelectorAll("[data-export]").forEach(link => link.addEventListener("click", () => {
  window.location.href = `/api/programs/${encodeURIComponent(state.program.file)}/export?format=${link.dataset.export}&${userQuery()}`;
  $("#export-options").classList.add("hidden");
  setMobileMenu(false, false);
}));

$("#auth-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const password = $("#auth-password");
  const submit = $("#auth-submit");
  submit.disabled = true;
  try {
    const enteredPassword = password.value;
    password.value = "";
    const challenge = await request("/api/auth/challenge");
    const proof = await passwordProof(enteredPassword, challenge);
    await request("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ challengeId: challenge.challengeId, proof }),
    });
    await initializeAuthentication();
  } catch (error) {
    password.value = "";
    showLogin(error.message);
  } finally {
    submit.disabled = false;
  }
});

initializeAuthentication();
