"""Build the static, password-protected NetPulse dashboard for GitHub Pages.

Why static: GitHub Pages serves files only, and it is the one free host that
needs no account of its own. GitHub Actions rebuilds this page after every
check, so it always shows the latest state.

Privacy: the payload is encrypted with AES-GCM using a key derived from
DASHBOARD_PASSWORD (PBKDF2-SHA256). The public repo only ever holds ciphertext.

Device management: the page can add/remove devices by writing
``cloud/config.json`` through the GitHub REST API. That needs a token the
operator pastes once (stored in the browser's localStorage).

Usage:
    DASHBOARD_PASSWORD=... python scripts/build_dashboard.py [output_dir]
"""
from __future__ import annotations

import base64
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "cloud" / "config.json"
STATE_PATH = ROOT / "cloud" / "state.json"
REPO = "mahfuztitas01/netpulse"
BRANCH = "main"
ITERATIONS = 200_000


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def read_json(path: Path, default):
    """Tolerate a UTF-8 BOM (PowerShell's Set-Content adds one on Windows)."""
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return default


def build_payload() -> dict:
    config = read_json(CONFIG_PATH, {})
    state = read_json(STATE_PATH, {})
    prev = state.get("devices") or {}
    labels = config.get("group_labels") or {}

    devices = []
    for dev in config.get("devices") or []:
        name = dev.get("name") or dev.get("host") or "unnamed"
        entry = prev.get(name) or {}
        group_key = dev.get("alert_group") or "default"
        devices.append(
            {
                "name": name,
                "host": dev.get("host") or "",
                "group": group_key,
                "group_label": labels.get(group_key) or (
                    "Default (your personal chat)" if group_key == "default" else group_key
                ),
                "checks": "+".join(c.get("type", "?") for c in (dev.get("checks") or [])),
                "status": entry.get("status") or "unknown",
                "latency": entry.get("latency_ms"),
                "last_change": entry.get("last_change"),
                "last_down": entry.get("last_down"),
            }
        )

    up = sum(1 for d in devices if d["status"] == "up")
    down = sum(1 for d in devices if d["status"] == "down")
    return {
        "generated_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "state_updated_at": state.get("updated_at"),
        "total": len(devices),
        "up": up,
        "down": down,
        "unknown": len(devices) - up - down,
        "devices": devices,
        # raw config so the page can edit the device list itself
        "config": config,
        "repo": REPO,
        "branch": BRANCH,
        # GitHub token for device management, shipped INSIDE the encrypted
        # payload so the operator never has to paste it by hand. It is only
        # readable after the dashboard password decrypts this blob.
        "gh_token": (os.environ.get("DASHBOARD_GH_TOKEN") or "").strip(),
    }


def encrypt(payload: dict, password: str) -> dict:
    salt = os.urandom(16)
    iv = os.urandom(12)
    kdf = PBKDF2HMAC(algorithm=SHA256(), length=32, salt=salt, iterations=ITERATIONS)
    key = kdf.derive(password.encode("utf-8"))
    ct = AESGCM(key).encrypt(iv, json.dumps(payload).encode("utf-8"), None)
    return {"salt": b64(salt), "iv": b64(iv), "ct": b64(ct), "iter": ITERATIONS}


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#0b1020" />
<title>NetPulse</title>
<style>
  :root { color-scheme: dark; --bg:#0b1020; --card:#141a2e; --border:#26304f;
          --fg:#e6ebf5; --muted:#8a97b5; --up:#22c55e; --down:#ef4444; --warn:#f59e0b; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--fg); padding:16px;
         font-family:"Segoe UI",system-ui,-apple-system,sans-serif; }
  .wrap { max-width:840px; margin:0 auto; }
  h1 { font-size:20px; margin:0 0 4px; display:flex; align-items:center; gap:8px; }
  .dot { width:10px; height:10px; border-radius:50%; background:#3b82f6; box-shadow:0 0 12px #3b82f6; }
  .sub { color:var(--muted); font-size:12px; margin-bottom:16px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(92px,1fr)); gap:10px; margin-bottom:16px; }
  .card { background:var(--card); border:1px solid var(--border); border-radius:12px; padding:12px; }
  .card .l { color:var(--muted); font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  .card .v { font-size:22px; font-weight:700; margin-top:4px; }
  table { width:100%; border-collapse:collapse; background:var(--card);
          border:1px solid var(--border); border-radius:12px; overflow:hidden; }
  th,td { padding:10px 12px; text-align:left; font-size:13px; border-bottom:1px solid var(--border); }
  th { color:var(--muted); font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:.04em; }
  tr:last-child td { border-bottom:none; }
  .b { display:inline-block; padding:3px 9px; border-radius:999px; font-size:11px; font-weight:700; }
  .b.up { background:rgba(34,197,94,.15); color:var(--up); }
  .b.down { background:rgba(239,68,68,.15); color:var(--down); }
  .b.unknown { background:rgba(138,151,181,.15); color:var(--muted); }
  code { color:var(--muted); font-size:12px; }
  .gate { background:var(--card); border:1px solid var(--border); border-radius:16px;
          padding:26px 22px; max-width:380px; margin:10vh auto 0; text-align:center; }
  .gate h2 { margin:0 0 6px; font-size:18px; }
  .gate p { color:var(--muted); font-size:13px; margin:0 0 16px; }
  input,select { width:100%; padding:12px; border-radius:10px; border:1px solid var(--border);
          background:#0e1424; color:var(--fg); font-size:14px; margin-top:4px; }
  label { color:var(--muted); font-size:12px; display:block; margin-top:10px; }
  button { padding:12px 16px; border:none; border-radius:10px; background:#3b82f6;
           color:#fff; font-weight:700; font-size:14px; cursor:pointer; }
  button.ghost { background:transparent; border:1px solid var(--border); color:var(--fg); font-weight:600; }
  button.mini { padding:6px 10px; font-size:12px; }
  button:disabled { opacity:.55; cursor:default; }
  .row { display:flex; gap:8px; align-items:center; }
  .err { color:var(--down); font-size:13px; margin-top:10px; min-height:18px; }
  .ok { color:var(--up); }
  .panel { background:var(--card); border:1px solid var(--border); border-radius:14px;
           padding:16px; margin-top:16px; }
  .panel h3 { margin:0 0 4px; font-size:15px; }
  .grid2 { display:grid; grid-template-columns:1fr 1fr; gap:10px; }
  .foot { color:#64748b; font-size:11px; margin-top:14px; line-height:1.6; text-align:center; }
  a { color:#60a5fa; }
</style>
<script src="https://cdn.jsdelivr.net/npm/libsodium-wrappers@0.7.15/dist/browser/libsodium.js"></script>
<script src="https://cdn.jsdelivr.net/npm/libsodium-wrappers@0.7.15/dist/browser/libsodium-wrappers.js"></script>
</head>
<body>
<div class="wrap">
  <div id="gate" class="gate">
    <h2><span class="dot"></span> <span id="gate-brand">NetPulse</span></h2>
    <p>Enter your username and password to view live status.</p>
    <div id="user-wrap" style="display:none">
      <input id="user" type="text" autocomplete="username" placeholder="Username" />
    </div>
    <input id="pw" type="password" autocomplete="current-password" placeholder="Password" />
    <button id="go" style="width:100%;margin-top:10px">Unlock</button>
    <div class="err" id="err"></div>
  </div>

  <div id="app" style="display:none">
    <h1><span class="dot"></span> <span id="brand">NetPulse</span></h1>
    <div class="sub" id="sub"></div>

    <div class="cards" id="cards"></div>

    <table>
      <thead><tr><th>Device</th><th>Host</th><th>Group</th><th>Status</th><th>Latency</th><th></th></tr></thead>
      <tbody id="rows"></tbody>
    </table>

    <div class="panel">
      <h3>Add / manage devices</h3>
      <div class="sub" id="mgmt-state"></div>

      <div id="mgmt-form" style="display:none">
        <div class="grid2">
          <div><label>Name</label><input id="d-name" placeholder="Core Switch" /></div>
          <div><label>IP / Hostname</label><input id="d-host" placeholder="host or IP" /></div>
        </div>
        <div class="grid2">
          <div><label>Check type</label>
            <select id="d-type">
              <option value="ping">Ping (TCP fallback in cloud)</option>
              <option value="tcp">TCP port</option>
              <option value="http">HTTP(S)</option>
            </select>
          </div>
          <div><label>Alert group</label><select id="d-group"></select></div>
        </div>
        <div class="grid2">
          <div id="d-port-wrap"><label>TCP port</label><input id="d-port" type="number" placeholder="443" /></div>
          <div id="d-url-wrap" style="display:none"><label>HTTP URL</label><input id="d-url" placeholder="https://example.com/" /></div>
        </div>
        <div class="row" style="margin-top:12px">
          <button id="d-save">Add device</button>
          <button class="ghost" id="d-cancel">Cancel</button>
        </div>
        <div class="err" id="d-err"></div>
      </div>

      <div class="row" id="mgmt-actions">
        <button id="d-new">+ Add device</button>
        <button class="ghost" id="d-token-btn">Set GitHub token</button>
        <button class="ghost" id="d-test-btn">Test token</button>
        <button class="ghost" id="d-clear-btn">Clear token</button>
      </div>
      <div class="err" id="d-token-msg"></div>
      <div class="foot" style="text-align:left">
        Changes are saved to <code>cloud/config.json</code> on GitHub and take effect
        on the next scheduled check (within ~15 minutes).<br>
        Tip: you can type <code>host:port</code> in the Host box and it is saved as a TCP check automatically.
      </div>
    </div>

    <div class="panel">
      <h3>Manage client logins</h3>
      <div class="sub" id="client-state"></div>
      <div id="client-list"></div>
      <div class="err" id="client-msg"></div>
      <div class="foot" style="text-align:left">
        Each client group gets its own read-only page at <code>/client/&lt;group&gt;.html</code>.
        Set a username + password here; they are stored as GitHub secrets and applied on the next build.
      </div>
    </div>

    <div class="foot" id="foot"></div>
  </div>
</div>

<script>
const BLOB = __BLOB__;
const READ_ONLY = __READ_ONLY__;
const HAS_USER = __HAS_USER__;
const S = { salt: b64d(BLOB.salt), iv: b64d(BLOB.iv), ct: b64d(BLOB.ct), iter: BLOB.iter };
let DATA = null;
let CFG = null, CFG_SHA = null, REPO = "", BRANCH = "main";

function b64d(s){ const b=atob(s); const a=new Uint8Array(b.length); for(let i=0;i<b.length;i++) a[i]=b.charCodeAt(i); return a; }
function b64e(s){ return btoa(unescape(encodeURIComponent(s))); }
function esc(s){ return String(s??"").replace(/[&<>"']/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c])); }
function fmtLat(v){ return v==null ? "—" : Number(v).toFixed(1)+" ms"; }
function fmtT(v){ if(!v) return "—"; const d=new Date(v); return isNaN(d)?"—":d.toLocaleString(); }

async function unlock(pw){
  const km = await crypto.subtle.importKey("raw", new TextEncoder().encode(pw), "PBKDF2", false, ["deriveKey"]);
  const key = await crypto.subtle.deriveKey(
    { name:"PBKDF2", salt:S.salt, iterations:S.iter, hash:"SHA-256" },
    km, { name:"AES-GCM", length:256 }, false, ["decrypt"]);
  const plain = await crypto.subtle.decrypt({ name:"AES-GCM", iv:S.iv }, key, S.ct);
  return JSON.parse(new TextDecoder().decode(plain));
}

/* ---------------- GitHub API (device management) ---------------- */
/* The token arrives inside the encrypted payload, so no manual entry is
   needed. A value typed into localStorage still wins, which lets you
   override it without rebuilding the page. */
let EMBEDDED_TOKEN = "";

function ghToken(){
  const manual = (localStorage.getItem("np_gh_token") || "").trim();
  return manual || EMBEDDED_TOKEN;
}

async function ghFetch(url, opts){
  const r = await fetch(url, Object.assign({
    headers: { Authorization: "Bearer " + ghToken(), Accept: "application/vnd.github+json" }
  }, opts || {}));
  return r;
}

async function ghExplainError(r){
  let msg = "";
  try { msg = (await r.json()).message || ""; } catch (e) {}
  if (r.status === 401) return "Token rejected (401). " + (msg || "The token is wrong, expired, or was never saved.");
  if (r.status === 403) return "Token lacks permission (403). " + (msg || "For a fine-grained token set Contents: Read and write and select the netpulse repository.");
  if (r.status === 404) return "Not found (404). " + (msg || "The token probably cannot see this repository - check that netpulse is selected under Repository access.");
  return "GitHub error " + r.status + ": " + msg;
}

async function ghTestToken(){
  const t = ghToken();
  if (!t) return "No token saved yet.";
  const info = "[token: " + (t.length) + " chars, starts '" + t.slice(0, 11) + "...'] ";
  if (!/^(github_pat_|ghp_|gho_|ghs_|ghu_)/.test(t)) {
    return info + "That does not look like a GitHub token - it should start with github_pat_ or ghp_.";
  }
  const r = await ghFetch("https://api.github.com/user");
  if (!r.ok) return info + await ghExplainError(r);
  const who = (await r.json()).login;
  const repo = await ghFetch(`https://api.github.com/repos/${REPO}`);
  if (!repo.ok) return info + "Signed in as " + who + ", but " + (await ghExplainError(repo));
  const j = await repo.json();
  return info + "OK - signed in as " + who + "; " + j.full_name +
         (j.permissions && j.permissions.push ? " (write access)" : " (read only - cannot add devices)");
}

async function ghGetConfig(){
  const r = await ghFetch(`https://api.github.com/repos/${REPO}/contents/cloud/config.json?ref=${BRANCH}`);
  if (!r.ok) throw new Error(await ghExplainError(r));
  const j = await r.json();
  CFG_SHA = j.sha;
  CFG = JSON.parse(decodeURIComponent(escape(atob(j.content.replace(/\\n/g, "")))));
  return CFG;
}

async function ghSaveConfig(message){
  const body = {
    message,
    content: b64e(JSON.stringify(CFG, null, 2)),
    sha: CFG_SHA,
    branch: BRANCH,
  };
  const r = await ghFetch(`https://api.github.com/repos/${REPO}/contents/cloud/config.json`, {
    method: "PUT",
    headers: { Authorization: "Bearer " + ghToken(), Accept: "application/vnd.github+json",
               "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(await ghExplainError(r));
  const j = await r.json();
  CFG_SHA = j.content && j.content.sha ? j.content.sha : CFG_SHA;
}

/* ---------------- rendering ---------------- */
function render(d){
  DATA = d; REPO = d.repo || ""; BRANCH = d.branch || "main";
  EMBEDDED_TOKEN = (d.gh_token || "").trim();
  if (d.brand) document.getElementById("brand").textContent = d.brand;
  document.getElementById("gate").style.display = "none";
  document.getElementById("app").style.display = "block";
  document.getElementById("sub").textContent =
    "Last check: " + fmtT(d.state_updated_at) + "  ·  Page built: " + fmtT(d.generated_at);
  document.getElementById("cards").innerHTML = [
    ["Total", d.total, "var(--fg)"], ["Up", d.up, "var(--up)"],
    ["Down", d.down, "var(--down)"], ["Unknown", d.unknown, "var(--muted)"],
  ].map(([l,v,c])=>`<div class="card"><div class="l">${l}</div><div class="v" style="color:${c}">${v}</div></div>`).join("");

  document.getElementById("rows").innerHTML = (d.devices||[]).map(x=>`
    <tr>
      <td>${esc(x.name)}<div style="color:var(--muted);font-size:11px">${esc(x.checks)}</div></td>
      <td><code>${esc(x.host)}</code></td>
      <td>${esc(x.group_label || x.group)}</td>
      <td><span class="b ${esc(x.status)}">${esc(String(x.status).toUpperCase())}</span></td>
      <td>${fmtLat(x.latency)}</td>
      <td>${READ_ONLY ? "" : `<button class="ghost mini" data-del="${esc(x.name)}">✕</button>`}</td>
    </tr>`).join("");

  const groups = Object.keys((d.config && d.config.groups) || {});
  const labels = (d.config && d.config.group_labels) || {};
  const opts = groups.map(g => ({ v: g, t: labels[g] || g }));
  opts.push({ v: "default", t: "Default (your personal chat)" });
  document.getElementById("d-group").innerHTML =
    opts.map(o => `<option value="${esc(o.v)}">${esc(o.t)}</option>`).join("");

  document.getElementById("foot").innerHTML = READ_ONLY
    ? "Live status, updated automatically.<br>Refresh this page for the latest check."
    : "Updated automatically by GitHub Actions.<br>Refresh this page for the latest check.";

  // clients get a read-only view: no add/remove panel
  const panel = document.querySelector(".panel");
  if (panel) panel.style.display = READ_ONLY ? "none" : "block";

  document.querySelectorAll("[data-del]").forEach(b =>
    b.addEventListener("click", () => removeDevice(b.getAttribute("data-del"))));

  const has = !!ghToken();
  document.getElementById("mgmt-state").innerHTML = has
    ? '<span class="ok">Device management is ready — add or remove devices below.</span>'
    : 'Device management needs a GitHub token. Tap <b>Set GitHub token</b> once to provide one.';
  document.getElementById("mgmt-actions").style.display = "flex";

  renderClients();
}

/* ---------------- client login management ---------------- */
function renderClients(){
  const groups = Object.keys((d && d.config && d.config.groups) || {});
  const labels = (d && d.config && d.config.group_labels) || {};
  const list = document.getElementById("client-list");
  const st = document.getElementById("client-state");
  if (!groups.length) {
    st.innerHTML = "No client groups configured yet.";
    list.innerHTML = "";
    return;
  }
  st.innerHTML = '<span class="ok">' + groups.length + ' client group(s) found.</span>';
  list.innerHTML = groups.map(g => {
    const label = labels[g] || g;
    const safe = esc(g).replace(/[^A-Za-z0-9_]/g, "_");
    return '<div class="row" style="margin-top:10px;flex-wrap:wrap">' +
      '<div style="flex:1;min-width:150px"><label>Client</label><code>' + esc(label) + ' (' + esc(g) + ')</code></div>' +
      '<input id="c-user-' + safe + '" placeholder="Username" autocomplete="off" />' +
      '<input id="c-pw-' + safe + '" type="password" placeholder="New password" autocomplete="new-password" />' +
      '<button class="ghost mini" data-csave="' + esc(g) + '">Save login</button>' +
      '<button class="ghost mini" data-cdel="' + esc(g) + '">Remove</button>' +
    '</div>';
  }).join("");
  document.querySelectorAll("[data-csave]").forEach(b =>
    b.addEventListener("click", () => saveClient(b.getAttribute("data-csave"))));
  document.querySelectorAll("[data-cdel]").forEach(b =>
    b.addEventListener("click", () => removeClient(b.getAttribute("data-cdel"))));
}

function secretName(group, kind){
  return kind + "_" + String(group).toUpperCase().replace(/[^A-Z0-9_]/g, "_");
}

async function ghGetPublicKey(){
  const r = await ghFetch(`https://api.github.com/repos/${REPO}/actions/secrets/public-key`);
  if (!r.ok) throw new Error(await ghExplainError(r));
  return await r.json();
}

async function ghSetSecret(name, value){
  try { await sodium.ready; } catch (e) {}
  const pk = await ghGetPublicKey();
  const sealed = sodium.crypto_box_seal(
    sodium.from_string(value),
    sodium.from_base64(pk.key, sodium.base64_variants.ORIGINAL)
  );
  const enc = sodium.to_base64(sealed, sodium.base64_variants.ORIGINAL);
  const r = await ghFetch(`https://api.github.com/repos/${REPO}/actions/secrets/${name}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ encrypted_value: enc, key_id: pk.key_id })
  });
  if (!r.ok) throw new Error(await ghExplainError(r) + " (token needs 'Secrets: Read and write' permission)");
}

async function ghDeleteSecret(name){
  const r = await ghFetch(`https://api.github.com/repos/${REPO}/actions/secrets/${name}`, { method: "DELETE" });
  if (!r.ok && r.status !== 404) throw new Error(await ghExplainError(r));
}

async function saveClient(group){
  const msg = document.getElementById("client-msg");
  msg.textContent = ""; msg.className = "err";
  const safe = String(group).toUpperCase().replace(/[^A-Z0-9_]/g, "_");
  const user = (document.getElementById("c-user-" + safe).value || "").trim();
  const pw = document.getElementById("c-pw-" + safe).value || "";
  if (!user || !pw) { msg.textContent = "Enter both a username and a password."; return; }
  try {
    await ghSetSecret(secretName(group, "CLIENT_USER"), user);
    await ghSetSecret(secretName(group, "CLIENT_PW"), pw);
    msg.className = "ok";
    msg.textContent = "Saved login for group '" + group + "'. It applies on the next dashboard build (~30s).";
  } catch (e) { msg.textContent = e.message; }
}

async function removeClient(group){
  const msg = document.getElementById("client-msg");
  msg.textContent = ""; msg.className = "err";
  if (!confirm('Remove client login for group "' + group + '"?')) return;
  try {
    await ghDeleteSecret(secretName(group, "CLIENT_USER"));
    await ghDeleteSecret(secretName(group, "CLIENT_PW"));
    msg.className = "ok";
    msg.textContent = "Removed login for group '" + group + "'.";
  } catch (e) { msg.textContent = e.message; }
}

/* ---------------- device actions ---------------- */
async function addDevice(){
  const err = document.getElementById("d-err");
  err.textContent = "";
  let name = document.getElementById("d-name").value.trim();
  let host = document.getElementById("d-host").value.trim();
  const type = document.getElementById("d-type").value;
  const group = document.getElementById("d-group").value;
  if (!name || !host) { err.textContent = "Name and host are required."; return; }

  // Accept "host:port" in the host box and turn it into a TCP check.
  let effectiveType = type;
  const params = {};
  const m = host.match(/^(.+?):(\\d{1,5})$/);
  if (m) {
    host = m[1];
    params.port = Number(m[2]);
    effectiveType = "tcp";
  }
  if (effectiveType === "tcp" && !params.port) {
    params.port = Number(document.getElementById("d-port").value || 443);
  }
  if (effectiveType === "http") {
    params.url = document.getElementById("d-url").value.trim() || ("https://" + host + "/");
  }
  if (/^(10\\.|192\\.168\\.|127\\.|172\\.(1[6-9]|2\\d|3[01])\\.)/.test(host)) {
    err.textContent = "That is a private address - GitHub runners cannot reach it.";
    return;
  }

  try {
    await ghGetConfig();
    CFG.devices = CFG.devices || [];
    if (CFG.devices.some(x => (x.name||"").toLowerCase() === name.toLowerCase())) {
      err.textContent = "A device with that name already exists.";
      return;
    }
    CFG.devices.push({ name, host, alert_group: group, timeout_seconds: 5,
                       checks: [{ type: effectiveType, params }] });
    await ghSaveConfig("feat(cloud): add device " + name);
    document.getElementById("mgmt-form").style.display = "none";
    err.textContent = "";
    alert("Saved as a " + effectiveType.toUpperCase() + " check on " + host +
          (params.port ? ":" + params.port : "") +
          ".\\nIt starts being checked within ~15 minutes.");
  } catch (e) { err.textContent = e.message; }
}

async function removeDevice(name){
  if (!confirm('Remove device "' + name + '" from cloud monitoring?')) return;
  try {
    // GitHub's contents API can serve a slightly stale copy right after a
    // write, so retry the lookup a couple of times before giving up.
    let found = false;
    for (let attempt = 0; attempt < 3 && !found; attempt++) {
      if (attempt) await new Promise(r => setTimeout(r, 2500));
      await ghGetConfig();
      const before = (CFG.devices || []).length;
      CFG.devices = (CFG.devices || []).filter(x => (x.name || "") !== name);
      found = CFG.devices.length !== before;
    }
    if (!found) { alert("Device not found - refresh the page and try again."); return; }
    await ghSaveConfig("chore(cloud): remove device " + name);
    alert("Removed. Refresh in a moment to see the updated list.");
  } catch (e) { alert(e.message); }
}

async function setToken(){
  const cur = ghToken();
  const t = prompt(
    "Paste a GitHub token with Contents: Read and write on " + REPO + "\\n\\n" +
    "Create one at: github.com/settings/personal-access-tokens/new\\n" +
    "  Repository access -> Only select repositories -> " + REPO + "\\n" +
    "  Permissions -> Contents -> Read and write\\n\\n" +
    "(stored only in this browser; leave empty to remove)",
    cur ? "(a token is already saved - paste a new one to replace)" : ""
  );
  if (t === null) return;
  const v = t.trim();
  if (!v || v.startsWith("(")) { if (cur) localStorage.setItem("np_gh_token", cur); return; }
  localStorage.setItem("np_gh_token", v);
  const err = document.getElementById("d-err");
  err.textContent = "Testing token...";
  const res = await ghTestToken();
  err.textContent = res;
  err.className = res.startsWith("OK") ? "ok" : "err";
  render(DATA);
}

/* ---------------- wiring ---------------- */
function onTypeChange(){
  const t = document.getElementById("d-type").value;
  document.getElementById("d-port-wrap").style.display = t === "tcp" ? "block" : "none";
  document.getElementById("d-url-wrap").style.display = t === "http" ? "block" : "none";
}

async function tryUnlock(){
  const pw = document.getElementById("pw").value;
  const user = document.getElementById("user").value;
  const err = document.getElementById("err");
  const btn = document.getElementById("go");
  err.textContent = ""; btn.disabled = true; btn.textContent = "Checking...";
  try {
    const d = await unlock(pw);
    if (HAS_USER && user.trim() !== (d.client_user || "")) {
      err.textContent = "Wrong username or password.";
      btn.disabled = false; btn.textContent = "Unlock";
      return;
    }
    sessionStorage.setItem("np_pw", pw);
    render(d);
  } catch (e) {
    err.textContent = "Wrong password (or corrupt data).";
    btn.disabled = false; btn.textContent = "Unlock";
  }
}

document.getElementById("go").addEventListener("click", tryUnlock);
document.getElementById("pw").addEventListener("keydown", e => { if (e.key === "Enter") tryUnlock(); });
document.getElementById("d-new").addEventListener("click", () => {
  document.getElementById("mgmt-form").style.display = "block"; onTypeChange();
});
document.getElementById("d-cancel").addEventListener("click", () => {
  document.getElementById("mgmt-form").style.display = "none";
});
document.getElementById("d-save").addEventListener("click", addDevice);
document.getElementById("d-token-btn").addEventListener("click", setToken);
document.getElementById("d-clear-btn").addEventListener("click", () => {
  localStorage.removeItem("np_gh_token");
  const m = document.getElementById("d-token-msg");
  m.textContent = "Token cleared. Tap 'Set GitHub token' to add a new one.";
  m.className = "ok";
  render(DATA);
});
document.getElementById("d-test-btn").addEventListener("click", async () => {
  const m = document.getElementById("d-token-msg");
  m.textContent = "Testing..."; m.className = "err";
  const res = await ghTestToken();
  m.textContent = res; m.className = res.startsWith("OK") ? "ok" : "err";
});
document.getElementById("d-type").addEventListener("change", onTypeChange);

(async () => {
  if (HAS_USER) document.getElementById("user-wrap").style.display = "block";
  // One-tap token setup: open .../#token=ghp_xxx and it is stored, then the
  // hash is removed from the address bar and history.
  try {
    const m = (location.hash || "").match(/[#&]token=([^&]+)/);
    if (m) {
      localStorage.setItem("np_gh_token", decodeURIComponent(m[1]).trim());
      history.replaceState(null, "", location.pathname + location.search);
      alert("GitHub token saved in this browser. You can now add devices.");
    }
  } catch (e) {}

  const saved = sessionStorage.getItem("np_pw");
  if (saved) { try { render(await unlock(saved)); return; } catch (e) {} }
  document.getElementById("pw").focus();
})();
</script>
</body>
</html>
"""


def write_page(out: Path, payload: dict, password: str, read_only: bool) -> None:
    blob = encrypt(payload, password) if password else encrypt(
        {"error": "no password"}, "netpulse-disabled"
    )
    has_user = bool((payload.get("client_user") or "").strip())
    html = (TEMPLATE
            .replace("__BLOB__", json.dumps(blob))
            .replace("__READ_ONLY__", "true" if read_only else "false")
            .replace("__HAS_USER__", "true" if has_user else "false"))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    password = os.environ.get("DASHBOARD_PASSWORD", "").strip()

    payload = build_payload()
    if password:
        print(f"admin dashboard: {payload['total']} devices")
    else:
        print("!! DASHBOARD_PASSWORD not set - publishing a locked placeholder")

    write_page(out_dir / "index.html", payload, password, read_only=False)
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")
    print(f"wrote {out_dir / 'index.html'}")

    # ---- per-client pages (read-only, one group each)
    config = read_json(CONFIG_PATH, {})
    labels = config.get("group_labels") or {}
    for key in (config.get("groups") or {}):
        pw = (os.environ.get("CLIENT_PW_" + key.upper()) or "").strip()
        if not pw:
            print(f"  client {key}: no password set - skipped")
            continue
        user = (os.environ.get("CLIENT_USER_" + key.upper()) or "").strip()
        mine = [d for d in payload["devices"] if d["group"] == key]
        sub = dict(payload)
        sub["devices"] = mine
        sub["total"] = len(mine)
        sub["up"] = sum(1 for d in mine if d["status"] == "up")
        sub["down"] = sum(1 for d in mine if d["status"] == "down")
        sub["unknown"] = sub["total"] - sub["up"] - sub["down"]
        sub["brand"] = f"NetPulse — {labels.get(key, key)}"
        sub["client_user"] = user
        sub.pop("gh_token", None)  # clients must never receive the admin token
        write_page(out_dir / "client" / f"{key}.html", sub, pw, read_only=True)
        print(f"  client {key}: {len(mine)} devices -> client/{key}.html")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
