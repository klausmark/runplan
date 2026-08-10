const state = { users: [], user: null, program: null, pointerDrag: null, workout: null, move: null, undoMove: null };
const $ = (selector) => document.querySelector(selector);
const MOVE_THRESHOLD = 6;
const TOUCH_LONG_PRESS_MS = 350;
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

function normalizePaceSide(side) {
  const trimmed = side.trim();
  if (/^\d+$/.test(trimmed)) return `${parseInt(trimmed, 10)}:00`;
  if (/^\d+:[0-5]\d$/.test(trimmed)) return trimmed;
  if (/^\d+(?:\.\d+)?$/.test(trimmed)) {
    const totalSec = Math.round(parseFloat(trimmed) * 60);
    const m = Math.floor(totalSec / 60);
    const s = totalSec % 60;
    return `${m}:${String(s).padStart(2, "0")}`;
  }
  return null;
}

function normalizePaceInput(raw) {
  const text = (raw || "").trim();
  if (!text) return null;
  const stripped = text.replace(/\s*min\s*\/\s*km\s*$/i, "").trim();
  const parts = stripped.split(/\s*-\s*/).map(normalizePaceSide);
  if (parts.some((p) => p === null)) return null;
  for (const part of parts) {
    const [mm, ss] = part.split(":").map((n) => parseInt(n, 10));
    if (ss >= 60 || mm <= 0) return null;
  }
  return `${parts.join("-")} min/km`;
}

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
  if (state.undoMove && !canMoveRequest(state.undoMove.fromWeek, state.undoMove.workoutId, state.undoMove.toWeek, state.undoMove.toDay)) {
    state.undoMove = null;
  }
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
  $("#coaching-guide").classList.add("hidden");
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

const SYNC_ACTION_LABELS = {
  create: "Create workout",
  schedule: "Schedule workout",
  reuse: "Reuse workout",
  update: "Replace workout",
  unschedule: "Unschedule old workout",
  delete: "Delete old workout",
  missed: "Mark as missed",
  completed: "Completed",
  retired: "Retired",
};

function describeSyncAction(action) {
  const base = SYNC_ACTION_LABELS[action.kind] || action.kind;
  if (action.date) return `${base} on ${action.date}`;
  return base;
}

function summarizeSyncActions(actions) {
  const counts = Object.create(null);
  for (const action of actions) {
    counts[action.kind] = (counts[action.kind] || 0) + 1;
  }
  return counts;
}

function renderSyncPreview(preview) {
  const summary = $("#sync-preview-summary");
  summary.innerHTML = "";
  const actions = preview?.plan?.actions ?? [];
  const counts = summarizeSyncActions(actions);
  const order = ["create", "schedule", "reuse", "update", "unschedule", "delete", "missed"];
  const summaryItems = order
    .filter((kind) => counts[kind])
    .map((kind) => `${counts[kind]} ${SYNC_ACTION_LABELS[kind].toLowerCase()}${counts[kind] > 1 ? "s" : ""}`);
  if (summaryItems.length === 0) summaryItems.push("No changes");
  for (const text of summaryItems) {
    const item = document.createElement("li");
    item.textContent = text;
    summary.appendChild(item);
  }

  const warning = $("#sync-preview-warning");
  const destructiveCount = (counts.delete || 0) + (counts.unschedule || 0);
  if (destructiveCount > 0) {
    warning.textContent = `This sync will remove ${destructiveCount} previously created Garmin workout${destructiveCount > 1 ? "s" : ""}.`;
    warning.classList.remove("hidden");
  } else {
    warning.classList.add("hidden");
    warning.textContent = "";
  }

  const list = $("#sync-preview-actions");
  list.innerHTML = "";
  for (const action of actions) {
    const item = document.createElement("li");
    item.textContent = describeSyncAction(action);
    list.appendChild(item);
  }
  $("#sync-preview-details").open = false;
}

async function syncGarmin() {
  const button = $("#sync-button");
  const file = state.program.file;
  const userId = state.user.id;
  setMobileMenu(false, false);
  window.clearTimeout(syncButtonResetTimer);
  button.disabled = true;
  button.textContent = "Checking…";
  setAppStatus("garmin", "Checking Garmin…");
  let preview;
  try {
    preview = await request(
      `/api/programs/${encodeURIComponent(file)}/sync/preview?user=${encodeURIComponent(userId)}`
    );
  } catch (error) {
    showError(error.message);
    button.textContent = "Sync Garmin";
    button.disabled = false;
    setAppStatus("failed", "Garmin sync failed");
    return;
  }
  renderSyncPreview(preview);
  const dialog = $("#sync-preview-dialog");
  const confirmButton = $("#sync-preview-confirm");
  const cancelButton = $("#sync-preview-cancel");
  const closeHandler = (event) => {
    if (event.target !== confirmButton && event.target !== cancelButton) return;
    dialog.close(event.target === confirmButton ? "confirm" : "cancel");
  };
  dialog.addEventListener("click", closeHandler);
  let result;
  try {
    result = await new Promise((resolve) => {
      dialog.showModal();
      dialog.addEventListener(
        "close",
        () => {
          resolve(dialog.returnValue === "confirm" ? preview : null);
        },
        { once: true },
      );
    });
  } finally {
    dialog.removeEventListener("click", closeHandler);
  }
  if (!result) {
    button.textContent = "Sync Garmin";
    button.disabled = false;
    setAppStatus("idle", "Sync cancelled");
    return;
  }
  button.textContent = "Syncing…";
  setAppStatus("garmin", "Syncing Garmin…");
  try {
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
  cancelPointerDrag();
  state.program = program;
  showProgramControls();
  $("#program-name").textContent = program.program.name;
  $("#program-description").textContent = program.program.description || "No program description";
  renderCoachingGuide(program.program.coaching);
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
      cell.dataset.moveLocked = String(workout?.can_move === false);
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
  card.classList.toggle("workout-locked", !workout.can_move);
  card.dataset.moveable = String(workout.can_move);
  const header = document.createElement("div");
  header.className = "workout-header";
  const content = document.createElement("div");
  content.className = "workout-content";
  content.setAttribute("role", "button");
  content.tabIndex = 0;
  content.setAttribute("aria-label", `${workout.name}. Click to edit.`);
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
  if (workout.can_move) {
    const handle = document.createElement("button");
    handle.className = "workout-drag-handle";
    handle.type = "button";
    handle.textContent = "⠿";
    handle.title = "Hold and drag to move, or tap to choose a day";
    handle.setAttribute("aria-label", `Move ${workout.name}`);
    handle.addEventListener("pointerdown", (event) => beginPointerDrag(event, card, handle, week, workout));
    handle.addEventListener("contextmenu", (event) => event.preventDefault());
    handle.addEventListener("click", (event) => {
      event.stopPropagation();
      if (handle.dataset.suppressClick === "true") {
        delete handle.dataset.suppressClick;
        return;
      }
      openMove(week, workout);
    });
    header.append(handle);
  }
  content.addEventListener("click", () => {
    openWorkout(week, workout);
  });
  content.addEventListener("keydown", (event) => {
    if (event.key === "Enter" || event.key === " ") {
      event.preventDefault();
      openWorkout(week, workout);
    }
  });
  header.prepend(status);
  content.append(title, summary, description);
  card.append(header, content);
  return card;
}

function activityLinkUrl() {
  const workout = state.workout;
  return `/api/programs/${encodeURIComponent(state.program.file)}/workouts/${workout.week}/${encodeURIComponent(workout.workoutId)}/activities?${userQuery()}`;
}

function selectedActivityIds() {
  return Array.from(
    $("#activity-list").querySelectorAll('input[type="checkbox"]:checked'),
    input => Number(input.value),
  ).sort((left, right) => left - right);
}

function clearChildren(node) {
  while (node.firstChild) node.removeChild(node.firstChild);
}

function appendStepLine(list, parts) {
  const line = document.createElement("span");
  parts.forEach(part => line.appendChild(typeof part === "string" ? document.createTextNode(part) : part));
  const item = document.createElement("li");
  item.className = "workout-step";
  item.appendChild(line);
  list.appendChild(item);
  return item;
}

function renderStepList(steps, list) {
  steps.forEach(step => {
    if (step.action === "repeat") {
      const item = document.createElement("li");
      item.className = "workout-step-repeat";
      const summary = document.createElement("strong");
      summary.textContent = `Repeat ${step.count} times`;
      item.appendChild(summary);
      const nested = document.createElement("ol");
      nested.className = "workout-steps";
      item.appendChild(nested);
      list.appendChild(item);
      renderStepList(step.steps, nested);
      return;
    }
    const parts = [
      `${step.kind_label}: `,
      document.createTextNode(step.end_value_display),
    ];
    if (step.pace_display) {
      const pace = document.createElement("span");
      pace.className = "workout-step-pace";
      pace.textContent = ` @ ${step.pace_display}`;
      parts.push(pace);
    }
    const item = appendStepLine(list, parts);
    if (step.note) {
      const note = document.createElement("p");
      note.className = "workout-step-note";
      note.textContent = `Note: ${step.note}`;
      item.appendChild(note);
    }
  });
}

function renderCoachingGuide(guide) {
  const section = $("#coaching-guide");
  const body = $("#coaching-body");
  const eyebrow = $("#coaching-eyebrow");
  if (!guide || !_coachingHasContent(guide)) {
    section.classList.add("hidden");
    body.replaceChildren();
    return;
  }
  eyebrow.textContent = guide.tagline || "Read before you start";
  body.replaceChildren(..._coachingSections(guide));
  section.classList.remove("hidden");
}

function _coachingHasContent(guide) {
  return Boolean(
    guide.tagline ||
      (guide.introSections && guide.introSections.length) ||
      (guide.weeklyWorkouts && guide.weeklyWorkouts.length) ||
      (guide.planTips && guide.planTips.length) ||
      guide.paceChart ||
      (guide.glossary && guide.glossary.length) ||
      (guide.paceTypes && guide.paceTypes.length) ||
      (guide.thingsToKnow && guide.thingsToKnow.length) ||
      (guide.situationalAdvice && guide.situationalAdvice.length)
  );
}

function _coachingSections(guide) {
  const sections = [];
  for (const item of guide.introSections || []) sections.push(_coachingTextSection(item.title, item.body));
  for (const item of guide.weeklyWorkouts || []) sections.push(_coachingTextSection(item.title, item.body));
  for (const item of guide.planTips || []) sections.push(_coachingTipSection(item));
  if (guide.paceChart) sections.push(_coachingPaceChartSection(guide.paceChart));
  if ((guide.glossary || []).length) {
    sections.push(_coachingGlossarySection("Types of Runs", guide.glossary));
  }
  if ((guide.paceTypes || []).length) {
    sections.push(_coachingPaceTypesSection(guide.paceTypes));
  }
  if ((guide.thingsToKnow || []).length) {
    sections.push(_coachingBulletSection("Things to Know", guide.thingsToKnow));
  }
  if ((guide.situationalAdvice || []).length) {
    sections.push(_coachingSituationalSection(guide.situationalAdvice));
  }
  return sections;
}

function _coachingTextSection(title, body) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const paragraph = document.createElement("p");
  paragraph.textContent = body;
  section.append(heading, paragraph);
  return section;
}

function _coachingTipSection(item) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = item.title;
  section.append(heading);
  if (item.items && item.items.length) {
    const list = document.createElement("ul");
    for (const line of item.items) {
      const li = document.createElement("li");
      li.textContent = line;
      list.append(li);
    }
    section.append(list);
  } else if (item.body) {
    const paragraph = document.createElement("p");
    paragraph.textContent = item.body;
    section.append(paragraph);
  }
  return section;
}

function _coachingPaceChartSection(chart) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = chart.title;
  section.append(heading);
  if (chart.intro) {
    const intro = document.createElement("p");
    intro.textContent = chart.intro;
    section.append(intro);
  }
  const table = document.createElement("table");
  table.className = "coaching-pace-chart";
  const thead = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const col of chart.headers) {
    const th = document.createElement("th");
    th.textContent = col.label;
    headRow.append(th);
  }
  thead.append(headRow);
  table.append(thead);
  const tbody = document.createElement("tbody");
  for (const row of chart.rows) {
    const tr = document.createElement("tr");
    for (const cell of row) {
      const td = document.createElement("td");
      td.textContent = cell;
      tr.append(td);
    }
    tbody.append(tr);
  }
  table.append(tbody);
  section.append(table);
  if (chart.headers && chart.headers.length) {
    const descriptions = document.createElement("ul");
    for (const col of chart.headers) {
      const li = document.createElement("li");
      li.textContent = `${col.label} — ${col.description}`;
      descriptions.append(li);
    }
    section.append(descriptions);
  }
  if (chart.examples && chart.examples.length) {
    for (const example of chart.examples) {
      const card = document.createElement("div");
      card.className = "coaching-example";
      const title = document.createElement("strong");
      title.textContent = example.title;
      card.append(title);
      const list = document.createElement("ul");
      for (const target of example.targets) {
        const li = document.createElement("li");
        li.textContent = target;
        list.append(li);
      }
      card.append(list);
      section.append(card);
    }
  }
  return section;
}

function _coachingGlossarySection(title, items) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    const term = document.createElement("strong");
    term.textContent = `${item.term} — `;
    li.append(term, document.createTextNode(item.definition));
    list.append(li);
  }
  section.append(list);
  return section;
}

function _coachingPaceTypesSection(items) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = "Types of Pace";
  section.append(heading);
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    const name = document.createElement("strong");
    name.textContent = `${item.name} (${item.effort}) — `;
    li.append(name, document.createTextNode(item.description));
    list.append(li);
  }
  section.append(list);
  return section;
}

function _coachingBulletSection(title, items) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = title;
  section.append(heading);
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    li.textContent = item;
    list.append(li);
  }
  section.append(list);
  return section;
}

function _coachingSituationalSection(items) {
  const section = document.createElement("section");
  section.className = "coaching-section";
  const heading = document.createElement("h3");
  heading.textContent = "If You...";
  section.append(heading);
  const list = document.createElement("ul");
  for (const item of items) {
    const li = document.createElement("li");
    const title = document.createElement("strong");
    title.textContent = `${item.title} — `;
    li.append(title, document.createTextNode(item.body));
    list.append(li);
  }
  section.append(list);
  return section;
}

function renderWorkoutSteps(steps) {
  const container = $("#workout-steps");
  clearChildren(container);
  if (!Array.isArray(steps) || steps.length === 0) {
    const empty = document.createElement("li");
    empty.className = "workout-step-empty";
    empty.textContent = "No steps yet.";
    container.appendChild(empty);
    return;
  }
  renderStepList(steps, container);
}

function setWorkoutOverview(steps) {
  const overview = $("#workout-overview");
  const help = $("#workout-overview-help");
  if (Array.isArray(steps) && steps.length > 0) {
    renderWorkoutSteps(steps);
    help.textContent = "The steps are part of the saved workout. Edit them in the YAML editor below.";
    overview.classList.remove("hidden");
  } else {
    clearChildren($("#workout-steps"));
    help.textContent = "";
    overview.classList.add("hidden");
  }
}

function updateWorkoutActions() {
  if (!state.workout) return;
  const yamlChanged = $("#workout-yaml").value !== state.workout.originalYaml;
  const activitiesChanged = Array.isArray(state.workout.activityIds)
    && selectedActivityIds().join(",") !== state.workout.activityIds.join(",");
  $("#save-workout-button").disabled = activitiesChanged;
  $("#activity-apply").disabled = yamlChanged || !activitiesChanged;
}

async function loadActivityCandidates() {
  const workout = state.workout;
  const list = $("#activity-list");
  list.setAttribute("aria-busy", "true");
  list.replaceChildren(Object.assign(document.createElement("p"), { textContent: "Loading Garmin activities…" }));
  try {
    const result = await request(activityLinkUrl());
    if (state.workout !== workout || workout.mode !== "edit") return;
    list.replaceChildren();
    if (!result.activities.length) {
      list.append(Object.assign(document.createElement("p"), {
        className: "activity-empty",
        textContent: "No running activities found on this date.",
      }));
    }
    for (const activity of result.activities) {
      const item = document.createElement("label");
      item.className = "activity-candidate activity-choice";
      const checkbox = document.createElement("input");
      checkbox.type = "checkbox";
      checkbox.value = activity.id;
      checkbox.checked = activity.selected;
      checkbox.addEventListener("change", updateWorkoutActions);
      const details = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = activity.name;
      const summary = document.createElement("span");
      const time = new Intl.DateTimeFormat("en", { dateStyle: "medium", timeStyle: "short" }).format(new Date(activity.startTimeLocal));
      summary.textContent = `${time} · ${distanceLabel(activity.distanceMeters)} · ${durationLabel(activity.durationSeconds)}`;
      details.append(title, summary);
      if (activity.linkSource) {
        const source = document.createElement("small");
        source.textContent = `${activity.linkSource === "automatic" ? "Automatically" : "Manually"} linked`;
        details.append(source);
      }
      item.append(checkbox, details);
      list.append(item);
    }
    state.workout.activityIds = result.activities
      .filter(activity => activity.selected)
      .map(activity => activity.id)
      .sort((left, right) => left - right);
    updateWorkoutActions();
  } catch (error) {
    list.replaceChildren(Object.assign(document.createElement("p"), { className: "sync-error", textContent: error.message }));
    $("#activity-apply").disabled = true;
  } finally {
    list.removeAttribute("aria-busy");
  }
}

async function applyActivityLinks() {
  const button = $("#activity-apply");
  button.disabled = true;
  try {
    const workout = state.workout;
    const activityIds = selectedActivityIds();
    const updated = await request(`/api/programs/${encodeURIComponent(state.program.file)}/workouts/${workout.week}/${encodeURIComponent(workout.workoutId)}/activity-links`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ userId: state.user.id, revision: state.program.revision, activityIds }),
    });
    render(updated);
    if (state.workout !== workout) return;
    const refreshed = updated.weeks
      .find(item => item.week === workout.week).workouts
      .find(item => item.id === workout.workoutId);
    state.workout.name = refreshed.name;
    state.workout.originalYaml = refreshed.yaml;
    $("#workout-yaml").value = refreshed.yaml;
    setWorkoutOverview(refreshed.steps);
    await loadActivityCandidates();
  } catch (error) {
    updateWorkoutActions();
    showError(error.message);
  }
}

function beginPointerDrag(event, card, handle, week, workout) {
  if (!event.isPrimary) return;
  if (event.button !== undefined && event.button !== 0) return;
  cancelPointerDrag();
  const isTouch = event.pointerType !== "mouse";
  state.pointerDrag = {
    pointerId: event.pointerId,
    card,
    handle,
    week,
    workoutId: workout.id,
    day: workout.day,
    startX: event.clientX,
    startY: event.clientY,
    x: event.clientX,
    y: event.clientY,
    isTouch,
    started: false,
    target: null,
    ghost: null,
    scrollFrame: null,
    timer: null,
  };
  if (isTouch) {
    state.pointerDrag.timer = window.setTimeout(activatePointerDrag, TOUCH_LONG_PRESS_MS);
  }
}

function activatePointerDrag() {
  const drag = state.pointerDrag;
  if (!drag) return;
  window.clearTimeout(drag.timer);
  drag.timer = null;
  const bounds = drag.card.getBoundingClientRect();
  const ghost = drag.card.cloneNode(true);
  ghost.className = "workout touch-drag-ghost";
  ghost.style.width = `${bounds.width}px`;
  drag.offsetX = drag.startX - bounds.left;
  drag.offsetY = drag.startY - bounds.top;
  drag.ghost = ghost;
  drag.started = true;
  drag.card.classList.add("touch-drag-source");
  document.body.classList.add("touch-dragging");
  document.body.append(ghost);
  positionPointerGhost(drag.x, drag.y);
  updatePointerTarget(drag.x, drag.y);
  drag.scrollFrame = window.requestAnimationFrame(autoScrollPointerDrag);
  try { drag.handle.setPointerCapture(drag.pointerId); } catch (_) {}
  navigator.vibrate?.(25);
}

function positionPointerGhost(x, y) {
  const drag = state.pointerDrag;
  if (!drag?.ghost) return;
  drag.ghost.style.transform = `translate3d(${x - drag.offsetX}px, ${y - drag.offsetY}px, 0)`;
}

function updatePointerTarget(x, y) {
  const drag = state.pointerDrag;
  if (!drag?.started) return;
  const candidate = document.elementFromPoint(x, y)?.closest(".day") || null;
  const target = candidate?.dataset.moveLocked === "true" ? null : candidate;
  if (target === drag.target) return;
  drag.target?.classList.remove("touch-drag-over");
  drag.target = target;
  drag.target?.classList.add("touch-drag-over");
}

function autoScrollPointerDrag() {
  const drag = state.pointerDrag;
  if (!drag?.started) return;
  const edge = 72;
  const speed = drag.y < edge ? -10 : drag.y > window.innerHeight - edge ? 10 : 0;
  if (speed) {
    window.scrollBy(0, speed);
    updatePointerTarget(drag.x, drag.y);
  }
  drag.scrollFrame = window.requestAnimationFrame(autoScrollPointerDrag);
}

function movePointerDrag(event) {
  const drag = state.pointerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  drag.x = event.clientX;
  drag.y = event.clientY;
  if (!drag.started) {
    const moved = Math.hypot(event.clientX - drag.startX, event.clientY - drag.startY);
    if (drag.isTouch) {
      if (moved > TOUCH_CANCEL_DISTANCE) cancelPointerDrag();
      return;
    }
    if (moved > MOVE_THRESHOLD) activatePointerDrag();
    return;
  }
  event.preventDefault();
  positionPointerGhost(event.clientX, event.clientY);
  updatePointerTarget(event.clientX, event.clientY);
}

async function endPointerDrag(event) {
  const drag = state.pointerDrag;
  if (!drag || drag.pointerId !== event.pointerId) return;
  if (!drag.started) {
    cancelPointerDrag();
    return;
  }
  event.preventDefault();
  const target = drag.target;
  const fromWeek = drag.week;
  const workoutId = drag.workoutId;
  const sameDay = target && Number(target.dataset.week) === drag.week && Number(target.dataset.day) === drag.day;
  // Suppress the click event that the browser fires after pointerup so the
  // card does not open its edit dialog when the user finishes a drag. Only
  // suppress when the pointer actually travelled, so a long-press followed
  // by a release without movement still opens the edit dialog.
  const threshold = drag.isTouch ? TOUCH_CANCEL_DISTANCE : MOVE_THRESHOLD;
  const moved = Math.hypot(drag.x - drag.startX, drag.y - drag.startY) > threshold;
  if (moved) drag.handle.dataset.suppressClick = "true";
  cancelPointerDrag();
  if (!target || sameDay) return;
  try {
    await persistMove(fromWeek, workoutId, Number(target.dataset.week), Number(target.dataset.day));
  } catch (error) {
    setSaveFailure(error);
    showError(error.message);
  }
}

function cancelPointerDrag() {
  const drag = state.pointerDrag;
  if (!drag) return;
  if (drag.timer !== null) window.clearTimeout(drag.timer);
  if (drag.scrollFrame) window.cancelAnimationFrame(drag.scrollFrame);
  drag.target?.classList.remove("touch-drag-over");
  drag.card.classList.remove("touch-drag-source");
  drag.ghost?.remove();
  document.body.classList.remove("touch-dragging");
  try { drag.handle.releasePointerCapture(drag.pointerId); } catch (_) {}
  state.pointerDrag = null;
}

function openMove(week, workout) {
  if (!workout.can_move) return;
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
  updateMoveDayOptions(week);
  $("#move-dialog").showModal();
}

function updateMoveDayOptions(weekNumber) {
  const selectedWeek = state.program.weeks.find((week) => week.week === weekNumber);
  const daySelect = $("#move-day");
  for (const option of daySelect.options) {
    const occupant = selectedWeek?.workouts.find((workout) => workout.day === Number(option.value));
    option.disabled = occupant?.can_move === false;
  }
  if (daySelect.selectedOptions[0]?.disabled) {
    const available = Array.from(daySelect.options).find((option) => !option.disabled);
    if (available) daySelect.value = available.value;
  }
}

document.addEventListener("pointermove", movePointerDrag, { passive: false });
document.addEventListener("pointerup", endPointerDrag, { passive: false });
document.addEventListener("pointercancel", cancelPointerDrag);

function canMoveRequest(fromWeek, workoutId, toWeek, toDay) {
  const source = state.program?.weeks.find((week) => week.week === fromWeek)?.workouts.find((workout) => workout.id === workoutId);
  if (!source?.can_move) return false;
  const target = state.program.weeks.find((week) => week.week === toWeek)?.workouts.find((workout) => workout.day === toDay);
  return !target || (toWeek === fromWeek && target.id === source.id) || target.can_move;
}

async function persistMove(fromWeek, workoutId, toWeek, toDay) {
  const source = state.program.weeks.find((week) => week.week === fromWeek)?.workouts.find((workout) => workout.id === workoutId);
  if (!source) throw new Error("Workout no longer exists at its original position.");
  if (!canMoveRequest(fromWeek, workoutId, toWeek, toDay)) {
    throw new Error("Completed workouts can only be moved by editing YAML directly.");
  }
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

function openWorkout(week, workout) {
  state.workout = { mode: "edit", week, workoutId: workout.id, name: workout.name, originalYaml: workout.yaml, activityIds: null };
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
  $("#save-workout-button").disabled = false;
  setWorkoutOverview(workout.steps);
  const activities = $("#workout-activities");
  activities.classList.toggle("hidden", !workout.can_manage_activities);
  $("#workout-yaml-details").open = false;
  if (workout.can_manage_activities) {
    $("#workout-activities-help").textContent = `Select every Garmin run from ${dateLabel(workout.date)} that belongs to this workout. Save YAML changes separately.`;
    $("#activity-apply").disabled = true;
    loadActivityCandidates();
  }
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
  $("#workout-activities").classList.add("hidden");
  setWorkoutOverview(null);
  $("#workout-yaml-details").open = true;
  $("#save-workout-button").textContent = "Validate & add";
  $("#save-workout-button").disabled = false;
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
    await activateProgram(file.name);
    $("#add-program-dialog").close();
  } catch (error) {
    if (state.program) setSaveFailure(error);
    showError(error.message);
  } finally {
    $("#program-file-input").value = "";
  }
}

async function activateProgram(filename) {
  storeValue(programStorageKey(state.user.id), filename);
  await request(`/api/users/${encodeURIComponent(state.user.id)}/active-program`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ filename }),
  });
  state.user = { ...state.user, activeProgram: filename };
  await loadPrograms();
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
$("#empty-upload-program-button").addEventListener("click", () => openAddProgramDialog("upload"));
$("#empty-browse-templates-button").addEventListener("click", () => openAddProgramDialog("templates"));
$("#program-file-input").addEventListener("change", (event) => {
  uploadProgram(event.target.files[0]);
});

function closeAddProgramMenu() {
  $("#add-program-menu").classList.add("hidden");
  $("#add-program-button").setAttribute("aria-expanded", "false");
  $("#add-program-toggle").setAttribute("aria-expanded", "false");
}

function toggleAddProgramMenu(force) {
  const menu = $("#add-program-menu");
  const willOpen = force ?? menu.classList.contains("hidden");
  menu.classList.toggle("hidden", !willOpen);
  $("#add-program-button").setAttribute("aria-expanded", String(willOpen));
  $("#add-program-toggle").setAttribute("aria-expanded", String(willOpen));
}

$("#add-program-button").addEventListener("click", () => openAddProgramDialog("templates"));
$("#add-program-toggle").addEventListener("click", (event) => {
  event.stopPropagation();
  toggleAddProgramMenu();
});
document.addEventListener("click", (event) => {
  const menu = $("#add-program-menu");
  if (menu.classList.contains("hidden")) return;
  if (event.target.closest(".split-button")) return;
  closeAddProgramMenu();
});
document.addEventListener("keydown", (event) => {
  if (event.key === "Escape" && !$("#add-program-menu").classList.contains("hidden")) {
    closeAddProgramMenu();
  }
});
document.querySelectorAll("[data-add-action]").forEach((button) => {
  button.addEventListener("click", () => {
    const action = button.dataset.addAction;
    closeAddProgramMenu();
    setMobileMenu(false, false);
    openAddProgramDialog(action);
  });
});

function openAddProgramDialog(tab = "upload") {
  const dialog = $("#add-program-dialog");
  switchAddProgramTab(tab);
  dialog.showModal();
}

function switchAddProgramTab(tab) {
  const tabs = document.querySelectorAll("#add-program-dialog [data-tab]");
  tabs.forEach((button) => {
    const selected = button.dataset.tab === tab;
    button.setAttribute("aria-selected", String(selected));
  });
  for (const section of document.querySelectorAll("#add-program-dialog .add-program-tab")) {
    section.classList.toggle("hidden", section.dataset.tab !== tab);
  }
  if (tab === "templates") loadTemplatesList();
}

document.querySelectorAll('#add-program-dialog [role="tab"]').forEach((button) => {
  button.addEventListener("click", () => switchAddProgramTab(button.dataset.tab));
});
$("#add-program-upload-button").addEventListener("click", () => $("#program-file-input").click());
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
    $("#user-settings-default-pace").value = normalizePaceInput(settings.defaultPace) ?? settings.defaultPace;
    $("#user-settings-garmin-email").value = settings.garminEmail;
    $("#user-settings-garmin-password").value = "";
    $("#user-settings-garmin-password").required = false;
    $("#user-settings-garmin-email").required = false;
    $("#user-settings-password-help").textContent = settings.hasGarminPassword
      ? "A password is saved. Leave blank to keep it. Optional."
      : "Leave blank if you do not want to set up Garmin credentials right now. Optional.";
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
$("#user-settings-default-pace").addEventListener("blur", (event) => {
  const normalized = normalizePaceInput(event.target.value);
  if (normalized !== null) event.target.value = normalized;
});
$("#workout-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const change = state.workout.mode === "add"
    ? { add_workout: { week: state.workout.week, yaml: $("#workout-yaml").value } }
    : { workout: { week: state.workout.week, workout_id: state.workout.workoutId, yaml: $("#workout-yaml").value } };
  try { await saveEdit(change); $("#workout-dialog").close(); }
  catch (error) { setSaveFailure(error); showError(error.message); }
});
$("#workout-yaml").addEventListener("input", updateWorkoutActions);
$("#activity-apply").addEventListener("click", applyActivityLinks);
$("#workout-dialog").addEventListener("close", () => { state.workout = null; });

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
  } catch (error) {
    setSaveFailure(error);
    showError(error.message);
  }
});
$("#move-week").addEventListener("change", (event) => {
  updateMoveDayOptions(Number(event.target.value));
});
$("#move-dialog").addEventListener("close", () => { state.move = null; });

$("#delete-program-button").addEventListener("click", () => {
  $("#delete-program-title").textContent = `Delete ${state.program.program.name}?`;
  $("#delete-program-message").textContent = "This permanently removes the YAML file, all local sync state, and any Garmin schedules and workouts that were created from this plan.";
  $("#settings-dialog").close();
  $("#delete-program-dialog").showModal();
});

$("#delete-program-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const button = $("#delete-program-confirm");
  button.disabled = true;
  try {
    await request(`/api/programs/${encodeURIComponent(state.program.file)}?${userQuery()}`, { method: "DELETE" });
    $("#delete-program-dialog").close();
    state.program = null;
    await loadPrograms();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
});
$("#export-button").addEventListener("click", () => $("#export-options").classList.toggle("hidden"));
document.querySelectorAll("[data-export]").forEach(link => link.addEventListener("click", () => {
  window.location.href = `/api/programs/${encodeURIComponent(state.program.file)}/export?format=${link.dataset.export}&${userQuery()}`;
  $("#export-options").classList.add("hidden");
  setMobileMenu(false, false);
}));

function nextMondayIsoDate(now = new Date()) {
  const date = new Date(now);
  const day = date.getDay();
  const daysToMonday = (8 - (day === 0 ? 7 : day)) % 7 || 7;
  date.setDate(date.getDate() + daysToMonday);
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const dayText = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${dayText}`;
}

function isoWeekFromDate(mondayIsoDate) {
  const [y, m, d] = mondayIsoDate.split("-").map(Number);
  const date = new Date(Date.UTC(y, m - 1, d));
  const target = new Date(Date.UTC(date.getUTCFullYear(), date.getUTCMonth(), date.getUTCDate()));
  const dayNr = (target.getUTCDay() + 6) % 7;
  target.setUTCDate(target.getUTCDate() - dayNr + 3);
  const firstThursday = new Date(Date.UTC(target.getUTCFullYear(), 0, 4));
  const diff = target - firstThursday;
  const week = 1 + Math.round(diff / (7 * 24 * 3600 * 1000));
  return `${target.getUTCFullYear()}-W${String(week).padStart(2, "0")}`;
}

async function loadTemplatesList() {
  const list = $("#templates-list");
  const detail = $("#template-detail");
  const empty = $("#templates-empty");
  detail.classList.add("hidden");
  $("#template-start-week").value = isoWeekFromDate(nextMondayIsoDate());
  list.replaceChildren(Object.assign(document.createElement("p"), { className: "editor-help", textContent: "Loading templates…" }));
  try {
    const result = await request("/api/templates");
    list.replaceChildren();
    if (!result.templates.length) {
      empty.classList.remove("hidden");
      return;
    }
    empty.classList.add("hidden");
    for (const template of result.templates) {
      const card = document.createElement("button");
      card.type = "button";
      card.className = "template-card";
      card.dataset.templateId = template.id;
      const eyebrow = document.createElement("p");
      eyebrow.className = "eyebrow";
      eyebrow.textContent = `${template.distanceLabel} · ${template.durationWeeks} weeks`;
      const title = document.createElement("h3");
      title.textContent = template.name;
      const summary = document.createElement("p");
      summary.className = "description";
      summary.textContent = template.description || "";
      const meta = document.createElement("ul");
      meta.className = "template-meta";
      for (const item of [`${template.sessionsPerWeek} runs / week`, template.hasRaceWeek ? "Includes race week" : "No race week", `Source: ${template.source}`]) {
        const li = document.createElement("li");
        li.textContent = item;
        meta.append(li);
      }
      card.append(eyebrow, title, summary, meta);
      card.addEventListener("click", () => showTemplateDetail(template));
      list.append(card);
    }
  } catch (error) {
    list.replaceChildren(Object.assign(document.createElement("p"), { className: "sync-error", textContent: error.message }));
  }
}

function showTemplateDetail(template) {
  $("#template-detail-eyebrow").textContent = `${template.distanceLabel} · ${template.durationWeeks} weeks`;
  $("#template-detail-name").textContent = template.name;
  $("#template-detail-description").textContent = template.description || "";
  const meta = $("#template-detail-meta");
  meta.replaceChildren();
  for (const item of [`${template.sessionsPerWeek} runs / week`, template.hasRaceWeek ? "Includes race week" : "No race week", `Source: ${template.source}`, `Suggested filename: ${template.id}-${$("#template-start-week").value.toLowerCase() || "<start-week>"}.yaml`]) {
    const li = document.createElement("li");
    li.textContent = item;
    meta.append(li);
  }
  $("#template-use-button").dataset.templateId = template.id;
  $("#template-detail").classList.remove("hidden");
  $("#templates-list").classList.add("hidden");
}

$("#template-start-week").addEventListener("input", () => {
  const button = $("#template-use-button");
  const templateId = button.dataset.templateId;
  if (!templateId) return;
  const meta = $("#template-detail-meta");
  const last = meta.lastElementChild;
  if (last) last.textContent = `Suggested filename: ${templateId}-${$("#template-start-week").value.toLowerCase() || "<start-week>"}.yaml`;
});

$("#template-back-button").addEventListener("click", () => {
  $("#template-detail").classList.add("hidden");
  $("#templates-list").classList.remove("hidden");
});

async function useTemplate() {
  const button = $("#template-use-button");
  const templateId = button.dataset.templateId;
  if (!templateId) return;
  const startWeek = $("#template-start-week").value;
  button.disabled = true;
  try {
    const copy = await request(`/api/templates/${encodeURIComponent(templateId)}/copy`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ start_week: startWeek }),
    });
    await request("/api/programs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        userId: state.user.id,
        filename: copy.filename,
        content: copy.content,
      }),
    });
    await activateProgram(copy.filename);
    $("#add-program-dialog").close();
  } catch (error) {
    showError(error.message);
  } finally {
    button.disabled = false;
  }
}

$("#template-use-button").addEventListener("click", (event) => {
  event.preventDefault();
  useTemplate();
});

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
