/* NetPulse dashboard (vanilla JS, no build step, no external libs) */
const REFRESH_MS = 10000;
let currentDeviceId = null;

/* ---------------------------------------------------------------- utils */
async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    credentials: "same-origin",
    ...options,
  });
  if (res.status === 401) { window.location.href = "/login"; throw new Error("unauthorized"); }
  if (res.status === 403 && res.headers.get("X-Password-Change-Required")) {
    showPasswordModal();
    throw new Error("password change required");
  }
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  if (res.status === 204) return null;
  return res.json();
}

/* ---------------------------------------------------------------- forced password change */
function showPasswordModal() {
  document.getElementById("pw-modal").classList.add("open");
}

async function submitPasswordChange(e) {
  e.preventDefault();
  const errBox = document.getElementById("pw-error");
  errBox.textContent = "";
  const current = document.getElementById("pw-current").value;
  const next = document.getElementById("pw-new").value;
  const confirmPw = document.getElementById("pw-confirm").value;
  if (next !== confirmPw) { errBox.textContent = "New passwords do not match"; return; }
  if (next.length < 8) { errBox.textContent = "New password must be at least 8 characters"; return; }
  try {
    await api("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({ current_password: current, new_password: next }),
    });
    alert("Password updated. Please sign in again.");
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login";
  } catch (err) {
    errBox.textContent = err.message;
  }
}
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}
function fmtLatency(v) { return v == null ? "—" : `${Number(v).toFixed(1)} ms`; }
function fmtPct(v) { return v == null ? "—" : `${Number(v).toFixed(0)}%`; }
function fmtRate(bps) {
  if (bps == null) return "—";
  const b = Number(bps);
  if (b >= 1e9) return (b / 1e9).toFixed(2) + " Gbps";
  if (b >= 1e6) return (b / 1e6).toFixed(2) + " Mbps";
  if (b >= 1e3) return (b / 1e3).toFixed(1) + " Kbps";
  return b.toFixed(0) + " bps";
}
function fmtTime(v) {
  if (!v) return "—";
  const d = new Date(v);
  return isNaN(d) ? "—" : d.toLocaleString();
}
function badge(status) {
  const s = (status || "unknown").toLowerCase();
  const dot = s === "up" ? "🟢" : s === "down" ? "🔴" : "⚪";
  return `<span class="badge ${s}">${dot} ${esc(s.toUpperCase())}</span>`;
}

/* ---------------------------------------------------------------- charts (SVG) */
function drawSpark(svg, values, color, unit = "") {
  svg.innerHTML = "";
  const W = 600, H = 120, PAD = 6;
  if (!values || values.length < 2) {
    svg.innerHTML = `<text x="12" y="66" fill="#8a97b5" font-size="14">no data yet</text>`;
    return;
  }
  const nums = values.map((p) => Number(p.v) || 0);
  let min = Math.min(...nums), max = Math.max(...nums);
  if (min === max) { max = min + 1; }
  const span = max - min;
  const stepX = (W - PAD * 2) / (nums.length - 1);
  const y = (v) => H - PAD - ((v - min) / span) * (H - PAD * 2);

  const pts = nums.map((v, i) => [PAD + i * stepX, y(v)]);
  const line = pts.map((p, i) => `${i === 0 ? "M" : "L"}${p[0].toFixed(1)},${p[1].toFixed(1)}`).join(" ");
  const area = `${line} L${pts[pts.length - 1][0].toFixed(1)},${H - PAD} L${pts[0][0].toFixed(1)},${H - PAD} Z`;

  svg.innerHTML = `
    <path d="${area}" fill="${color}" opacity="0.12"></path>
    <path d="${line}" fill="none" stroke="${color}" stroke-width="2"></path>
    <text x="10" y="14" fill="#8a97b5" font-size="11">max ${max.toFixed(1)}${unit}</text>
    <text x="10" y="${H - 4}" fill="#8a97b5" font-size="11">min ${min.toFixed(1)}${unit}</text>`;
}

/* ---------------------------------------------------------------- dashboard */
async function loadStats() {
  const s = await api("/api/stats");
  document.getElementById("stat-total").textContent = s.total;
  document.getElementById("stat-up").textContent = s.up;
  document.getElementById("stat-down").textContent = s.down;
  document.getElementById("stat-unknown").textContent = s.unknown;
  document.getElementById("stat-latency").textContent = fmtLatency(s.avg_latency_ms);
  document.getElementById("stat-cpu").textContent = fmtPct(s.avg_cpu);
  document.getElementById("stat-ram").textContent = fmtPct(s.avg_ram);
  document.getElementById("stat-events").textContent = s.events_last_24h;
}

async function loadDevices() {
  const devices = await api("/api/devices");
  const tbody = document.getElementById("devices-body");
  if (!devices.length) {
    tbody.innerHTML = `<tr><td colspan="10" class="muted" style="text-align:center;padding:24px">
      No devices yet. Click "Add Device" to start monitoring.</td></tr>`;
    return;
  }
  tbody.innerHTML = devices.map((d) => `
    <tr>
      <td><a href="#" onclick="openDevice(${d.id});return false;">${esc(d.name)}</a>
          ${d.vendor ? `<div class="muted" style="font-size:12px">${esc(d.vendor)}</div>` : ""}</td>
      <td><code>${esc(d.host)}</code></td>
      <td>${d.alert_group_name
            ? `<span class="badge unknown">${esc(d.alert_group_name)}</span>`
            : `<span class="muted">default</span>`}</td>
      <td>${badge(d.status)}</td>
      <td>${fmtLatency(d.last_latency_ms)}</td>
      <td>${fmtPct(d.last_cpu)}</td>
      <td>${fmtPct(d.last_ram)}</td>
      <td>${d.uptime_percent == null ? "—" : d.uptime_percent + "%"}</td>
      <td class="muted">${fmtTime(d.last_checked_at)}</td>
      <td>
        <button class="ghost small" onclick="checkNow(${d.id})">Check</button>
        <button class="danger small" onclick="removeDevice(${d.id}, '${esc(d.name)}')">Delete</button>
      </td>
    </tr>`).join("");
}

async function loadEvents() {
  const events = await api("/api/events?limit=25");
  const box = document.getElementById("events-body");
  if (!events.length) { box.innerHTML = `<div class="muted" style="padding:16px">No events yet.</div>`; return; }
  box.innerHTML = events.map((e) => {
    const color = e.severity === "critical" ? "var(--down)"
      : e.severity === "warning" ? "var(--warn)" : "var(--up)";
    return `<div style="padding:10px 18px;border-bottom:1px solid var(--border)">
      <span style="color:${color};font-weight:600">${esc(e.type.toUpperCase())}</span>
      <span class="muted" style="float:right;font-size:12px">${fmtTime(e.created_at)}</span>
      <div class="muted" style="margin-top:3px">${esc(e.message)}</div></div>`;
  }).join("");
}

async function refresh() {
  try {
    await Promise.all([loadStats(), loadDevices(), loadEvents()]);
    document.getElementById("last-refresh").textContent = new Date().toLocaleTimeString();
    if (currentDeviceId) { await renderDevice(currentDeviceId); }
  } catch (e) { console.error(e); }
}

/* ---------------------------------------------------------------- device detail */
async function openDevice(id) {
  currentDeviceId = id;
  document.getElementById("drawer").classList.add("open");
  document.getElementById("drawer-backdrop").classList.add("open");
  await renderDevice(id);
}
function closeDrawer() {
  currentDeviceId = null;
  document.getElementById("drawer").classList.remove("open");
  document.getElementById("drawer-backdrop").classList.remove("open");
}

async function renderDevice(id) {
  const [device, cpu, ram, history, interfaces, events] = await Promise.all([
    api(`/api/devices/${id}`),
    api(`/api/devices/${id}/metrics?metric=cpu&hours=12`),
    api(`/api/devices/${id}/metrics?metric=ram&hours=12`),
    api(`/api/devices/${id}/history?hours=12&limit=300`),
    api(`/api/devices/${id}/interfaces`),
    api(`/api/devices/${id}/events?limit=8`),
  ]);

  document.getElementById("d-name").textContent = device.name;
  document.getElementById("d-host").textContent = `${device.host}${device.vendor ? " · " + device.vendor : ""}`;
  document.getElementById("d-badges").innerHTML =
    badge(device.status) +
    `<span class="badge unknown">latency ${fmtLatency(device.last_latency_ms)}</span>` +
    `<span class="badge unknown">CPU ${fmtPct(device.last_cpu)}</span>` +
    `<span class="badge unknown">RAM ${fmtPct(device.last_ram)}</span>`;

  document.getElementById("d-cpu-now").textContent = fmtPct(device.last_cpu);
  document.getElementById("d-ram-now").textContent = fmtPct(device.last_ram);
  document.getElementById("d-lat-now").textContent = fmtLatency(device.last_latency_ms);

  drawSpark(document.getElementById("chart-cpu"), cpu.points, "#3b82f6", "%");
  drawSpark(document.getElementById("chart-ram"), ram.points, "#a855f7", "%");
  const latPts = history.slice().reverse().filter((r) => r.latency_ms != null)
    .map((r) => ({ t: r.timestamp, v: r.latency_ms }));
  drawSpark(document.getElementById("chart-lat"), latPts, "#22c55e", "ms");

  const itbody = document.getElementById("d-interfaces");
  if (!interfaces.length) {
    itbody.innerHTML = `<tr><td colspan="5" class="muted">No SNMP interfaces (enable SNMP or wait for a poll).</td></tr>`;
  } else {
    itbody.innerHTML = interfaces.slice(0, 40).map((i) => `
      <tr>
        <td class="muted">${i.if_index}</td>
        <td>${esc(i.if_name || i.if_alias || "—")}</td>
        <td>${i.oper_status === 1 ? "🟢 up" : i.oper_status === 2 ? "🔴 down" : "—"}</td>
        <td>${fmtRate(i.last_in_bps)}</td>
        <td>${fmtRate(i.last_out_bps)}</td>
      </tr>`).join("");
  }

  const ebox = document.getElementById("d-events");
  ebox.innerHTML = events.length
    ? events.map((e) => `<div class="event-line">
        <b>${esc(e.type)}</b> <span class="muted">${fmtTime(e.created_at)}</span><br>
        <span class="muted">${esc(e.message)}</span></div>`).join("")
    : "No events yet.";
}

/* ---------------------------------------------------------------- actions */
async function checkNow(id) {
  try { await api(`/api/devices/${id}/check-now`, { method: "POST" }); setTimeout(refresh, 1500); }
  catch (e) { alert(e.message); }
}
async function removeDevice(id, name) {
  if (!confirm(`Delete device "${name}"?`)) return;
  try { await api(`/api/devices/${id}`, { method: "DELETE" }); if (currentDeviceId === id) closeDrawer(); await refresh(); }
  catch (e) { alert(e.message); }
}
async function testTelegram() {
  try { const r = await api("/api/notifications/test", { method: "POST" }); alert(r.detail); }
  catch (e) { alert(e.message); }
}
async function logout() { await api("/api/auth/logout", { method: "POST" }); window.location.href = "/login"; }

/* ---------------------------------------------------------------- modal */
function openModal() { document.getElementById("modal").classList.add("open"); }
function closeModal() {
  document.getElementById("modal").classList.remove("open");
  document.getElementById("add-error").textContent = "";
}
function onCheckTypeChange() {
  const type = document.getElementById("f-check-type").value;
  document.getElementById("row-port").style.display = type === "tcp" ? "block" : "none";
  document.getElementById("row-url").style.display = type === "http" ? "block" : "none";
}
function onSnmpToggle() {
  document.getElementById("snmp-fields").style.display =
    document.getElementById("f-snmp-enabled").checked ? "block" : "none";
}
function onSnmpVersionChange() {
  const v = document.getElementById("f-snmp-version").value;
  document.getElementById("snmp-v12").style.display = v === "3" ? "none" : "block";
  document.getElementById("snmp-v3").style.display = v === "3" ? "block" : "none";
}

async function loadVendors() {
  const vendors = await api("/api/system/vendors");
  const sel = document.getElementById("f-vendor");
  sel.innerHTML = `<option value="">— none —</option>` +
    vendors.map((v) => `<option value="${esc(v.key)}">${esc(v.label)}</option>`).join("");
}

async function submitDevice(e) {
  e.preventDefault();
  const errBox = document.getElementById("add-error");
  errBox.textContent = "";
  const type = document.getElementById("f-check-type").value;
  const params = {};
  if (type === "tcp") params.port = Number(document.getElementById("f-port").value || 0);
  if (type === "http") params.url = document.getElementById("f-url").value || "";

  const snmpOn = document.getElementById("f-snmp-enabled").checked;
  const payload = {
    name: document.getElementById("f-name").value.trim(),
    host: document.getElementById("f-host").value.trim(),
    vendor: document.getElementById("f-vendor").value || null,
    alert_group_id: document.getElementById("f-group").value
      ? Number(document.getElementById("f-group").value) : null,
    interval_seconds: Number(document.getElementById("f-interval").value || 60),
    timeout_seconds: Number(document.getElementById("f-timeout").value || 3),
    latency_threshold_ms: document.getElementById("f-threshold").value ? Number(document.getElementById("f-threshold").value) : null,
    cpu_threshold: document.getElementById("f-cpu-threshold").value ? Number(document.getElementById("f-cpu-threshold").value) : null,
    ram_threshold: document.getElementById("f-ram-threshold").value ? Number(document.getElementById("f-ram-threshold").value) : null,
    checks: [{ name: type, type, params, enabled: true, critical: true, latency_threshold_ms: null }],
    snmp_enabled: snmpOn,
  };
  if (snmpOn) {
    const ver = document.getElementById("f-snmp-version").value;
    payload.snmp_version = ver;
    payload.snmp_port = Number(document.getElementById("f-snmp-port").value || 161);
    if (ver === "3") {
      payload.snmp_v3_user = document.getElementById("f-v3-user").value || null;
      payload.snmp_v3_auth_proto = document.getElementById("f-v3-auth-proto").value;
      payload.snmp_v3_auth_pass = document.getElementById("f-v3-auth-pass").value || null;
      payload.snmp_v3_priv_proto = document.getElementById("f-v3-priv-proto").value;
      payload.snmp_v3_priv_pass = document.getElementById("f-v3-priv-pass").value || null;
    } else {
      payload.snmp_community = document.getElementById("f-snmp-community").value || "public";
    }
  }
  try {
    await api("/api/devices", { method: "POST", body: JSON.stringify(payload) });
    closeModal();
    document.getElementById("add-form").reset();
    onCheckTypeChange(); onSnmpToggle(); onSnmpVersionChange();
    await refresh();
  } catch (err) { errBox.textContent = err.message; }
}

/* ---------------------------------------------------------------- telegram */
function openTelegramModal() {
  document.getElementById("tg-modal").classList.add("open");
  loadTelegram().catch((e) => console.error(e));
}
function closeTelegramModal() { document.getElementById("tg-modal").classList.remove("open"); }

async function loadTelegram() {
  const [s, w] = await Promise.all([
    api("/api/system/telegram"),
    api("/api/system/whatsapp").catch(() => null),
  ]);
  document.getElementById("tg-enabled").checked = s.enabled;
  document.getElementById("tg-chat").value = s.chat_id || "";
  document.getElementById("tg-token").value = "";
  document.getElementById("tg-digest").checked = !!s.digest_enabled;
  document.getElementById("tg-digest-min").value = s.digest_minutes || 60;
  document.getElementById("tg-token-hint").textContent =
    s.has_token ? "✅ a token is already saved (leave blank to keep it)"
                : "⚠️ no token saved yet";

  if (w) {
    document.getElementById("wa-enabled").checked = w.enabled;
    document.getElementById("wa-phone").value = w.phone || "";
    document.getElementById("wa-apikey").value = "";
    document.getElementById("wa-hint").textContent =
      w.has_apikey ? "✅ an API key is already saved (leave blank to keep it)"
                   : "⚠️ no API key saved yet";
  }
}

async function saveTelegram() {
  const errBox = document.getElementById("tg-error");
  errBox.textContent = "";
  const tgBody = {
    enabled: document.getElementById("tg-enabled").checked,
    chat_id: document.getElementById("tg-chat").value.trim(),
    digest_enabled: document.getElementById("tg-digest").checked,
    digest_minutes: Number(document.getElementById("tg-digest-min").value || 60),
  };
  const tgToken = document.getElementById("tg-token").value.trim();
  if (tgToken) tgBody.bot_token = tgToken;

  const waBody = {
    enabled: document.getElementById("wa-enabled").checked,
    phone: document.getElementById("wa-phone").value.trim(),
  };
  const waKey = document.getElementById("wa-apikey").value.trim();
  if (waKey) waBody.apikey = waKey;

  try {
    const s = await api("/api/system/telegram", { method: "PUT", body: JSON.stringify(tgBody) });
    const w = await api("/api/system/whatsapp", { method: "PUT", body: JSON.stringify(waBody) });
    errBox.style.color = "var(--up)";
    const parts = [];
    parts.push(s.ready ? "Telegram ✅" : "Telegram ⚠️");
    parts.push(w.ready ? "WhatsApp ✅" : "WhatsApp ⚠️");
    errBox.textContent = "Saved — " + parts.join("  ·  ");
    await loadTelegram();
  } catch (e) { errBox.style.color = "var(--down)"; errBox.textContent = e.message; }
}

async function testTelegramSettings() {
  const errBox = document.getElementById("tg-error");
  errBox.style.color = "var(--muted)";
  errBox.textContent = "Sending Telegram test...";
  try {
    const r = await api("/api/system/telegram/test", { method: "POST" });
    errBox.style.color = "var(--up)";
    errBox.textContent = "Telegram: " + r.detail;
  } catch (e) { errBox.style.color = "var(--down)"; errBox.textContent = e.message; }
}

async function testWhatsAppSettings() {
  const errBox = document.getElementById("tg-error");
  errBox.style.color = "var(--muted)";
  errBox.textContent = "Sending WhatsApp test...";
  try {
    const r = await api("/api/system/whatsapp/test", { method: "POST" });
    errBox.style.color = "var(--up)";
    errBox.textContent = "WhatsApp: " + r.detail;
  } catch (e) { errBox.style.color = "var(--down)"; errBox.textContent = e.message; }
}

async function findTelegramChats() {
  const box = document.getElementById("tg-chats");
  box.textContent = "Looking up chats...";
  try {
    const r = await api("/api/system/telegram/chats");
    const chats = r.chats || [];
    if (!chats.length) {
      box.innerHTML = "No chats found. Add the bot to your group, send a message there, then click again.";
      return;
    }
    box.innerHTML = chats.map((c) =>
      `<a href="#" onclick="pickChat('${c.id}');return false;">${esc(c.title || c.type || "chat")} (${c.id})</a>`
    ).join("<br>") + `<div class="muted" style="margin-top:6px">${esc(r.hint || "")}</div>`;
  } catch (e) { box.style.color = "var(--down)"; box.textContent = e.message; }
}

function pickChat(id) {
  document.getElementById("tg-chat").value = id;
}

/* ---------------------------------------------------------------- alert groups */
let groupsCache = [];

async function loadGroups() {
  try { groupsCache = await api("/api/groups"); } catch (e) { groupsCache = []; }
  const sel = document.getElementById("f-group");
  if (sel) {
    const keep = sel.value;
    sel.innerHTML = `<option value="">— default chat —</option>` +
      groupsCache.map((g) =>
        `<option value="${g.id}">${esc(g.name)}${g.telegram_chat_id ? "" : " ⚠ no chat id"}</option>`
      ).join("");
    sel.value = keep;
  }
  return groupsCache;
}

function openGroupsModal() {
  document.getElementById("groups-modal").classList.add("open");
  loadGroupsTable().catch((e) => console.error(e));
}
function closeGroupsModal() { document.getElementById("groups-modal").classList.remove("open"); }

async function loadGroupsTable() {
  const groups = await api("/api/groups");
  groupsCache = groups;
  const tbody = document.getElementById("groups-body");
  if (!groups.length) {
    tbody.innerHTML = `<tr><td colspan="6" class="muted">No groups yet — create one below.</td></tr>`;
    return;
  }
  tbody.innerHTML = groups.map((g) => `
    <tr>
      <td class="muted">${g.id}</td>
      <td>${esc(g.name)}${g.enabled ? "" : ' <span class="muted">(disabled)</span>'}</td>
      <td><code>${g.telegram_chat_id ? esc(g.telegram_chat_id) : "—"}</code>
          <button class="ghost small" onclick="editGroupChat(${g.id}, '${esc(g.name)}', '${g.telegram_chat_id || ""}')">set</button></td>
      <td>${g.whatsapp_enabled ? "🟢" : "⚪"}</td>
      <td>${g.device_count}</td>
      <td>
        <button class="ghost small" onclick="testGroup(${g.id})">Test</button>
        <button class="danger small" onclick="deleteGroup(${g.id}, '${esc(g.name)}')">Delete</button>
      </td>
    </tr>`).join("");
}

async function submitNewGroup(e) {
  e.preventDefault();
  const errBox = document.getElementById("ng-error");
  errBox.textContent = "";
  try {
    await api("/api/groups", {
      method: "POST",
      body: JSON.stringify({
        name: document.getElementById("ng-name").value.trim(),
        telegram_chat_id: document.getElementById("ng-chat").value.trim() || null,
        whatsapp_enabled: document.getElementById("ng-wa").checked,
      }),
    });
    document.getElementById("new-group-form").reset();
    document.getElementById("ng-chats").textContent = "";
    await loadGroupsTable();
    await loadGroups();
    await refresh();
  } catch (err) { errBox.textContent = err.message; }
}

async function editGroupChat(id, name, current) {
  const v = prompt(`Telegram chat id for "${name}" (group ids start with -100):`, current || "");
  if (v === null) return;
  try {
    await api(`/api/groups/${id}`, { method: "PATCH", body: JSON.stringify({ telegram_chat_id: v.trim() }) });
    await loadGroupsTable(); await loadGroups(); await refresh();
  } catch (e) { alert(e.message); }
}

async function testGroup(id) {
  try { const r = await api(`/api/groups/${id}/test`, { method: "POST" }); alert(r.detail); }
  catch (e) { alert(e.message); }
}

async function deleteGroup(id, name) {
  if (!confirm(`Delete group "${name}"? Its devices will fall back to the default chat.`)) return;
  try {
    await api(`/api/groups/${id}`, { method: "DELETE" });
    await loadGroupsTable(); await loadGroups(); await refresh();
  } catch (e) { alert(e.message); }
}

async function findGroupChats() {
  const box = document.getElementById("ng-chats");
  box.textContent = "Looking up chats...";
  try {
    const r = await api("/api/system/telegram/chats");
    const chats = r.chats || [];
    if (!chats.length) {
      box.textContent = "No chats found. Add the bot to the group, send /start there, then click Find again.";
      return;
    }
    box.innerHTML = chats.map((c) =>
      `<a href="#" onclick="document.getElementById('ng-chat').value='${c.id}';return false;">${esc(c.title || c.type || "chat")} (${c.id})</a>`
    ).join("<br>");
  } catch (e) { box.textContent = e.message; }
}

/* ---------------------------------------------------------------- users */
let currentUser = null;

function openUsersModal() {
  document.getElementById("users-modal").classList.add("open");
  loadUsers().catch((e) => console.error(e));
}
function closeUsersModal() { document.getElementById("users-modal").classList.remove("open"); }

async function loadUsers() {
  const users = await api("/api/auth/users");
  const tbody = document.getElementById("users-body");
  tbody.innerHTML = users.map((u) => `
    <tr>
      <td class="muted">${u.id}</td>
      <td>${esc(u.username)}${currentUser && u.id === currentUser.id ? ' <span class="muted">(you)</span>' : ""}</td>
      <td class="muted">${esc(u.email)}</td>
      <td>${u.is_active ? "🟢 yes" : "⚪ no"}</td>
      <td>${u.is_superuser ? "Admin" : "User"}</td>
      <td>
        <button class="ghost small" onclick="resetUserPassword(${u.id}, '${esc(u.username)}')">Reset pw</button>
        <button class="ghost small" onclick="toggleUserActive(${u.id}, ${u.is_active})">${u.is_active ? "Disable" : "Enable"}</button>
        <button class="ghost small" onclick="toggleUserAdmin(${u.id}, ${u.is_superuser})">${u.is_superuser ? "Demote" : "Promote"}</button>
        <button class="danger small" onclick="deleteUser(${u.id}, '${esc(u.username)}')">Delete</button>
      </td>
    </tr>`).join("");
}

async function submitMyPassword(e) {
  e.preventDefault();
  const errBox = document.getElementById("my-pw-error");
  errBox.textContent = "";
  try {
    await api("/api/auth/change-password", {
      method: "POST",
      body: JSON.stringify({
        current_password: document.getElementById("my-pw-current").value,
        new_password: document.getElementById("my-pw-new").value,
      }),
    });
    alert("Password changed. Please sign in again.");
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    window.location.href = "/login";
  } catch (err) { errBox.textContent = err.message; }
}

async function submitNewUser(e) {
  e.preventDefault();
  const errBox = document.getElementById("nu-error");
  errBox.textContent = "";
  try {
    await api("/api/auth/users", {
      method: "POST",
      body: JSON.stringify({
        username: document.getElementById("nu-username").value.trim(),
        email: document.getElementById("nu-email").value.trim(),
        password: document.getElementById("nu-password").value,
        is_superuser: document.getElementById("nu-superuser").value === "true",
      }),
    });
    document.getElementById("new-user-form").reset();
    await loadUsers();
  } catch (err) { errBox.textContent = err.message; }
}

async function resetUserPassword(id, name) {
  const pw = prompt(`New password for "${name}" (min 8 characters):`);
  if (!pw) return;
  try { await api(`/api/auth/users/${id}`, { method: "PATCH", body: JSON.stringify({ password: pw }) }); alert("Password reset."); }
  catch (e) { alert(e.message); }
}

async function toggleUserActive(id, isActive) {
  try { await api(`/api/auth/users/${id}`, { method: "PATCH", body: JSON.stringify({ is_active: !isActive }) }); await loadUsers(); }
  catch (e) { alert(e.message); }
}

async function toggleUserAdmin(id, isAdmin) {
  try { await api(`/api/auth/users/${id}`, { method: "PATCH", body: JSON.stringify({ is_superuser: !isAdmin }) }); await loadUsers(); }
  catch (e) { alert(e.message); }
}

async function deleteUser(id, name) {
  if (!confirm(`Delete user "${name}"? This cannot be undone.`)) return;
  try { await api(`/api/auth/users/${id}`, { method: "DELETE" }); await loadUsers(); }
  catch (e) { alert(e.message); }
}

/* ---------------------------------------------------------------- init */
async function init() {
  let me;
  try { me = await api("/api/auth/me"); }
  catch (e) { return; }
  currentUser = me;
  document.getElementById("whoami").textContent = me.username;
  if (me.must_change_password) {
    showPasswordModal();
    return;   // block the dashboard until the password is changed
  }
  await loadVendors().catch(() => {});
  await loadGroups().catch(() => {});
  await refresh();
  setInterval(refresh, REFRESH_MS);
}

document.addEventListener("DOMContentLoaded", () => {
  document.getElementById("btn-add").addEventListener("click", openModal);
  document.getElementById("btn-close-modal").addEventListener("click", closeModal);
  document.getElementById("add-form").addEventListener("submit", submitDevice);
  document.getElementById("pw-form").addEventListener("submit", submitPasswordChange);
  document.getElementById("btn-users").addEventListener("click", openUsersModal);
  document.getElementById("btn-close-users").addEventListener("click", closeUsersModal);
  document.getElementById("my-pw-form").addEventListener("submit", submitMyPassword);
  document.getElementById("new-user-form").addEventListener("submit", submitNewUser);
  document.getElementById("f-check-type").addEventListener("change", onCheckTypeChange);
  document.getElementById("f-snmp-enabled").addEventListener("change", onSnmpToggle);
  document.getElementById("f-snmp-version").addEventListener("change", onSnmpVersionChange);
  document.getElementById("btn-telegram").addEventListener("click", openTelegramModal);
  document.getElementById("btn-groups").addEventListener("click", openGroupsModal);
  document.getElementById("btn-close-groups").addEventListener("click", closeGroupsModal);
  document.getElementById("new-group-form").addEventListener("submit", submitNewGroup);
  document.getElementById("ng-find").addEventListener("click", findGroupChats);
  document.getElementById("btn-close-tg").addEventListener("click", closeTelegramModal);
  document.getElementById("tg-save").addEventListener("click", saveTelegram);
  document.getElementById("tg-test").addEventListener("click", testTelegramSettings);
  document.getElementById("wa-test").addEventListener("click", testWhatsAppSettings);
  document.getElementById("tg-find").addEventListener("click", findTelegramChats);
  document.getElementById("btn-logout").addEventListener("click", logout);
  document.getElementById("btn-refresh").addEventListener("click", refresh);
  document.getElementById("drawer-close").addEventListener("click", closeDrawer);
  document.getElementById("drawer-backdrop").addEventListener("click", closeDrawer);
  onCheckTypeChange(); onSnmpToggle(); onSnmpVersionChange();
  init();
});
