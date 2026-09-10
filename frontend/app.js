"use strict";

const $ = (id) => document.getElementById(id);
// Access tokens stay in memory; the refresh token survives reloads within this tab.
const SESSION_KEY = "cestos.refresh-token";
const openedResetLink = location.hash.startsWith("#reset=");
const session = { access: null, refresh: null, user: null, expiresAt: 0 };
const users = { page: 1, pages: 0 };
const pagers = {
  employees: { page: 1, pages: 0 },
  projects: { page: 1, pages: 0 },
  assets: { page: 1, pages: 0 },
  clients: { page: 1, pages: 0 },
  locations: { page: 1, pages: 0 },
};
const VIEWS = ["inventory", "availability", "my-profile", "notifications", "hr-settings", "employee-details", "home", "employees", "projects", "assets", "clients", "locations", "users"];
let busy = false;
let refreshing = null;
const nameCache = { employees: null, projects: null, assets: null, locations: null, clients: null };

class ApiError extends Error {
  constructor(status, message) { super(message); this.status = status; }
}
function showError(id, message) { $(id).textContent = message; $(id).hidden = !message; }
function notice(message, error = false) {
  $("notice").textContent = message; $("notice").hidden = !message;
  $("notice").classList.toggle("error", error);
}
function statusMessages(status) {
  return {
    401: "Your session has ended. Please sign in again.",
    403: "You don’t have permission to do this. Contact your administrator.",
    404: "We couldn’t find that record in your organization.",
    409: "This conflicts with existing data. It may already exist.",
    422: "Please check the details and try again.",
  }[status] || "Something went wrong. Please try again.";
}
async function send(path, { method = "GET", body, authenticated = true } = {}) {
  const headers = { Accept: "application/json" };
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (authenticated && session.access) headers.Authorization = `Bearer ${session.access}`;
  let response;
  try {
    response = await fetch(path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(15000) });
  } catch { throw new ApiError(0, "We couldn’t connect. Please try again in a moment."); }
  const data = response.status === 204 ? null : await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data?.error?.message || statusMessages(response.status));
  return data;
}
async function sendForm(path, form) {
  const headers = {};
  if (session.access) headers.Authorization = `Bearer ${session.access}`;
  let response;
  try {
    response = await fetch(path, { method: "POST", headers, body: form, cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(30000) });
  } catch { throw new ApiError(0, "We couldn’t connect. Please try again in a moment."); }
  const data = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, data?.error?.message || statusMessages(response.status));
  return data;
}
async function sendBlob(path) {
  const headers = {};
  if (session.access) headers.Authorization = `Bearer ${session.access}`;
  const response = await fetch(path, { headers, cache: "no-store", credentials: "omit", signal: AbortSignal.timeout(30000) });
  if (!response.ok) throw new ApiError(response.status, data?.error?.message || statusMessages(response.status));
  const disposition = response.headers.get("content-disposition") || "";
  const match = disposition.match(/filename="?([^"]+)"?/);
  return { blob: await response.blob(), filename: match ? match[1] : "download" };
}
function saveTokens(tokens) {
  session.access = tokens.access_token; session.refresh = tokens.refresh_token;
  session.expiresAt = Date.now() + tokens.expires_in * 1000;
  try { sessionStorage.setItem(SESSION_KEY, session.refresh); } catch {}
}
async function refreshSession() {
  if (!refreshing) refreshing = send("/api/v1/auth/refresh", { method: "POST", body: { refresh_token: session.refresh }, authenticated: false }).then(saveTokens).finally(() => { refreshing = null; });
  return refreshing;
}
async function api(path, options = {}) {
  try {
    if (session.refresh && Date.now() >= session.expiresAt - 30000) await refreshSession();
    try { return await send(path, options); }
    catch (error) {
      if (error.status !== 401 || !session.refresh) throw error;
      await refreshSession(); return await send(path, options);
    }
  } catch (error) {
    if (error.status === 401) { signOutLocally(); showError("login-error", error.message); }
    throw error;
  }
}
async function apiBlob(path) {
  if (session.refresh && Date.now() >= session.expiresAt - 30000) await refreshSession();
  try { return await sendBlob(path); }
  catch (error) {
    if (error.status !== 401 || !session.refresh) throw error;
    await refreshSession(); return await sendBlob(path);
  }
}
function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url; link.download = filename; document.body.append(link);
  link.click(); link.remove(); setTimeout(() => URL.revokeObjectURL(url), 5000);
}
function fmtDate(value) { return value ? new Date(value).toLocaleDateString() : "—"; }
function fmtDateTime(value) { return value ? new Date(value).toLocaleString() : "—"; }
function text(value) { return value === null || value === undefined || value === "" ? "—" : String(value); }
function el(tag, content, className) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}
function updatePager(name) {
  const pager = name === "users" ? users : pagers[name];
  const prev = $(name === "users" ? "previous-page" : `${name}-prev`);
  const next = $(name === "users" ? "next-page" : `${name}-next`);
  if (prev) prev.disabled = busy || pager.page <= 1;
  if (next) next.disabled = busy || pager.page >= pager.pages;
}
function pagination() {
  updatePager("users");
  for (const name of Object.keys(pagers)) updatePager(name);
}
async function action(task, errorId = null) {
  if (busy) return;
  busy = true;
  const controls = [...document.querySelectorAll("button, input, select, textarea")];
  const previouslyDisabled = new Set(controls.filter((element) => element.disabled));
  controls.forEach((element) => { element.disabled = true; });
  if (errorId) showError(errorId, "");
  try { await task(); }
  catch (error) {
    if (errorId && (session.user || errorId === "login-error" || errorId === "hr-error")) showError(errorId, error.message);
    else if (session.user) notice(error.message, true);
  } finally {
    busy = false; controls.forEach((element) => { element.disabled = previouslyDisabled.has(element); });
    pagination(); $("sign-in").textContent = "Sign in →"; $("save-user").textContent = "Create user";
  }
}
function signOutLocally() {
  try { sessionStorage.removeItem(SESSION_KEY); } catch {}
  session.access = null; session.refresh = null; session.user = null; session.expiresAt = 0;
  for (const key of Object.keys(nameCache)) nameCache[key] = null;
  Workforce.clear();
  HR.clear();
  for (const node of document.querySelectorAll("tbody")) node.replaceChildren();
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  $("workspace").hidden = true; $("auth-screen").hidden = false;
  $("user-rows").replaceChildren(); $("account-name").textContent = ""; $("account-email").textContent = "";
  $("create-form").reset(); $("login-password").value = ""; notice("");
  history.replaceState(null, "", location.pathname);
}
function showView(view) {
  if (!session.user) return;
  const current = VIEWS.includes(view) ? view : "home";
  for (const name of VIEWS) $(`${name}-view`).hidden = name !== current;
  for (const link of document.querySelectorAll("[data-view]")) {
    if (link.dataset.view === (current === "employee-details" ? "employees" : current)) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current");
  }
}
function emptyTable(bodyId, columns, message) {
  $(bodyId).replaceChildren();
  const row = document.createElement("tr"); const cell = document.createElement("td");
  cell.colSpan = columns; cell.className = "table-empty"; cell.textContent = message;
  row.append(cell); $(bodyId).append(row);
}
function addRow(bodyId, cells, onSelect) {
  const row = document.createElement("tr");
  for (const value of cells) {
    const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
  }
  if (onSelect) {
    row.style.cursor = "pointer";
    row.addEventListener("click", () => onSelect());
    row.tabIndex = 0;
    row.addEventListener("keydown", (event) => { if (event.key === "Enter") onSelect(); });
  }
  $(bodyId).append(row);
}
async function ensureNameCache(kind) {
  if (nameCache[kind]) return nameCache[kind];
  const map = new Map();
  try {
    const result = await api(`/api/v1/${kind}?page=1&page_size=100`);
    for (const item of result.items) map.set(item.id, item.name || `${item.first_name || ""} ${item.last_name || ""}`.trim());
  } catch { /* read permission may be missing; names stay unresolved */ }
  nameCache[kind] = map;
  return map;
}
async function displayName(kind, id) {
  if (!id) return "—";
  return (await ensureNameCache(kind)).get(id) || "—";
}
async function loadOptions(selectId, kind, placeholder) {
  const select = $(selectId);
  select.replaceChildren(new Option(placeholder, ""));
  try {
    const result = await api(`/api/v1/${kind}?page=1&page_size=100`);
    for (const item of (Array.isArray(result) ? result : result.items)) {
      select.append(new Option(item.name || `${item.first_name || ""} ${item.last_name || ""}`.trim() || item.id, item.id));
    }
  } catch { /* leave placeholder when the list cannot be read */ }
}
/* ---------- home ---------- */
async function loadSummary() {
  $("ops-summary").textContent = "Loading today’s numbers…";
  try {
    const summary = await api("/api/v1/operations/summary");
    const people = `${summary.employees.total} employees (${summary.employees.assigned} assigned)`;
    const projects = `${summary.projects.total} projects (${summary.projects.active} active)`;
    const assets = `${summary.assets.total} assets (${summary.assets.operating} operating)`;
    $("ops-summary").textContent = `${people} · ${projects} · ${assets}.`;
    $("ops-headline").textContent = "Your operations at a glance.";
    $("count-employees").textContent = `${summary.employees.total} TOTAL`;
    $("count-projects").textContent = `${summary.projects.active} ACTIVE`;
    $("count-assets").textContent = `${summary.assets.total} TOTAL`;
  } catch {
    $("ops-summary").textContent = "Operations numbers need the projects read permission. Your administrator can grant it.";
  }
  for (const [id, kind] of [["count-clients", "clients"], ["count-locations", "locations"]]) {
    try {
      const result = await api(`/api/v1/${kind}?page=1&page_size=1`);
      $(id).textContent = `${result.total} TOTAL`;
    } catch { $(id).textContent = "—"; }
  }
}
/* ---------- workforce availability ---------- */
const availabilityState = { month: new Date(new Date().getFullYear(), new Date().getMonth(), 1) };
function availabilityIso(date) { return date.toISOString().slice(0, 10); }
function availabilityIncludes(date, start, end) { return start && end && date >= start && date <= end; }
async function loadAvailability() {
  const month = availabilityState.month;
  const year = month.getFullYear(); const monthIndex = month.getMonth();
  $("availability-month").textContent = month.toLocaleDateString(undefined, { month: "long", year: "numeric" });
  const content = $("availability-content"); content.replaceChildren(el("p", "Loading availability…", "hint"));
  try {
    const result = await api("/api/v1/employees?page=1&page_size=100&is_active=true");
    const employees = await Promise.all(result.items.map(async (item) => {
      const [overview, rotations, leave] = await Promise.all([
        api(`/api/v1/employees/${item.id}/overview`).catch(() => null),
        api(`/api/v1/employees/${item.id}/rotations`).catch(() => []),
        api(`/api/v1/employees/${item.id}/leave-requests`).catch(() => []),
      ]);
      return { item, overview, rotations, leave };
    }));
    const days = new Date(year, monthIndex + 1, 0).getDate();
    const totals = { covered: 0, off: 0, leave: 0 };
    const grid = el("div", undefined, "availability-grid");
    grid.append(el("div", "Employee", "availability-name"));
    for (let dayNumber = 1; dayNumber <= days; dayNumber++) {
      const date = new Date(year, monthIndex, dayNumber);
      grid.append(el("div", `${date.toLocaleDateString(undefined, { weekday: "short" })} ${dayNumber}`, `availability-day-head ${date.getDay() === 0 || date.getDay() === 6 ? "weekend" : ""}`));
    }
    for (const person of employees) {
      const name = `${person.item.first_name} ${person.item.last_name}`;
      const project = person.overview?.current_project_name || "No current project";
      const nameCell = el("div", undefined, "availability-name"); nameCell.append(el("strong", name), el("small", project)); grid.append(nameCell);
      for (let dayNumber = 1; dayNumber <= days; dayNumber++) {
        const date = new Date(year, monthIndex, dayNumber); const key = availabilityIso(date); const cell = el("div", undefined, "availability-cell");
        const leave = person.leave.find((entry) => entry.status !== "REJECTED" && availabilityIncludes(key, entry.start_date, entry.end_date));
        const rotation = person.rotations.find((entry) => entry.status !== "CANCELLED" && availabilityIncludes(key, entry.work_start_date, entry.off_end_date));
        const off = rotation && availabilityIncludes(key, rotation.off_start_date, rotation.off_end_date);
        const weekend = date.getDay() === 0 || date.getDay() === 6;
        const state = leave ? "leave" : off ? "off" : weekend && !rotation ? "weekend" : "covered";
        cell.classList.add(state); cell.title = leave ? `${name}: ${leave.reason || "Leave"} (${leave.status})` : off ? `${name}: Off rotation` : weekend && !rotation ? `${name}: Weekend` : `${name}: Covered${project === "No current project" ? " · no project" : ` · ${project}`}`;
        cell.append(el("span", state === "leave" ? "Leave" : state === "off" ? "Off" : state === "weekend" ? "Weekend" : "On")); grid.append(cell);
        if (state !== "weekend") totals[state]++;
      }
    }
    content.replaceChildren(grid);
    $("availability-summary").replaceChildren(...[["covered", "Covered days"], ["off", "Off rotation days"], ["leave", "Leave days"]].map(([key, title]) => { const card = el("article"); card.append(el("strong", totals[key]), el("span", title)); return card; }));
  } catch (error) { content.replaceChildren(el("p", `Availability unavailable: ${error.message}`, "form-error")); }
}
/* ---------- users (existing) ---------- */
function emptyUsers(message) {
  $("user-rows").replaceChildren();
  const row = document.createElement("tr"); const cell = document.createElement("td");
  cell.colSpan = 4; cell.className = "table-empty"; cell.textContent = message;
  row.append(cell); $("user-rows").append(row);
}
async function loadUsers(page = 1) {
  $("user-count").textContent = "Loading accounts…";
  try {
    const result = await api(`/api/v1/users?page=${page}&page_size=${$("page-size").value}`);
    users.page = result.page; users.pages = result.pages; $("user-rows").replaceChildren();
    if (!result.items.length) emptyUsers("No users on this page.");
    for (const user of result.items) {
      const row = document.createElement("tr");
      for (const value of [`${user.first_name} ${user.last_name}`, user.email, user.is_active ? "Active" : "Inactive", new Date(user.created_at).toLocaleDateString()]) {
        const cell = document.createElement("td"); cell.textContent = value; row.append(cell);
      }
      $("user-rows").append(row);
    }
    $("user-count").textContent = `${result.total} accounts in your organization`;
    $("page-info").textContent = `Page ${result.pages ? result.page : 0} of ${result.pages}`;
  } catch (error) {
    users.page = 1; users.pages = 0; emptyUsers(error.message);
    $("user-count").textContent = "Accounts unavailable"; $("page-info").textContent = "";
    throw error;
  } finally { pagination(); }
}
/* ---------- generic lists ---------- */
const LIST_CONFIG = {
  employees: { path: "employees", count: "employee-count", rows: "employee-rows", info: "employee-page-info", search: "employee-search", label: "employees" },
  projects: { path: "projects", count: "project-count", rows: "project-rows", info: "project-page-info", search: "project-search", label: "projects" },
  assets: { path: "assets", count: "asset-count", rows: "asset-rows", info: "asset-page-info", search: "asset-search", label: "assets" },
  clients: { path: "clients", count: "client-count", rows: "client-rows", info: "client-page-info", search: null, label: "clients" },
  locations: { path: "locations", count: "location-count", rows: "location-rows", info: "location-page-info", search: null, label: "locations" },
};
const ROW_BUILDERS = {
  employees: (item) => [`${item.first_name} ${item.last_name}`, item.employee_number, text(item.job_title), item.is_active ? text(item.employment_status) : "Archived"],
  projects: (item) => [item.name, item.project_number, text(item.status), fmtDate(item.start_date)],
  assets: (item) => [item.name, item.asset_number, text(item.status), item.current_meter_reading ?? "—"],
  clients: (item) => [item.name, item.client_number, text(item.primary_contact_name), item.is_active ? "Active" : "Archived"],
  locations: (item) => [item.name, item.location_number, text(item.location_type), item.is_active ? "Active" : "Archived"],
};
async function loadList(name, page = 1) {
  if (name === "employees") return Workforce.list(page);
  if (name === "assets") await Fleet.dashboard();
  const cfg = LIST_CONFIG[name];
  const pager = pagers[name];
  $(cfg.count).textContent = "Loading…";
  try {
    let path = `/api/v1/${cfg.path}?page=${page}&page_size=20`;
    if (cfg.search) {
      const term = $(cfg.search).value.trim();
      if (term) path += `&search=${encodeURIComponent(term)}`;
    }
    if (name === "assets") path += Fleet.filters();
    const result = await api(path);
    pager.page = result.page; pager.pages = result.pages; $(cfg.rows).replaceChildren();
    if (!result.items.length) emptyTable(cfg.rows, 4, `No ${cfg.label} found.`);
    for (const item of result.items) addRow(cfg.rows, ROW_BUILDERS[name](item), () => openDetail(name, item.id));
    $(cfg.count).textContent = `${result.total} ${cfg.label} in your organization · select a row for details`;
    $(cfg.info).textContent = `Page ${result.pages ? result.page : 0} of ${result.pages}`;
  } catch (error) {
    pager.page = 1; pager.pages = 0; emptyTable(cfg.rows, 4, error.message);
    $(cfg.count).textContent = "Unavailable"; $(cfg.info).textContent = "";
    throw error;
  } finally { pagination(); }
}
/* ---------- detail dialog ---------- */
function openDialogTitle(eyebrow, title) {
  $("detail-eyebrow").textContent = eyebrow;
  $("detail-title").textContent = title;
  $("detail-body").replaceChildren();
  $("detail-dialog").showModal();
}
function detailSection(title) {
  $("detail-body").append(el("h3", title));
}
function detailList(entries) {
  const list = el("dl", undefined, "detail-list");
  for (const [term, value] of entries) {
    list.append(el("dt", term), el("dd", value));
  }
  $("detail-body").append(list);
}
function detailTable(headers, rows) {
  const wrap = el("div", undefined, "table-scroll");
  const table = document.createElement("table");
  const head = document.createElement("thead");
  const headRow = document.createElement("tr");
  for (const header of headers) headRow.append(el("th", header, undefined));
  head.append(headRow); table.append(head);
  const body = document.createElement("tbody");
  if (!rows.length) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = headers.length; cell.className = "table-empty"; cell.textContent = "Nothing here yet.";
    row.append(cell); body.append(row);
  }
  for (const cells of rows) {
    const row = document.createElement("tr");
    for (const value of cells) row.append(el("td", value));
    body.append(row);
  }
  table.append(body); wrap.append(table); $("detail-body").append(wrap);
}
function downloadButton(label, path) {
  const button = el("button", label, "secondary");
  button.type = "button";
  button.addEventListener("click", () => action(async () => {
    const { blob, filename } = await apiBlob(path);
    downloadBlob(blob, filename);
    notice("Download started.");
  }));
  return button;
}
async function openDetail(kind, id) {
  try {
    if (kind === "employees") await employeeDetail(id);
    else if (kind === "projects") await projectDetail(id);
    else if (kind === "assets") await assetDetail(id);
    else if (kind === "clients") await clientDetail(id);
    else if (kind === "locations") await locationDetail(id);
  } catch (error) {
    notice(error.message, true);
  }
}
/* ----- employee detail ----- */
async function employeeDetail(id) { return Workforce.open(id); }
function assignEmployeeForm(employeeId) {
  const form = el("form", undefined, "detail-form");
  const projectSelect = document.createElement("select");
  const startInput = document.createElement("input");
  startInput.type = "date"; startInput.required = true; startInput.value = new Date().toISOString().slice(0, 10);
  const roleInput = document.createElement("input");
  roleInput.placeholder = "Role (optional)"; roleInput.maxLength = 150;
  const submit = el("button", "Assign", "primary"); submit.type = "submit";
  form.append(projectSelect, startInput, roleInput, submit);
  loadOptionsInto(projectSelect, "projects", "Choose project…");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    action(async () => {
      await api(`/api/v1/employees/${employeeId}/assignments`, { method: "POST", body: { project_id: projectSelect.value, start_date: startInput.value, role_on_project: roleInput.value || null } });
      notice("Assignment created."); await employeeDetail(employeeId);
      await loadList("employees", pagers.employees.page).catch(() => {});
    });
  });
  return form;
}
async function loadOptionsInto(select, kind, placeholder) {
  select.replaceChildren(new Option(placeholder, ""));
  try {
    const result = await api(`/api/v1/${kind}?page=1&page_size=100`);
    for (const item of (Array.isArray(result) ? result : result.items)) {
      select.append(new Option(item.name || `${item.first_name || ""} ${item.last_name || ""}`.trim() || item.id, item.id));
    }
  } catch { /* leave placeholder when the list cannot be read */ }
}
function assignSkillForm(employeeId) {
  const form = el("form", undefined, "detail-form");
  const skillSelect = document.createElement("select");
  const submit = el("button", "Add skill", "secondary"); submit.type = "submit";
  form.append(skillSelect, submit);
  loadOptionsInto(skillSelect, "skills", "Choose skill…");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    action(async () => {
      await api(`/api/v1/employees/${employeeId}/skills`, { method: "POST", body: { skill_id: skillSelect.value } });
      notice("Skill added."); await employeeDetail(employeeId);
    });
  });
  return form;
}
function uploadForm(kind, parentId) {
  const form = el("form", undefined, "detail-form");
  const fileInput = document.createElement("input");
  fileInput.type = "file"; fileInput.required = true;
  fileInput.accept = ".pdf,.png,.jpg,.jpeg,.doc,.docx,.xls,.xlsx,.txt,.csv";
  const titleInput = document.createElement("input");
  titleInput.placeholder = "Title (optional)"; titleInput.maxLength = 200;
  const submit = el("button", "Upload", "secondary"); submit.type = "submit";
  form.append(fileInput, titleInput, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const file = fileInput.files[0];
    if (!file) return;
    const data = new FormData();
    data.append("file", file);
    if (titleInput.value.trim()) data.append("title", titleInput.value.trim());
    action(async () => {
      await sendForm(`/api/v1/${kind}/${parentId}/documents/upload`, data);
      notice("Document uploaded.");
      if (kind === "employees") { await employeeDetail(parentId); await loadList("employees", pagers.employees.page).catch(() => {}); }
      else { await assetDetail(parentId); await loadList("assets", pagers.assets.page).catch(() => {}); }
    });
  });
  return form;
}
/* ----- project detail ----- */
async function projectDetail(id) {
  const overview = await api(`/api/v1/projects/${id}/overview`);
  const project = overview.project;
  openDialogTitle("PROJECT", project.name);
  detailList([
    ["Number", project.project_number],
    ["Client", overview.client ? overview.client.name : "—"],
    ["Manager", overview.project_manager ? `${overview.project_manager.first_name} ${overview.project_manager.last_name}` : "—"],
    ["Status", text(project.status)], ["Start", fmtDate(project.start_date)],
    ["Expected end", fmtDate(project.expected_end_date)],
    ["Contract value", project.contract_value ?? "—"],
  ]);
  detailSection(`Sites (${overview.sites.length})`);
  detailTable(["Site", "Number", "Type"], overview.sites.map((site) => [site.name, site.location_number, text(site.location_type)]));
  detailSection(`People on site (${overview.employee_count})`);
  detailTable(["Employee", "Job title", "Status"], overview.current_employees.map((item) => [`${item.first_name} ${item.last_name}`, text(item.job_title), text(item.employment_status)]));
  detailSection(`Equipment on site (${overview.asset_count})`);
  detailTable(["Asset", "Number", "Status"], overview.current_assets.map((item) => [item.name, item.asset_number, text(item.status)]));
}
/* ----- asset detail ----- */
async function assetDetail(id) {
  return Fleet.open(id);
}
async function legacyAssetDetail(id) {
  const overview = await api(`/api/v1/assets/${id}/overview`);
  const asset = overview.asset;
  openDialogTitle("ASSET", asset.name);
  detailList([
    ["Number", asset.asset_number],
    ["Category", overview.category ? overview.category.name : "—"],
    ["Status", text(asset.status)], ["Manufacturer", text(asset.manufacturer)],
    ["Model", text(asset.model)], ["Serial", text(asset.serial_number)],
    ["Meter", asset.current_meter_reading ?? "—"],
    ["Responsible", overview.responsible_employee ? `${overview.responsible_employee.first_name} ${overview.responsible_employee.last_name}` : "—"],
  ]);
  detailSection("Current assignment");
  if (overview.current_assignment) {
    const current = overview.current_assignment;
    detailList([
      ["Assignment", current.assignment_number],
      ["Project", await displayName("projects", current.project_id)],
      ["Location", await displayName("locations", current.location_id)],
      ["Since", fmtDateTime(current.assigned_at)],
    ]);
  } else {
    $("detail-body").append(el("p", "Currently unassigned."));
  }
  detailSection("Assign to a project");
  $("detail-body").append(assignAssetForm(id));
  detailSection("Latest meter reading");
  detailList([["Reading", overview.latest_meter_reading ? `${overview.latest_meter_reading.reading} (${overview.latest_meter_reading.reading_type})` : "—"]]);
  $("detail-body").append(recordMeterForm(id));
  detailSection("Assignment history");
  detailTable(["Number", "Project", "Status"], await Promise.all(overview.recent_assignments.map(async (item) => [
    item.assignment_number, await displayName("projects", item.project_id), text(item.status),
  ])));
  detailSection("Components");
  detailTable(["Component", "Type", "Status"], overview.components.map((item) => [item.name, text(item.component_type), text(item.status)]));
  detailSection("Documents");
  detailTable(["Title", "Type", "File"], overview.documents.map((doc) => [doc.title, text(doc.document_type), doc.file_name || "—"]));
  for (const doc of overview.documents.filter((item) => item.file_url.endsWith("/download"))) {
    $("detail-body").append(downloadButton(`Download ${doc.title}`, doc.file_url));
  }
  $("detail-body").append(uploadForm("assets", id));
}
function assignAssetForm(assetId) {
  const form = el("form", undefined, "detail-form");
  const projectSelect = document.createElement("select");
  const whenInput = document.createElement("input");
  whenInput.type = "datetime-local"; whenInput.required = true;
  whenInput.value = new Date().toISOString().slice(0, 16);
  const submit = el("button", "Assign", "primary"); submit.type = "submit";
  form.append(projectSelect, whenInput, submit);
  loadOptionsInto(projectSelect, "projects", "Choose project…");
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    action(async () => {
      await api(`/api/v1/assets/${assetId}/assignments`, { method: "POST", body: { project_id: projectSelect.value, assigned_at: new Date(whenInput.value).toISOString() } });
      notice("Asset assigned."); await assetDetail(assetId);
      await loadList("assets", pagers.assets.page).catch(() => {});
    });
  });
  return form;
}
function recordMeterForm(assetId) {
  const form = el("form", undefined, "detail-form");
  const readingInput = document.createElement("input");
  readingInput.type = "number"; readingInput.min = "0"; readingInput.step = "0.01";
  readingInput.placeholder = "Reading"; readingInput.required = true;
  const typeSelect = document.createElement("select");
  for (const kind of ["ENGINE_HOURS", "OPERATING_HOURS", "ODOMETER_KM"]) typeSelect.append(new Option(kind, kind));
  const submit = el("button", "Record", "secondary"); submit.type = "submit";
  form.append(readingInput, typeSelect, submit);
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    action(async () => {
      await api(`/api/v1/assets/${assetId}/meter-readings`, { method: "POST", body: { reading: readingInput.value, recorded_at: new Date().toISOString(), reading_type: typeSelect.value } });
      notice("Meter reading recorded."); await assetDetail(assetId);
    });
  });
  return form;
}
/* ----- client / location detail ----- */
async function clientDetail(id) {
  const client = await api(`/api/v1/clients/${id}`);
  openDialogTitle("CLIENT", client.name);
  detailList([
    ["Number", client.client_number],
    ["Legal name", text(client.legal_name)],
    ["Contact", text(client.primary_contact_name)],
    ["Contact email", text(client.primary_contact_email)],
    ["Country", text(client.country)],
  ]);
  detailSection("Projects for this client");
  const projects = await api(`/api/v1/projects?client_id=${id}&page=1&page_size=100`).catch(() => ({ items: [] }));
  detailTable(["Project", "Number", "Status"], projects.items.map((item) => [item.name, item.project_number, text(item.status)]));
}
async function locationDetail(id) {
  const location = await api(`/api/v1/locations/${id}`);
  openDialogTitle("LOCATION", location.name);
  detailList([
    ["Number", location.location_number], ["Type", text(location.location_type)],
    ["Project", await displayName("projects", location.project_id)],
    ["City", text(location.city)], ["Country", text(location.country)],
  ]);
  detailSection("People here now");
  const employees = await api(`/api/v1/employees?location_id=${id}&page=1&page_size=100`).catch(() => ({ items: [] }));
  detailTable(["Employee", "Job title", "Status"], employees.items.map((item) => [`${item.first_name} ${item.last_name}`, text(item.job_title), text(item.employment_status)]));
  detailSection("Equipment here now");
  const assets = await api(`/api/v1/assets?location_id=${id}&page=1&page_size=100`).catch(() => ({ items: [] }));
  detailTable(["Asset", "Number", "Status"], assets.items.map((item) => [item.name, item.asset_number, text(item.status)]));
}
/* ---------- create forms ---------- */
function cleanForm(body) {
  for (const key of Object.keys(body)) {
    if (typeof body[key] === "string") body[key] = body[key].trim();
    if (body[key] === "") body[key] = null;
  }
  return body;
}
function openCreateForm(dialogId, formId, errorId, focusId) {
  if (!session.user) return;
  $("record-dialog").close();
  $(formId).reset(); showError(errorId, "");
  $(dialogId).showModal(); $(focusId).focus();
}
async function openProjectForm() {
  openCreateForm("project-dialog", "project-form", "project-error", "project-name");
  await loadOptionsInto($("project-client"), "clients", "Choose client…");
}
async function openLocationForm() {
  openCreateForm("location-dialog", "location-form", "location-error", "location-name");
  const select = $("location-project");
  select.replaceChildren(new Option("— None —", ""));
  try {
    const result = await api("/api/v1/projects?page=1&page_size=100");
    for (const item of result.items) select.append(new Option(item.name, item.id));
  } catch { /* projects stay unlisted */ }
}
async function openAssetForm() {
  return Fleet.create();
}
async function legacyOpenAssetForm() {
  openCreateForm("asset-dialog", "asset-form", "asset-error", "asset-name");
  await loadOptionsInto($("asset-category"), "asset-categories", "Choose category…");
}
function openUserForm() {
  openCreateForm("user-dialog", "create-form", "create-error", "first-name");
}
function wireCreate(formId, errorId, saveId, path, listName, dialogId, successMessage) {
  $(formId).addEventListener("submit", (event) => {
    event.preventDefault();
    const body = cleanForm(Object.fromEntries(new FormData(event.currentTarget)));
    action(async () => {
      $(saveId).textContent = "Creating…";
      try {
        await api(path, { method: "POST", body });
        $(dialogId).close(); $(formId).reset();
        notice(successMessage);
        try { await loadList(listName, 1); } catch (error) { if (session.user) notice(`Created. ${error.message}`, true); }
      } finally { $(saveId).textContent = $(saveId).textContent.replace("Creating…", "Create"); }
    }, errorId);
  });
}
/* ---------- auth & wiring ---------- */
async function showWorkspace(user) {
  session.user = user; $("auth-screen").hidden = true; $("workspace").hidden = false;
  $("account-name").textContent = `${user.first_name} ${user.last_name}`;
  $("account-email").textContent = user.email; $("greeting").textContent = `Welcome, ${user.first_name}.`;
  await HR.initialize();
  if (!HR.access.workforce && location.hash !== "#inventory") { showView("my-profile"); history.replaceState(null,"","#my-profile"); await HR.self(); return; }
  if (location.hash.startsWith("#employees/")) { await Workforce.open(decodeURIComponent(location.hash.slice(11)), false); return; }
  const route = ROUTES[location.hash] || ROUTES["#home"];
  showView(route[0]);
  await route[1]();
}
async function restoreSession() {
  if (openedResetLink) return;
  try { session.refresh = sessionStorage.getItem(SESSION_KEY); } catch { return; }
  if (!session.refresh) return;
  await action(async () => {
    try {
      await refreshSession();
      await showWorkspace(await api("/api/v1/auth/me"));
    } catch (error) {
      if (error.status === 401) signOutLocally();
      showError("login-error", error.status === 401 ? "Your session has expired. Please sign in again." : error.message);
    }
  }, "login-error");
}
window.addEventListener("DOMContentLoaded", restoreSession);
$("login-form").addEventListener("submit", (event) => {
  event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget));
  body.email = body.email.trim(); body.organization_id = body.organization_id.trim();
  action(async () => {
    $("sign-in").textContent = "Signing in…";
    try {
      saveTokens(await send("/api/v1/auth/login", { method: "POST", body, authenticated: false }));
      await showWorkspace(await api("/api/v1/auth/me"));
    } catch (error) {
      signOutLocally();
      if (error.status === 401) throw new ApiError(401, "The email, password, or organization is incorrect.");
      throw error;
    } finally { $("login-password").value = ""; }
  }, "login-error");
});
$("sign-out").addEventListener("click", () => action(async () => {
  let failed = false;
  try { await send("/api/v1/auth/logout", { method: "POST", body: { refresh_token: session.refresh }, authenticated: false }); }
  catch { failed = true; } finally { signOutLocally(); }
  showError("login-error", failed ? "Signed out on this device. We couldn’t reach the server to end the session there." : "");
}));
const ROUTES = {
  "#inventory": ["inventory", () => Inventory.open()],
  "#availability": ["availability", loadAvailability],
  "#my-profile": ["my-profile", () => HR.self()],
  "#notifications": ["notifications", () => HR.notifications()],
  "#hr-settings": ["hr-settings", () => HR.settings()],
  "#home": ["home", loadSummary],
  "#employees": ["employees", () => loadList("employees")],
  "#projects": ["projects", () => loadList("projects")],
  "#assets": ["assets", () => loadList("assets")],
  "#clients": ["clients", () => loadList("clients")],
  "#locations": ["locations", () => loadList("locations")],
  "#users": ["users", () => loadUsers()],
};
window.addEventListener("hashchange", () => {
  if (HR.openPasswordReset()) return;
  if (!session.user) return;
  if (location.hash.startsWith("#employees/")) { action(() => Workforce.open(decodeURIComponent(location.hash.slice(11)), false)); return; }
  const route = ROUTES[location.hash] || ROUTES["#home"];
  showView(route[0]); notice("");
  action(() => route[1]());
});
$("create-record").addEventListener("click", () => { if (session.user && !busy) $("record-dialog").showModal(); });
for (const id of ["choose-user", "home-create-user", "add-user"]) $(id).addEventListener("click", openUserForm);
$("choose-employee").addEventListener("click", () => Workforce.createEmployee());
$("choose-client").addEventListener("click", () => openCreateForm("client-dialog", "client-form", "client-error", "client-name"));
$("choose-project").addEventListener("click", () => action(() => openProjectForm()));
$("choose-location").addEventListener("click", () => action(() => openLocationForm()));
$("choose-asset").addEventListener("click", () => action(() => openAssetForm()));
$("add-employee").addEventListener("click", () => Workforce.createEmployee());
$("availability-prev").addEventListener("click", () => action(() => { availabilityState.month = new Date(availabilityState.month.getFullYear(), availabilityState.month.getMonth() - 1, 1); return loadAvailability(); }));
$("availability-next").addEventListener("click", () => action(() => { availabilityState.month = new Date(availabilityState.month.getFullYear(), availabilityState.month.getMonth() + 1, 1); return loadAvailability(); }));







$("add-client").addEventListener("click", () => openCreateForm("client-dialog", "client-form", "client-error", "client-name"));
$("add-project").addEventListener("click", () => action(() => openProjectForm()));
$("add-location").addEventListener("click", () => action(() => openLocationForm()));
$("add-asset").addEventListener("click", () => action(() => openAssetForm()));
for (const button of document.querySelectorAll("[data-close]")) button.addEventListener("click", () => { if (!busy) $(button.dataset.close).close(); });
for (const dialog of document.querySelectorAll("dialog")) dialog.addEventListener("cancel", (event) => { if (busy) event.preventDefault(); });
$("user-dialog").addEventListener("close", () => { $("new-password").value = ""; });
$("create-form").addEventListener("submit", (event) => {
  event.preventDefault(); const body = Object.fromEntries(new FormData(event.currentTarget));
  body.email = body.email.trim(); body.first_name = body.first_name.trim(); body.last_name = body.last_name.trim();
  action(async () => {
    $("save-user").textContent = "Creating…";
    try {
      const user = await api("/api/v1/users", { method: "POST", body });
      $("user-dialog").close(); $("create-form").reset();
      history.replaceState(null, "", "#users"); showView("users");
      notice(`${user.first_name} ${user.last_name}’s account was created.`);
      try { await loadUsers(); } catch (error) { if (session.user) notice(`Account created. ${error.message}`, true); }
    } finally { $("new-password").value = ""; }
  }, "create-error");
});

wireCreate("client-form", "client-error", "save-client", "/api/v1/clients", "clients", "client-dialog", "Client created.");
wireCreate("project-form", "project-error", "save-project", "/api/v1/projects", "projects", "project-dialog", "Project created.");
wireCreate("location-form", "location-error", "save-location", "/api/v1/locations", "locations", "location-dialog", "Location created.");
wireCreate("asset-form", "asset-error", "save-asset", "/api/v1/assets", "assets", "asset-dialog", "Asset registered.");






$("reload-users").addEventListener("click", () => action(() => loadUsers(users.page)));
$("previous-page").addEventListener("click", () => action(() => loadUsers(users.page - 1)));
$("next-page").addEventListener("click", () => action(() => loadUsers(users.page + 1)));
$("page-size").addEventListener("change", () => action(() => loadUsers()));
for (const name of ["employees", "projects", "assets", "clients", "locations"]) {
  $(`reload-${name}`).addEventListener("click", () => action(() => loadList(name, 1)));
  $(`${name}-prev`).addEventListener("click", () => action(() => loadList(name, pagers[name].page - 1)));
  $(`${name}-next`).addEventListener("click", () => action(() => loadList(name, pagers[name].page + 1)));
}


















for (const id of ["employee-search", "project-search", "asset-search"]) {
  $(id).addEventListener("change", () => action(() => loadList(id.replace("-search", "s"), 1)));
}
pagination();

"use strict";

// Employee UI contracts reference the API's published create/update schemas.
// This keeps enum values, required fields and nullable fields in sync with the backend.
window.Workforce = (() => {
  let employeeId = null;
  let employee = null;
  let generation = 0;
  let contractPromise = null;
  const root = () => `/api/v1/employees/${employeeId}`;
  const configs = {
    family: { label: "Family", path: "family", item: "employee-family-members", create: "EmployeeFamilyCreate", update: "EmployeeFamilyUpdate", columns: ["full_name", "relationship_type", "is_dependent", "is_next_of_kin", "is_active"], actions: ["set-next-of-kin", "set-dependent", "archive"] },
    emergency: { label: "Emergency contacts", path: "emergency-contacts", item: "employee-emergency-contacts", create: "EmergencyContactCreate", update: "EmergencyContactUpdate", columns: ["full_name", "relationship", "primary_phone", "is_primary", "is_active"], actions: ["set-primary", "archive"] },
    resumes: { label: "Resumes", path: "resumes", item: "employee-resumes", create: "EmployeeResumeCreate", update: "EmployeeResumeUpdate", columns: ["title", "version", "is_current", "uploaded_at", "is_active"], actions: ["set-current", "archive"], upload: true },
    documents: { label: "Documents", path: "documents", item: "employee-documents", create: "EmployeeDocumentCreate", update: "EmployeeDocumentUpdate", columns: ["title", "document_type", "expiry_date", "verification_status", "is_active"], actions: ["verify", "reject", "archive"], upload: true },
    qualifications: { label: "Qualifications", path: "qualifications", item: "employee-qualifications", create: "QualificationCreate", update: "QualificationUpdate", columns: ["qualification_name", "qualification_type", "institution", "completion_date", "is_active"], actions: ["archive"] },
    skills: { label: "Skills", path: "skills", item: "employee-skills", create: "EmployeeSkillCreate", update: "EmployeeSkillUpdate", columns: ["skill_name", "proficiency_level", "years_experience", "expiry_date"], actions: [] },
    training: { label: "Training", path: "training", item: "employee-training", create: "TrainingCreate", update: "TrainingUpdate", columns: ["training_name", "provider", "completion_date", "expiry_date", "status"], actions: [] },
    licenses: { label: "Licences", path: "licenses", item: "employee-licenses", create: "LicenseCreate", update: "LicenseUpdate", columns: ["license_number", "license_type", "expiry_date", "status"], actions: [] },
    assignments: { label: "Assignments", path: "assignments", item: "employee-assignments", create: "EmployeeAssignmentCreate", update: "EmployeeAssignmentUpdate", columns: ["assignment_number", "project_id", "role_on_project", "start_date", "end_date", "status"], actions: ["complete", "cancel"] },
    rotations: { label: "Rotations", path: "rotations", create: "EmployeeRotationCreate", columns: ["rotation_pattern_name", "work_start_date", "work_end_date", "off_end_date", "status"], actions: [] },
    authorizations: { label: "Asset authorizations", path: "asset-authorizations", item: "employee-asset-authorizations", create: "AssetAuthorizationCreate", update: "AssetAuthorizationUpdate", columns: ["asset_id", "asset_category_id", "authorization_type", "valid_until", "status"], actions: ["revoke"] },
    time_logs: { label: "Time logs", path: "time-logs", item: "time-logs", create: "TimeLogCreate", columns: ["date", "check_in", "check_out", "status"], actions: [] },
    leave_requests: { label: "Leave requests", path: "leave-requests", item: "leave-requests", create: "LeaveRequestCreate", columns: ["start_date", "end_date", "reason", "status"], actions: ["approve", "reject"] },
  };
  const setup = {
    departments: { label: "Departments", create: "DepartmentCreate", update: "DepartmentUpdate", columns: ["name", "code", "is_active"] },
    positions: { label: "Positions", create: "PositionCreate", update: "PositionUpdate", columns: ["title", "department_id", "grade", "is_field_role", "is_active"] },
    skills: { label: "Skill catalogue", create: "SkillCreate", update: "SkillUpdate", columns: ["name", "category", "is_active"] },
    "rotation-patterns": { label: "Rotation patterns", create: "RotationPatternCreate", update: "RotationPatternUpdate", columns: ["name", "days_on", "days_off", "is_active"] },
  };
  const labels = { full_name: "Full name", primary_phone: "Primary phone", work_email: "Work email", is_active: "Active", is_primary: "Primary", is_current: "Current version", is_dependent: "Dependent", is_next_of_kin: "Next of kin", department_id: "Department", position_id: "Position", supervisor_id: "Supervisor", home_location_id: "Home location", manager_employee_id: "Manager", parent_department_id: "Parent department", family_member_id: "Family member", project_id: "Project", location_id: "Location", skill_id: "Skill", document_id: "Supporting document", assignment_id: "Assignment", rotation_pattern_id: "Rotation pattern", asset_id: "Asset", asset_category_id: "Asset category", days_on: "Days on duty", days_off: "Days off duty", file_url: "Document link", is_primary_next_of_kin: "Primary next of kin", time_check_in: "Check-in time", time_check_out: "Check-out time", leave_start_date: "Start date", leave_end_date: "End date", leave_reason: "Reason" };
  function label(key) { return labels[key] || key.replaceAll("_", " ").replace(/^./, (c) => c.toUpperCase()); }
  function pretty(value) {
    if (value === null || value === undefined || value === "") return "—";
    if (typeof value === "boolean") return value ? "Yes" : "No";
    if (/^\d{4}-\d{2}-\d{2}$/.test(String(value))) return value;
    if (typeof value === "string" && /^[A-Z_]+$/.test(value)) return label(value.toLowerCase());
    return String(value);
  }
  function button(title, handler, className = "secondary") {
    const node = el("button", title, className); node.type = "button";
    node.addEventListener("click", () => { if (!busy) handler(); }); return node;
  }
  function message(value, error = false) {
    const node = $("workforce-notice"); node.textContent = value; node.hidden = !value;
    node.className = error ? "form-error" : "notice";
  }
  async function guarded(task) {
    await action(async () => {
      try { await task(); } catch (error) { if (session.user) message(error.message, true); }
    });
  }
  async function contracts() {
    if (!contractPromise) contractPromise = fetch("/openapi.json", { cache: "no-store" }).then(async (response) => {
      if (!response.ok) throw Error("Form definitions are unavailable. Restart the development API and try again.");
      return (await response.json()).components.schemas;
    }).catch((error) => { contractPromise = null; throw error; });
    return contractPromise;
  }
  function resolve(schema, schemas) {
    if (schema.$ref) return resolve(schemas[schema.$ref.split("/").pop()], schemas);
    if (schema.anyOf) return { ...resolve(schema.anyOf.find((item) => item.type !== "null"), schemas), ...schema, nullable: schema.anyOf.some((item) => item.type === "null") };
    if (schema.allOf?.length === 1) return { ...resolve(schema.allOf[0], schemas), ...schema };
    return schema;
  }
  function relation(key, id = employeeId) {
    const lookup = { department_id: "departments", parent_department_id: "departments", position_id: "positions", supervisor_id: "employees", manager_employee_id: "employees", project_id: "projects", location_id: "locations", home_location_id: "locations", rotation_pattern_id: "rotation-patterns", skill_id: "skills", asset_id: "assets", asset_category_id: "asset-categories" };
    if (lookup[key]) return `/api/v1/${lookup[key]}`;
    if (id && key === "family_member_id") return `/api/v1/employees/${id}/family`;
    if (id && key === "document_id") return `/api/v1/employees/${id}/documents`;
    if (id && key === "assignment_id") return `/api/v1/employees/${id}/assignments`;
    return null;
  }
  const itemName = (item) => item.full_name || item.name || item.title || item.assignment_number || [item.first_name, item.last_name].filter(Boolean).join(" ") || item.id;

  // Lookup pages stay bounded; search and Load more reach records beyond the first hundred.
  async function lookup(select, path, value, field, formError) {
    let page = 1;
    let items = [];
    let query = "";
    const area = el("div", undefined, "lookup-tools");
    const search = document.createElement("input"); search.type = "search";
    search.placeholder = `Find ${label(field).toLowerCase()}…`; search.setAttribute("aria-label", search.placeholder);
    const more = button("Load more", () => guardedLookup(false));
    const find = button("Find", () => { query = search.value.trim(); guardedLookup(true); });
    area.append(search, find, more); select.after(area);
    select.append(new Option("Choose…", ""));
    async function guardedLookup(reset) {
      if (reset) { page = 1; items = []; }
      select.disabled = true; more.disabled = true;
      try {
        const response = await api(`${path}?page=${page}&page_size=100${query ? `&search=${encodeURIComponent(query)}` : ""}`);
        const array = Array.isArray(response);
        items.push(...(array ? response : response.items));
        const selected = select.value || value || "";
        select.replaceChildren(new Option("Choose…", ""));
        for (const item of items) {
          if (field === "supervisor_id" && item.id === employeeId) continue;
          select.append(new Option(`${itemName(item)}${item.employee_number ? ` · ${item.employee_number}` : ""}`, item.id));
        }
        if (selected && !items.some((item) => item.id === selected)) select.append(new Option("Current selection (outside this page)", selected));
        select.value = selected;
        more.hidden = array || page >= response.pages;
        search.hidden = find.hidden = array;
        page += 1;
      } catch (error) {
        formError.textContent = `Could not load ${label(field).toLowerCase()}: ${error.message}`; formError.hidden = false;
        if (value && !select.querySelector(`option[value="${value}"]`)) select.append(new Option("Current selection", value));
        select.value = value || "";
      } finally { select.disabled = false; more.disabled = false; }
    }
    await guardedLookup(true);
  }

  async function form(title, schemaName, path, { record = null, done = null, upload = false, fields = null, contextId = employeeId, wizard = false, method = null, lookupTargets = {} } = {}) {
    $("workforce-form-title").textContent = title;
    const dialog = $("workforce-form-dialog");
    const content = $("workforce-form-content");
    content.replaceChildren(el("p", "Loading form…", "hint"));
    if (!dialog.open) dialog.showModal();
    let schemas;
    try {
      schemas = await contracts();
      if (!schemas[schemaName]) throw Error("The running API is out of date. Restart the Cestos API with the latest code, then reopen this form.");
    } catch (error) {
      const alert = el("p", error.message, "form-error");
      alert.setAttribute("role", "alert");
      content.replaceChildren(alert);
      return;
    }
    const schema = schemas[schemaName];
    if (!schema) throw Error(`This API does not yet support ${title.toLowerCase()}. Restart it after applying the latest migrations.`);
    const capturedId = contextId;
    $("workforce-form-title").textContent = title;
    const container = $("workforce-form-content"); container.replaceChildren();
    const formNode = el("form", undefined, "workforce-form");
    const errors = el("p", "", "form-error"); errors.id = "workforce-form-error"; errors.hidden = true; errors.setAttribute("role", "alert");
    const grid = el("div", undefined, "form-grid");
    const controls = [];
    const lookups = [];
    const properties = fields || schema.properties;
    const required = new Set(schema.required || []);
    const initial = {};
    for (const [key, spec] of Object.entries(properties)) {
      if (key === "organization_id" || key === "profile_photo_url") continue;
      const data = resolve(spec, schemas);
      const wrapper = el("div"); const caption = el("label", `${label(key)}${required.has(key) ? " *" : ""}`);
      const inputId = `wf-field-${key}`; caption.htmlFor = inputId;
      let input;
      const target = lookupTargets[key] ? `/api/v1/${lookupTargets[key]}` : relation(key, capturedId);
      if (target || data.enum) {
        input = document.createElement("select");
        if (data.enum) {
          if (!required.has(key)) input.append(new Option("Not specified", ""));
          for (const value of data.enum) input.append(new Option(pretty(value), value));
        }
      } else if (["notes", "bio", "description", "address", "residential_address", "restrictions", "termination_reason"].includes(key)) {
        input = document.createElement("textarea"); input.rows = 3; wrapper.className = "full-field";
      } else {
        input = document.createElement("input");
        input.type = data.type === "boolean" ? "checkbox" : data.format === "binary" ? "file" : data.format === "date" ? "date" : data.format === "date-time" ? "datetime-local" : data.format === "email" ? "email" : data.type === "integer" ? "number" : "text";
        if (input.type === "file") input.accept = ".pdf,.doc,.docx,.png,.jpg,.jpeg,.txt,.csv,.xls,.xlsx";
        if (data.minimum !== undefined) input.min = data.minimum;
        if (data.maximum !== undefined) input.max = data.maximum;
        if (data.maxLength) input.maxLength = data.maxLength;
        if (data.minLength) input.minLength = data.minLength;
      }
      input.id = inputId; input.name = key; input.required = required.has(key);
      const value = record ? record[key] : (spec.default ?? data.default);
      if (input.type === "checkbox") { input.checked = Boolean(value); wrapper.classList.add("checkbox-field"); }
      else if (input.type !== "file") input.value = value ?? "";
      initial[key] = value ?? null;
      controls.push({ key, input, data });
      wrapper.append(caption, input); grid.append(wrapper);
      if (target) lookups.push(() => lookup(input, target, value, key, errors));
    }
    const actions = el("div", undefined, "dialog-actions");
    const cancel = button("Cancel", () => $("workforce-form-dialog").close());
    const save = el("button", record ? "Save changes" : upload ? "Upload" : "Save record", "primary"); save.type = "submit";
    actions.append(cancel, save); formNode.append(grid, errors, actions); container.append(formNode);
    const onboarding = wizard ? employeeWizard(formNode, grid, controls, actions, save) : null;
    $("workforce-form-dialog").showModal();
    save.disabled = true;
    await Promise.all(lookups.map((run) => run()));
    save.disabled = false;
    controls[0]?.input.focus();
    formNode.addEventListener("submit", (event) => {
      event.preventDefault();
      if (onboarding && !onboarding.ready()) return;
      const payload = {};
      const multipart = new FormData();
      for (const { key, input, data } of controls) {
        let value = input.type === "checkbox" ? input.checked : input.type === "file" ? input.files[0] : input.value.trim();
        if (upload) { if (value !== "" && value !== undefined && value !== null) multipart.append(key, value); continue; }
        if (value === "") value = null;
        if (value !== null && data.type === "integer") value = Number(value);
        if (value !== null && data.format === "date-time") value = new Date(value).toISOString();
        if (record && value === initial[key]) continue;
        if (value === null && !data.nullable) continue;
        if (!record && value === null) continue;
        payload[key] = value;
      }
      action(async () => {
        save.textContent = "Saving…";
        try {
          if (!upload && record && !Object.keys(payload).length) { $("workforce-form-dialog").close(); return; }
          const saved = onboarding ? await onboarding.persist(payload) : upload ? await uploadFile(path, multipart) : await api(path, { method: method || (record ? "PATCH" : "POST"), body: payload });
          $("workforce-form-dialog").close();
          message("Saved successfully.");
          for (const key of Object.keys(nameCache)) nameCache[key] = null;
          if (done) await done(saved);
          else if (capturedId && employeeId === capturedId) await loadTab(Object.keys(configs).find(key => path.includes(configs[key].path)) || "profile");
        } finally { save.textContent = record ? "Save changes" : "Save record"; }
      }, errors.id);
    });
  }
  function employeeWizard(formNode, grid, controls, actions, save) {
    const titles = ["Personal details", "Employment", "Files", "Emergency contacts", "Review"];
    const steps = titles.map((title) => { const section = el("section", undefined, "onboarding-step"); section.append(el("h3", title)); return section; });
    const progress = el("ol", undefined, "onboarding-progress");
    titles.forEach((title) => progress.append(el("li", title)));
    formNode.prepend(progress); grid.replaceWith(...steps);
    const personal = el("div", undefined, "form-grid"), employment = el("div", undefined, "form-grid");
    steps[0].append(personal); steps[1].append(employment);
    const work = new Set(["department_id", "position_id", "department", "job_title", "employment_type", "employment_status", "hire_date", "probation_end_date", "confirmation_date", "contract_start_date", "contract_end_date", "termination_date", "termination_reason", "supervisor_id", "home_location_id", "notes"]);
    for (const {key,input} of controls) (work.has(key) ? employment : personal).append(input.parentElement);
    function fileField(title, accept) {
      const box = el("div", undefined, "upload-card"), caption = el("label", title), input = el("input");
      input.type = "file"; input.accept = accept; input.id = `onboard-${title.split(" ")[0].toLowerCase()}`; caption.htmlFor = input.id;
      input.addEventListener("change", () => { const file = input.files[0]; input.setCustomValidity(file && !accept.split(",").some(ext=>file.name.toLowerCase().endsWith(ext)) ? `Choose a supported file: ${accept}` : ""); });
      box.append(caption,input); steps[2].append(box); return input;
    }
    steps[2].append(el("p", "Add a profile photo and resume now, or add them later. Files are saved when you finish."));
    const photo = fileField("Profile photo", ".png,.jpg,.jpeg"), resume = fileField("Resume", ".pdf,.doc,.docx");
    const preview = el("img", undefined, "employee-photo"); preview.alt = "Profile photo preview"; preview.hidden = true; photo.after(preview);
    let previewUrl;
    photo.addEventListener("change", () => { if (previewUrl) URL.revokeObjectURL(previewUrl); preview.hidden = !photo.files.length; if (photo.files.length) { previewUrl = URL.createObjectURL(photo.files[0]); preview.src = previewUrl; } });
    $("workforce-form-dialog").addEventListener("close", () => { if (previewUrl) URL.revokeObjectURL(previewUrl); }, {once:true});
    const contacts = [], contactArea = el("div");
    steps[3].append(el("p", "Add as many contacts as needed. The first contact is the primary contact. Email is optional."), contactArea);
    function addContact() {
      const entry = { fields: {}, saved: false }, card = el("fieldset", undefined, "contact-card");
      card.append(el("legend", "Emergency contact")); const fields = el("div", undefined, "form-grid");
      for (const [key,title,type] of [["full_name","Full name","text"],["relationship","Relationship","text"],["primary_phone","Contact phone","tel"],["email","Email (optional)","email"],["address","Address","text"]]) {
        const wrap = el("div"), caption = el("label", title), input = el(key === "address" ? "textarea" : "input");
        if (key !== "address") input.type = type;
        input.id = `contact-${crypto.randomUUID()}-${key}`; caption.htmlFor = input.id; input.required = key !== "email";
        input.maxLength = key === "full_name" ? 200 : key === "primary_phone" ? 50 : key === "relationship" ? 100 : 1000;
        entry.fields[key] = input; wrap.append(caption,input); fields.append(wrap);
      }
      card.append(fields,button("Remove contact", () => { contacts.splice(contacts.indexOf(entry),1); card.remove(); }));
      contacts.push(entry); contactArea.append(card);
    }
    steps[3].append(button("+ Add emergency contact", addContact));
    let stage = 0, savedEmployee = null, photoDocument = null, photoSaved = false, resumeSaved = false;
    const back = button("Back", () => show(stage-1)), next = button("Continue →", () => { if (valid()) show(stage+1); }, "primary");
    actions.insertBefore(back,save); actions.insertBefore(next,save);
    formNode.noValidate = true;
    function valid() { return [...steps[stage].querySelectorAll("input,select,textarea")].every(input => input.reportValidity()); }
    function show(index) {
      stage = index; steps.forEach((step,i) => step.hidden = i !== stage);
      [...progress.children].forEach((item,i) => { if(i===stage)item.setAttribute("aria-current","step"); else item.removeAttribute("aria-current"); });
      back.hidden = stage === 0 || !!savedEmployee; next.hidden = stage === 4; save.hidden = stage !== 4; save.textContent = savedEmployee ? "Retry remaining items" : "Create employee";
      if(stage === 4) {
        steps[4].replaceChildren(el("h3","Review employee"));
        const summary = el("dl",undefined,"detail-list");
        for(const {key,input} of controls) if(input.value) summary.append(el("dt",label(key)),el("dd",input.tagName === "SELECT" ? input.selectedOptions[0]?.textContent : input.value));
        summary.append(el("dt","Profile photo"),el("dd",photo.files[0]?.name || "Not added"),el("dt","Resume"),el("dd",resume.files[0]?.name || "Not added"));
        steps[4].append(summary,el("h3",`${contacts.length} emergency contacts`));
        for(const contact of contacts) steps[4].append(el("p",Object.values(contact.fields).map(input=>input.value).filter(Boolean).join(" · ")));
      }
      $("workforce-form-dialog").scrollTop = 0;
    }
    show(0);
    return {
      ready() { if(stage !== 4) { if(valid()) show(stage+1); return false; } return true; },
      async persist(payload) {
        try {
          if(!savedEmployee) savedEmployee = await api("/api/v1/employees",{method:"POST",body:payload});
          back.hidden = true;
          const base = `/api/v1/employees/${savedEmployee.id}`;
          if(photo.files[0] && !photoSaved) {
            if(!photoDocument) { const body = new FormData(); body.append("file",photo.files[0]); body.append("title","Profile photo"); body.append("document_type","OTHER"); photoDocument = await uploadFile(`${base}/documents/upload`,body); }
            await api(base,{method:"PATCH",body:{profile_photo_url:`${base}/documents/${photoDocument.id}/download`}}); photoSaved = true;
          }
          if(resume.files[0] && !resumeSaved) { const body = new FormData(); body.append("file",resume.files[0]); body.append("title",resume.files[0].name); await uploadFile(`${base}/resumes/upload`,body); resumeSaved = true; }
          for(const [index,contact] of contacts.entries()) if(!contact.saved) {
            const body = Object.fromEntries(Object.entries(contact.fields).map(([key,input])=>[key,input.value.trim()]).filter(([,value])=>value));
            await api(`${base}/emergency-contacts`,{method:"POST",body:{...body,is_primary:index===0,priority:Math.min(index+1,10)}}); contact.saved = true;
          }
          return savedEmployee;
        } catch(error) { throw Error(savedEmployee ? `Employee created, but some attachments or contacts were not saved. Retry to continue with the remaining items. ${error.message}` : error.message); }
      }
    };
  }
  async function uploadFile(path, body) {
    try {
      if (session.refresh && Date.now() >= session.expiresAt - 30000) await refreshSession();
      try { return await sendForm(path, body); }
      catch (error) { if (error.status !== 401 || !session.refresh) throw error; await refreshSession(); return await sendForm(path, body); }
    } catch (error) { if (error.status === 401) { signOutLocally(); showError("login-error", error.message); } throw error; }
  }

  function table(columns, records, rowActions = null, names = {}) {
    const wrap = el("div", undefined, "table-scroll"); const node = el("table");
    const head = el("thead"); const tr = el("tr");
    for (const key of columns) { const th = el("th", label(key)); th.scope = "col"; tr.append(th); }
    if (rowActions) tr.append(el("th", "Actions")); head.append(tr); node.append(head);
    const body = el("tbody");
    if (!records.length) { const row = el("tr"); const cell = el("td", "No records yet.", "table-empty"); cell.colSpan = columns.length + Number(Boolean(rowActions)); row.append(cell); body.append(row); }
    for (const record of records) {
      const row = el("tr");
      for (const key of columns) row.append(el("td", pretty(names[key]?.get(record[key]) || record[key])));
      if (rowActions) { const cell = el("td"); const actions = el("div", undefined, "row-actions"); rowActions(actions, record); cell.append(actions); row.append(cell); }
      body.append(row);
    }
    node.append(body); wrap.append(node); return wrap;
  }
  async function namesFor(columns, records) {
    const names = {};
    await Promise.all(columns.filter((key) => key.endsWith("_id") && relation(key)).map(async (key) => {
      const ids = new Set(records.map((record) => record[key]).filter(Boolean));
      if (!ids.size) return;
      const map = new Map(); names[key] = map;
      try {
        const path = relation(key); let page = 1;
        while (ids.size) {
          const result = await api(`${path}?page=${page}&page_size=100`);
          for (const item of Array.isArray(result) ? result : result.items) { map.set(item.id, itemName(item)); ids.delete(item.id); }
          if (Array.isArray(result) || page >= result.pages) break;
          page += 1;
        }
      } catch { /* The UUID remains visible if related records cannot be read. */ }
    }));
    return names;
  }
  function confirmAction(title, path, done, body = undefined, method = "POST") {
    $("workforce-form-title").textContent = title;
    const area = $("workforce-form-content"); area.replaceChildren(el("p", "This changes the selected record. Its history will be retained."));
    const error = el("p", "", "form-error"); error.id = "workforce-confirm-error"; error.hidden = true; error.setAttribute("role", "alert");
    area.append(error, button("Cancel", () => $("workforce-form-dialog").close()), button(title, () => action(async () => {
      await api(path, { method, body }); $("workforce-form-dialog").close(); message("Record updated."); await done();
    }, error.id), "primary"));
    $("workforce-form-dialog").showModal();
  }
  async function open(id, navigate = true) {
    const ticket = ++generation;
    const value = await api(`/api/v1/employees/${id}`);
    if (ticket !== generation || !session.user) return;
    employeeId = id; employee = value;
    $("workforce-title").textContent = `${value.first_name} ${value.last_name}`;
    $("workforce-number").textContent = value.employee_number;
    if (navigate && location.hash !== `#employees/${id}`) history.pushState(null, "", `#employees/${id}`);
    showView("employee-details"); message("");
    const grid = $("workforce-content"); grid.replaceChildren();
    for (const [key,title] of [["profile","Personal & employment details"], ...Object.entries(configs).map(([key,cfg])=>[key,cfg.label]), ["activity","Activity"]]) {
      const card = el("article",undefined,"employee-info-card");
      const heading = el("h2",title); heading.id = `employee-card-title-${key}`; card.setAttribute("aria-labelledby",heading.id);
      const body = el("div"); body.id = `employee-card-${key}`; card.append(heading,body); grid.append(card);
    }
    $("workforce-title").focus();
    await Promise.all([...(["profile",...Object.keys(configs),"activity"].map(key=>loadTab(key))), HR.employee(id)]);
  }

  async function profile(content) {
    employee = await api(`${root()}`);
    if (employee.profile_photo_url?.startsWith(`${root()}/documents/`) && employee.profile_photo_url.endsWith("/download")) {
      try {
        const {blob} = await apiBlob(employee.profile_photo_url);
        const photo = el("img", undefined, "employee-photo"); photo.alt = `${employee.first_name} ${employee.last_name}`;
        const url = URL.createObjectURL(blob); photo.onload = photo.onerror = () => URL.revokeObjectURL(url); photo.src = url; content.append(photo);
      } catch { content.append(el("p", "Profile photo unavailable.", "hint")); }
    }
    const toolbar = el("div", undefined, "workforce-actions");
    toolbar.append(button("Edit employee", () => guarded(() => form("Edit employee", "EmployeeUpdate", root(), { record: employee, done: () => loadTab("profile") }))));
    const photoInput = el("input"); photoInput.type = "file"; photoInput.accept = ".png,.jpg,.jpeg"; photoInput.hidden = true;
    toolbar.append(photoInput, button("Upload profile photo", () => photoInput.click()));
    photoInput.addEventListener("change", () => {
      const file = photoInput.files[0]; if (!file) return;
      guarded(async () => {
        if (!/\.(png|jpe?g)$/i.test(file.name)) throw Error("Choose a PNG or JPEG photo.");
        const body = new FormData(); body.append("file", file); body.append("title", "Profile photo"); body.append("document_type", "OTHER");
        const document = await uploadFile(`${root()}/documents/upload`, body);
        await api(root(), {method:"PATCH", body:{profile_photo_url:`${root()}/documents/${document.id}/download`}});
        await loadTab("profile");
      });
    });
    const status = employee.is_active ? "archive" : "restore";
    toolbar.append(button(`${label(status)} employee`, () => confirmAction(`${label(status)} employee`, `${root()}/${status}`, async () => { await loadTab("profile"); await list(pagers.employees.page); })));
    content.append(toolbar);
    const groups = {
      "Personal": ["first_name","middle_name","last_name","preferred_name","gender","date_of_birth","nationality","marital_status","bio"],
      "Contact & address": ["personal_email","work_email","primary_phone","secondary_phone","residential_address","city","county_or_region","country"],
      "Employment": ["employee_number","department","department_id","position_id","job_title","employment_type","employment_status","supervisor_id","home_location_id","availability_status","is_active"],
      "Dates & notes": ["hire_date","probation_end_date","confirmation_date","contract_start_date","contract_end_date","termination_date","termination_reason","notes"]
    };
    const personalGrid = el("div",undefined,"personal-info-grid");
    const relatedNames = await namesFor(Object.values(groups).flat(), [employee]);
    for (const [title,fields] of Object.entries(groups)) {
      const section = el("section"); section.append(el("h3",title)); const dl = el("dl",undefined,"detail-list");
      for(const key of fields) dl.append(el("dt",label(key)),el("dd",pretty(relatedNames[key]?.get(employee[key]) || employee[key])));
      section.append(dl); personalGrid.append(section);
    }
    content.append(personalGrid);
    try {
      const overview = await api(`${root()}/overview`);
      const summary = el("dl", undefined, "detail-list");
      for (const [key, value] of [["Department", overview.department?.name], ["Position", overview.position?.title], ["Supervisor", overview.supervisor && itemName(overview.supervisor)], ["Current project", overview.current_project_name], ["Current location", overview.current_location_name], ["Availability", overview.availability_status], ["Compliance", overview.compliance.status], ["Emergency contact", overview.primary_emergency_contact?.full_name], ["Current resume", overview.current_resume?.title]]) summary.append(el("dt", key), el("dd", pretty(value)));
      content.append(el("h3", "Current work and readiness"), summary);
      if (overview.compliance.issues.length) {
        const issues = el("ul", undefined, "compliance-list");
        for (const issue of overview.compliance.issues) issues.append(el("li", `${pretty(issue.severity)}: ${issue.message}`));
        content.append(issues);
      }
    } catch (error) {
      if (error.status === 403) content.append(el("p", "Your account can view basic employee details. Full profile information requires additional permission.", "access-note"));
      else content.append(el("p", `Work readiness unavailable: ${error.message}`, "form-error"));
    }
  }
  function recordCards(columns, records, rowActions = null, names = {}) {
    const list = el("div",undefined,"employee-records");
    if (!records.length) { list.append(el("p","No records added yet.","empty-records")); return list; }
    for(const record of records) {
      const section = el("section",undefined,"employee-record"); const details = el("dl",undefined,"detail-list");
      for(const [key,value] of Object.entries(record)) {
        if (["id","organization_id","employee_id","created_by_id","updated_by_id","file_url","storage_key"].includes(key) || value === null || typeof value === "object") continue;
        details.append(el("dt",label(key)),el("dd",pretty(names[key]?.get(value) || value)));
      }
      section.append(details);
      if(rowActions) {const actions = el("div",undefined,"row-actions"); rowActions(actions,record); section.append(actions);}
      list.append(section);
    }
    return list;
  }
  async function loadTab(key) {
    const ticket = generation; const captured = employeeId;
    const target = $(`employee-card-${key}`); if (!target) return;
    const content = el("div"); target.replaceChildren(el("p", "Loading…", "hint"));
    try {
      if (key === "profile") await profile(content);
      else if (key === "activity") {
        const records = await api(`${root()}/activity`);
        content.append(recordCards(["occurred_at", "action", "summary"], records));
      } else {
        const cfg = configs[key];
        const records = await api(`${root()}/${cfg.path}`);
        const tools = el("div", undefined, "workforce-actions");
        if ((key !== "time_logs" || HR.access.time_log_create) && (key !== "leave_requests" || HR.access.leave_create)) tools.append(button(`Add ${cfg.label.toLowerCase()}`, () => guarded(() => form(`Add ${cfg.label.toLowerCase()}`, cfg.create, `${root()}/${cfg.path}`, {done: () => loadTab(key)})), "primary"));
        if (cfg.upload) tools.append(button("Upload file", () => guarded(() => upload(cfg))));
        if (key === "assignments") tools.append(button("Transfer employee", () => guarded(() => form("Transfer employee", "EmployeeTransferRequest", `${root()}/transfer`, {done: () => loadTab(key)}))));
        content.append(tools);
        const names = await namesFor(cfg.columns, records);
        content.append(recordCards(cfg.columns, records, (actions, row) => {
          if (cfg.update) actions.append(button("Edit", () => guarded(() => form(`Edit ${cfg.label.toLowerCase()}`, cfg.update, `/api/v1/${cfg.item}/${row.id}`, { record: row, done: () => loadTab(key) }))));
          if (key === "leave_requests" && row.attachment_url) actions.append(button("Download leave letter", () => guarded(() => HR.downloadLeaveLetter(row.id))));
          for (const op of cfg.actions) {
            if (key === "leave_requests") {
              if (row.status !== "PENDING" || !HR.access[`leave_${op}`]) continue;
              actions.append(button(label(op), () => confirmAction(`${label(op)} leave request`, `/api/v1/employees/${row.id}/${op}`, () => loadTab(key), undefined, "PATCH")));
              continue;
            }
            if (op === "archive" && row.is_active === false) continue;
            if (["complete", "cancel"].includes(op) && !["ACTIVE", "PLANNED"].includes(row.status)) continue;
            if (op === "set-current" && (row.is_current || !row.is_active)) continue;
            if (op === "set-primary" && (row.is_primary || !row.is_active)) continue;
            if (op === "revoke" && row.status === "REVOKED") continue;
            actions.append(button(label(op.replaceAll("-", "_")), () => confirmAction(label(op.replaceAll("-", "_")), `/api/v1/${cfg.item}/${row.id}/${op}`, () => loadTab(key))));
          }
          if (cfg.upload) {
            const remote = /^https?:\/\//i.test(row.file_url || "");
            if (remote) {
              const link = el("a", "Open link", "secondary resource-link"); link.href = row.file_url; link.target = "_blank"; link.rel = "noopener noreferrer"; actions.append(link);
            } else actions.append(button("Download", () => guarded(async () => {
              const result = await apiBlob(`${root()}/${cfg.path}/${row.id}/download`); downloadBlob(result.blob, result.filename);
            })));
          }
        }, names));
        if (key === "rotations") content.append(el("p", "Rotation cycles can be created and reviewed here. Editing an existing cycle is not exposed by the current API.", "hint"));
      }
      if (ticket === generation && captured === employeeId && session.user) target.replaceChildren(content);
    } catch (error) {
      if (ticket === generation && session.user) target.replaceChildren(el("p", error.message, "form-error"));
    }
  }
  async function upload(cfg) {
    const fields = { file: { type: "string", format: "binary" }, title: { type: "string", maxLength: 200 }, notes: { type: "string" } };
    if (cfg.path === "documents") {
      const schemas = await contracts();
      for (const key of ["document_type", "document_number", "issue_date", "expiry_date", "issuing_authority"]) fields[key] = schemas.EmployeeDocumentCreate.properties[key];
    }
    await form(`Upload ${cfg.path === "resumes" ? "resume" : "document"}`, cfg.create, `${root()}/${cfg.path}/upload`, { upload: true, fields });
    $("wf-field-file").required = true;
  }
  async function createEmployee() {
    if (!session.user) return;
    $("record-dialog").close();
    await guarded(() => form("New employee", "EmployeeCreate", "/api/v1/employees", { wizard: true, contextId: null, done: async (record) => {
      history.replaceState(null, "", "#employees"); showView("employees"); await list(1); await open(record.id);
    } }));
  }
  async function catalogue(kind) {
    const cfg = setup[kind];
    const records = await api(`/api/v1/${kind}`);
    const area = $("workforce-form-content"); $("workforce-form-title").textContent = cfg.label;
    const lookupTargets = kind === "departments" ? { parent_department_id: "departments", manager_employee_id: "employees" } : {};
    area.replaceChildren(button(`Add ${cfg.label.toLowerCase()}`, () => guarded(() => form(`Add ${cfg.label.toLowerCase()}`, cfg.create, `/api/v1/${kind}`, { contextId: null, lookupTargets, done: () => catalogue(kind) })), "primary"));
    const names = await namesFor(cfg.columns, records);
    area.append(table(cfg.columns, records, (actions, row) => actions.append(button("Edit", () => guarded(() => form(`Edit ${cfg.label.toLowerCase()}`, cfg.update, `/api/v1/${kind}/${row.id}`, { record: row, contextId: null, lookupTargets, done: () => catalogue(kind) })))), names));
    if (!$("workforce-form-dialog").open) $("workforce-form-dialog").showModal();
  }
  const filters = {};
  function buildTools() {
    const area = $("employee-tools");
    const panel = el("details", undefined, "workforce-filters"); panel.append(el("summary", "Filter workforce"));
    const fields = el("div", undefined, "form-grid");
    const options = {
      employment_status: ["ACTIVE", "ON_LEAVE", "OFF_ROTATION", "SUSPENDED", "EXITED", "RESIGNED", "TERMINATED", "RETIRED", "DECEASED"],
      employment_type: ["FULL_TIME", "PART_TIME", "CONTRACT", "CASUAL", "TEMPORARY", "CONSULTANT", "INTERN"],
      availability_status: ["AVAILABLE", "ASSIGNED", "ON_LEAVE", "OFF_ROTATION", "TRAINING", "SUSPENDED", "UNAVAILABLE"],
      is_active: [["true", "Active records"], ["false", "Archived records"]],
      unassigned_only: [["true", "Unassigned only"]],
      rotation_status: ["PLANNED", "ON_SITE", "OFF_ROTATION", "COMPLETED", "CANCELLED"],
      sort_by: ["created_at", "employee_number", "first_name", "last_name", "hire_date"],
      sort_dir: [["asc", "Ascending"], ["desc", "Descending"]],
      document_expiring_within_days: [["30", "Within 30 days"], ["60", "Within 60 days"], ["90", "Within 90 days"]],
      contract_expiring_within_days: [["30", "Within 30 days"], ["60", "Within 60 days"], ["90", "Within 90 days"]],
    };
    for (const [key, values] of Object.entries(options)) {
      const wrap = el("div"); const caption = el("label", label(key)); caption.htmlFor = `wf-filter-${key}`;
      const select = el("select"); select.id = caption.htmlFor;
      select.append(new Option("Any / default", ""));
      for (const value of values) select.append(new Option(Array.isArray(value) ? value[1] : pretty(value), Array.isArray(value) ? value[0] : value));
      filters[key] = select; wrap.append(caption, select); fields.append(wrap);
    }
    // Reference filters use the same searchable, paginated lookup controls as forms.
    for (const key of ["department_id", "position_id", "project_id", "location_id", "supervisor_id", "skill_id"]) {
      const wrap = el("div"); const caption = el("label", label(key)); caption.htmlFor = `wf-filter-${key}`;
      const select = el("select"); select.id = caption.htmlFor; select.append(new Option("Any", "")); filters[key] = select;
      wrap.append(caption, select); fields.append(wrap);
    }
    const errors = el("p", "", "form-error"); errors.hidden = true;
    let loaded = false;
    panel.addEventListener("toggle", () => {
      if (!panel.open || loaded) return; loaded = true;
      for (const key of Object.keys(filters).filter((key) => key.endsWith("_id"))) lookup(filters[key], relation(key), null, key, errors);
    });
    panel.append(fields, errors, button("Apply filters", () => action(() => list(1)), "primary"), button("Reset filters", () => {
      for (const select of Object.values(filters)) select.value = ""; $("employee-search").value = ""; action(() => list(1));
    }));
    area.append(panel);
    const masters = el("details", undefined, "workforce-setup"); masters.append(el("summary", "Workforce setup"));
    for (const [kind, cfg] of Object.entries(setup)) masters.append(button(cfg.label, () => guarded(() => catalogue(kind))));
    area.append(masters);
  }
  async function dashboard() {
    const node = $("workforce-summary");
    try {
      const data = await api("/api/v1/employees/dashboard-summary"); node.replaceChildren();
      for (const [key, title] of [["total_employees", "Employees"], ["assigned_employees", "Assigned"], ["available_employees", "Available"], ["off_rotation", "Off rotation"], ["expiring_documents", "Documents expiring"], ["employees_without_emergency_contact", "Missing emergency contact"]]) {
        const card = el("article"); card.append(el("strong", data[key]), el("span", title)); node.append(card);
      }
    } catch (error) { node.replaceChildren(el("p", `Workforce summary unavailable: ${error.message}`, "hint")); }
  }
  async function list(page = 1) {
    const query = new URLSearchParams({ page, page_size: 20 });
    const search = $("employee-search").value.trim(); if (search) query.set("search", search);
    for (const [key, select] of Object.entries(filters)) if (select.value) query.set(key, select.value);
    const pager = pagers.employees;
    try {
      const result = await api(`/api/v1/employees?${query}`); pager.page = result.page; pager.pages = result.pages;
      $("employee-rows").replaceChildren();
      for (const item of result.items) addRow("employee-rows", [`${item.first_name} ${item.last_name}`, item.employee_number, pretty(item.job_title), `${pretty(item.employment_status)} · ${item.is_active ? pretty(item.availability_status) : "Archived"}`], () => guarded(() => open(item.id)));
      if (!result.items.length) emptyTable("employee-rows", 4, "No employees match these filters.");
      $("employee-count").textContent = `${result.total} employees · select a name to open their profile`;
      $("employee-page-info").textContent = `Page ${result.pages ? result.page : 0} of ${result.pages}`;
      await dashboard();
    } catch (error) { pager.page = 1; pager.pages = 0; emptyTable("employee-rows", 4, error.message); $("employee-count").textContent = "Employee list unavailable"; $("employee-page-info").textContent = ""; throw error; }
    finally { pagination(); }
  }
  function clear() {
    generation += 1; employeeId = null; employee = null;
    for (const id of ["workforce-content", "workforce-form-content", "workforce-summary"]) $(id).replaceChildren();
    for (const select of Object.values(filters)) select.value = "";
    message("");
  }
  buildTools();
  return { open, list, createEmployee, clear, form };
})();



const HR = (() => {
  let access = {};
  const base = '/api/v1/hr';
  function btn(title,task){const b=el('button',title,'secondary');b.type='button';b.onclick=()=>action(task);return b;}
  function card(title,parent){const c=el('article',undefined,'employee-info-card');c.append(el('h2',title));parent.append(c);return c;}
  function values(data,parent){const dl=el('dl',undefined,'detail-list');for(const [key,value] of Object.entries(data)){if(value==null||key==='id')continue;dl.append(el('dt',key.replaceAll('_',' ')),el('dd',String(value)));}parent.append(dl);}
  async function initialize(){access=await api(`${base}/access`);document.querySelector('[data-view="hr-settings"]').hidden=!access.alerts_manage;document.querySelector('[data-view="my-profile"]').hidden=!access.linked;}
  async function edit(title,fields,save){
    $('hr-title').textContent=title;const form=el('form');const grid=el('div',undefined,'form-grid');const inputs={};
    for(const [key,cfg] of Object.entries(fields)){
      const wrap=el('div');const label=el('label',cfg.label||key.replaceAll('_',' '));const input=el(cfg.options?'select':cfg.type==='textarea'?'textarea':'input');input.id=`hr-${key}`;label.htmlFor=input.id;
      if(cfg.options){input.multiple=!!cfg.multiple;for(const [value,name] of cfg.options)input.append(new Option(name,value));if(cfg.multiple)for(const option of input.options)option.selected=(cfg.value||[]).includes(option.value);else input.value=cfg.value??'';}
      else {if(input.tagName==='INPUT')input.type=cfg.type||'text';else input.rows=3;if(cfg.type!=='file')input.value=cfg.value??'';if(cfg.accept)input.accept=cfg.accept;if(cfg.min!==undefined)input.min=cfg.min;if(cfg.step)input.step=cfg.step;}
      input.required=!!cfg.required;if(cfg.maxLength)input.maxLength=cfg.maxLength;inputs[key]=input;wrap.append(label,input);grid.append(wrap);
    }
    const error=el('p','','form-error');error.id='hr-error';error.hidden=true;error.setAttribute('role','alert');const submit=el('button','Save','primary');submit.type='submit';const actions=el('div',undefined,'dialog-actions');actions.append(submit);form.append(grid,error,actions);$('hr-form-content').replaceChildren(form);$('hr-dialog').showModal();
    form.onsubmit=event=>{event.preventDefault();const data={};for(const [key,input] of Object.entries(inputs))data[key]=input.type==='file'?(input.files[0]||null):input.multiple?[...input.selectedOptions].map(o=>o.value):input.value.trim();action(async()=>{await save(data);$('hr-dialog').close();},'hr-error');};
  }
  async function employee(id){
    if(access.salary_read){$('hr-salary-card')?.remove();const panel=card('Salary history',$('workforce-content'));panel.id='hr-salary-card';try{const rows=await api(`${base}/employees/${id}/salaries`);
      if(access.salary_manage)panel.append(btn('Add salary',()=>edit('Add salary',{
        amount:{required:true,type:'number',min:0,step:'0.01'},currency:{required:true,value:'USD'},pay_period:{required:true,options:['HOURLY','DAILY','WEEKLY','MONTHLY','ANNUAL'].map(x=>[x,x]),value:'MONTHLY'},start_date:{required:true,type:'date'},end_date:{type:'date'},notes:{}
      },async data=>{if(!data.end_date)delete data.end_date;await api(`${base}/employees/${id}/salaries`,{method:'POST',body:data});panel.remove();await employee(id);} )));
      if(!rows.length)panel.append(el('p','No salary records yet.','hint'));
      for(const row of rows){const section=el('section',undefined,'employee-record');values(row,section);if(access.salary_manage&&!row.end_date)section.append(btn('End salary period',()=>edit('End salary period',{end_date:{required:true,type:'date'}},async data=>{await api(`${base}/salaries/${row.id}/end`,{method:'POST',body:data});panel.remove();await employee(id);})));panel.append(section);}
    }catch(error){panel.append(el('p',error.message,'form-error'));}}
    if(access.superadmin&&!$('hr-account-card')){const panel=card('Linked account',$('workforce-content'));panel.id='hr-account-card';try{const row=await api(`${base}/employees/${id}/account`);values(row,panel);
      const refresh=async()=>{panel.remove();await employee(id);};
      if(!row.user_id)panel.append(btn('Link or create account',async()=>{await api(`${base}/employees/${id}/account/link`,{method:'POST'});await refresh();}));
      else{panel.append(btn('Change email & send reset',()=>edit('Change account email',{email:{type:'email',required:true,value:row.email}},async data=>{await api(`${base}/employees/${id}/account/email`,{method:'PUT',body:data});await refresh();})),btn('Send password reset',()=>edit('Send reset and revoke current sessions',{},async()=>{await api(`${base}/employees/${id}/account/reset`,{method:'POST'});await refresh();})));}
    }catch(error){panel.append(el('p',error.message,'form-error'));}}
  }
  async function editMyDetails(data){
    const fields = {};
    for(const [key,title,maxLength] of [['preferred_name','Preferred name',100],['primary_phone','Primary phone',50],['secondary_phone','Secondary phone',50],['residential_address','Residential address',1000],['city','City',100],['county_or_region','County / region',100],['country','Country',100]])
      fields[key]={label:title,value:data[key],maxLength,type:key==='residential_address'?'textarea':key.includes('phone')?'tel':'text'};
    await edit('Edit my personal details',fields,async values=>{
      const changes={};for(const [key,value] of Object.entries(values))if((value||null)!==(data[key]||null))changes[key]=value||null;
      await api(`${base}/me`,{method:'PATCH',body:changes});await self();notice('Your personal details were updated.');
    });
  }
  async function editMyContact(row=null){
    const fields={};
    for(const [key,title,maxLength] of [['full_name','Full name',200],['relationship','Relationship',100],['primary_phone','Contact phone',50],['secondary_phone','Secondary phone (optional)',50],['address','Address',1000],['email','Email (optional)',320]])
      fields[key]={label:title,value:row?.[key],maxLength,required:!['secondary_phone','email'].includes(key),type:key==='address'?'textarea':key==='email'?'email':key.includes('phone')?'tel':'text'};
    await edit(row?'Edit emergency contact':'Add emergency contact',fields,async data=>{
      data.email=data.email||null;data.secondary_phone=data.secondary_phone||null;
      await api(`${base}/me/emergency-contacts${row?'/'+row.id:''}`,{method:row?'PUT':'POST',body:data});await self();notice('Emergency contact saved.');
    });
  }
  function logActivity(){
    const today=new Date();const localDate=new Date(today.getTime()-today.getTimezoneOffset()*60000).toISOString().slice(0,10);
    return edit('Log my activity',{
      date:{type:'date',required:true,value:localDate},
      check_in:{label:'Start time (optional)',type:'datetime-local'},
      check_out:{label:'End time (optional)',type:'datetime-local'},
      notes:{label:'Activity / work completed',type:'textarea',required:true}
    },async data=>{
      const body={...data,check_in:data.check_in?new Date(data.check_in).toISOString():null,check_out:data.check_out?new Date(data.check_out).toISOString():null};
      if(body.check_out&&(!body.check_in||body.check_out<=body.check_in))throw Error('End time must be after start time');
      await api(`${base}/me/time-logs`,{method:'POST',body});await self();
    });
  }
  async function downloadLeaveLetter(id){
    const result=await apiBlob(`${base}/leave-requests/${id}/attachment`);downloadBlob(result.blob,result.filename);
  }
  function bookLeave(){
    return edit('Request leave',{
      start_date:{label:'First day of leave',type:'date',required:true},
      end_date:{label:'Last day of leave (inclusive)',type:'date',required:true},
      reason:{type:'textarea',required:true},
      letter:{label:'Leave request letter (optional)',type:'file',accept:'.pdf,.doc,.docx,.png,.jpg,.jpeg,.txt,.xls,.xlsx,.csv'}
    },async data=>{
      if(data.end_date<data.start_date)throw Error('Last day must be on or after the first day');
      const {letter,...body}=data;
      if(letter){
        const form=new FormData();for(const [key,value] of Object.entries(body))form.append(key,value);form.append('file',letter);
        await sendForm(`${base}/me/leave-requests/upload`,form);
      }else await api(`${base}/me/leave-requests`,{method:'POST',body});
      await self();
    });
  }
  async function myActivity(area){
    for(const [path,title,add,fields] of [
      ['time-logs','My activity & time logs',logActivity,['date','check_in','check_out','notes','status']],
      ['leave-requests','My leave requests',bookLeave,['start_date','end_date','reason','status','approved_at']]
    ]){
      const panel=card(title,area);panel.append(btn(path==='time-logs'?'Log activity':'Request leave',add));
      panel.append(el('p',path==='time-logs'?'Record work completed, with optional start and end times.':'Requests remain pending until reviewed by an authorized approver.','hint'));
      try{
        const rows=await api(`${base}/me/${path}`);
        if(!rows.length)panel.append(el('p','No records yet.','hint'));
        for(const row of rows){const section=el('section',undefined,'employee-record');values(Object.fromEntries(fields.map(key=>[key,row[key]])),section);if(path==='leave-requests'&&row.attachment_url)section.append(btn('Download leave letter',()=>downloadLeaveLetter(row.id)));panel.append(section);}
      }catch(error){panel.append(el('p',error.message,'form-error'));}
    }
  }
  async function self(){
    const area=$('my-profile-content');area.replaceChildren();
    try{
      const data=await api(`${base}/me`);
      await myActivity(area);
      const details=card('Personal & employment details',area);
      details.append(btn('Edit my personal details',()=>editMyDetails(data)),el('p','You can update your preferred name, phone numbers and address. For legal identity, email or employment corrections, contact HR.','hint'));
      values(Object.fromEntries(Object.entries(data).filter(([,v])=>!Array.isArray(v))),details);
      for(const [key,rows] of Object.entries(data).filter(([,v])=>Array.isArray(v))){
        const panel=card(key.replaceAll('_',' '),area);
        if(key==='emergency_contacts')panel.append(btn('+ Add emergency contact',()=>editMyContact()),el('p','Keep a primary contact available. Choose a replacement before removing your current primary contact.','hint'));
        else panel.append(el('p','Managed by HR · read only','hint'));
        if(!rows.length)panel.append(el('p','No records yet.','hint'));
        for(const row of rows){
          const section=el('section',undefined,'employee-record');values(row,section);
          if(key==='emergency_contacts'){
            const actions=el('div',undefined,'row-actions');actions.append(btn('Edit contact',()=>editMyContact(row)));
            if(!row.is_primary)actions.append(btn('Make primary',async()=>{await api(`${base}/me/emergency-contacts/${row.id}/primary`,{method:'POST'});await self();}),btn('Remove contact',()=>edit('Remove emergency contact? History will be retained.',{},async()=>{await api(`${base}/me/emergency-contacts/${row.id}/archive`,{method:'POST'});await self();})));
            section.append(actions);
          }
          if(key==='contracts')section.append(btn('Download contract',async()=>{
            const result=await apiBlob(`${base}/me/contracts/${row.id}/download`);const url=URL.createObjectURL(result.blob);const a=el('a');a.href=url;a.download=result.filename;a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
          }));
          panel.append(section);
        }
      }
    }catch(error){area.append(el('p',error.message,'form-error'));}
  }
  async function notifications(){const area=$('notifications-content');area.replaceChildren();const rows=await api(`${base}/notifications`);if(!rows.length)area.append(el('p','You have no notifications.'));for(const row of rows){const panel=card(row.read_at?'Read':'New reminder',area);panel.append(el('p',row.message),el('small',new Date(row.created_at).toLocaleString()));if(!row.read_at)panel.append(btn('Mark read',async()=>{await api(`${base}/notifications/${row.id}/read`,{method:'POST'});await notifications();}));}}
  async function ruleForm(row=null){
    const users=await api(`${base}/alert-recipients`);
    const employees=[]; let page=1;
    for(;;){const data=await api(`/api/v1/employees?page=${page}&page_size=100`);employees.push(...data.items);if(page>=data.pages)break;page++;}
    await edit(row?'Edit reminder':'New contract reminder',{
      name:{required:true,value:row?.name},employee_id:{label:'Applies to',options:[['','All employees'],...employees.map(e=>[e.id,`${e.first_name} ${e.last_name} · ${e.employee_number}`])],value:row?.employee_id||''},lead_value:{required:true,type:'number',min:0,value:row?.lead_value??1},lead_unit:{required:true,options:[['DAYS','Days'],['WEEKS','Weeks'],['MONTHS','Calendar months']],value:row?.lead_unit||'MONTHS'},
      recipient_ids:{label:'Recipients (Ctrl / Cmd to select multiple)',required:true,multiple:true,options:users.map(u=>[u.id,`${u.first_name} ${u.last_name} · ${u.email}`]),value:row?.recipient_ids||[]},
      is_active:{label:'Status',options:[['true','Enabled'],['false','Paused']],value:String(row?.is_active??true)}
    },async data=>{data.lead_value=Number(data.lead_value);data.is_active=data.is_active==='true';data.employee_id=data.employee_id||null;await api(`${base}/alert-rules${row?'/'+row.id:''}`,{method:row?'PUT':'POST',body:data});await settings();});
  }
  async function settings(){const area=$('alert-rules-content');area.replaceChildren(el('p','Rules apply to active employment-contract documents with an expiry date. A calendar month follows the calendar, including month-end dates. Both in-app and email reminders are generated once per rule, contract expiry and recipient.','hint'));
    area.append(btn('Check due contracts now',async()=>{const result=await api(`${base}/alert-rules/run`,{method:'POST'});notice(`${result.notifications_created} notifications created.`);await settings();}));
    const rows=await api(`${base}/alert-rules`);for(const row of rows){const panel=card(row.name,area);values({lead_time:`${row.lead_value} ${row.lead_unit.toLowerCase()}`,recipients:row.recipient_ids.length,status:row.is_active?'Enabled':'Paused'},panel);panel.append(btn('Edit rule',()=>ruleForm(row)));}
    const mail=await api(`${base}/email-deliveries`);const output=$('email-delivery-content');output.replaceChildren(el('p',mail.smtp_configured?'SMTP configured. Delivery is processed in the background.':'SMTP is not configured. Messages remain queued until SMTP_HOST and SMTP_FROM are set.','hint'));
    for(const row of mail.items){const panel=card(`${row.kind} · ${row.status}`,output);values({recipient:row.recipient_id,attempts:row.attempts,error:row.last_error},panel);if(row.status==='FAILED')panel.append(btn('Retry delivery',async()=>{await api(`${base}/email-deliveries/${row.id}/retry`,{method:'POST'});await settings();}));}
  }
  function clear(){access={};for(const id of ['my-profile-content','notifications-content','alert-rules-content','email-delivery-content','hr-form-content'])$(id).replaceChildren();}
  $('hr-dialog').addEventListener('close',()=> $('hr-form-content').replaceChildren());
  $('refresh-notifications').onclick=()=>action(notifications);$('add-alert-rule').onclick=()=>action(()=>ruleForm());
  function openPasswordReset(){
    if(!location.hash.startsWith('#reset='))return false;
    const token=location.hash.slice(7);history.replaceState(null,'','#home');
    edit('Set your password',{password:{label:'New password (at least 12 characters)',type:'password',required:true},confirmation:{label:'Confirm password',type:'password',required:true}},async data=>{
      if(data.password!==data.confirmation)throw Error('Passwords do not match');if(data.password.length<12)throw Error('Use at least 12 characters');
      await send(`${base}/password-reset`,{method:'POST',body:{token,password:data.password},authenticated:false});showError('login-error','Password set. Sign in with your email and new password.');
    });
    return true;
  }
  openPasswordReset();
  return {get access(){return access;},initialize,employee,self,notifications,settings,clear,openPasswordReset,downloadLeaveLetter};
})();
