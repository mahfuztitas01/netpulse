"""Build a static, password-protected dashboard for GitHub Pages.

Why static: GitHub Pages only serves static files, and it is the one free host
that needs no account of its own. The GitHub Actions monitor runs this after
every check, so the published page reflects the latest state.

Privacy: the payload is encrypted with AES-GCM using a key derived from
DASHBOARD_PASSWORD (PBKDF2-SHA256). The public repo only ever holds ciphertext;
the browser decrypts it locally after the password is entered.

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

    devices = []
    for dev in config.get("devices") or []:
        name = dev.get("name") or dev.get("host") or "unnamed"
        entry = prev.get(name) or {}
        devices.append(
            {
                "name": name,
                "host": dev.get("host") or "",
                "group": dev.get("alert_group") or "default",
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
  .wrap { max-width:820px; margin:0 auto; }
  h1 { font-size:20px; margin:0 0 4px; display:flex; align-items:center; gap:8px; }
  .dot { width:10px; height:10px; border-radius:50%; background:#3b82f6; box-shadow:0 0 12px #3b82f6; }
  .sub { color:var(--muted); font-size:12px; margin-bottom:16px; }
  .cards { display:grid; grid-template-columns:repeat(auto-fit,minmax(96px,1fr)); gap:10px; margin-bottom:16px; }
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
          padding:26px 22px; max-width:380px; margin:12vh auto 0; text-align:center; }
  .gate h2 { margin:0 0 6px; font-size:18px; }
  .gate p { color:var(--muted); font-size:13px; margin:0 0 16px; }
  input { width:100%; padding:13px; border-radius:10px; border:1px solid var(--border);
          background:#0e1424; color:var(--fg); font-size:15px; }
  button { width:100%; margin-top:10px; padding:13px; border:none; border-radius:10px;
           background:#3b82f6; color:#fff; font-weight:700; font-size:15px; cursor:pointer; }
  button:disabled { opacity:.6; cursor:default; }
  .err { color:var(--down); font-size:13px; margin-top:10px; min-height:18px; }
  .foot { color:#64748b; font-size:11px; margin-top:14px; line-height:1.6; text-align:center; }
</style>
</head>
<body>
<div class="wrap">
  <div id="gate" class="gate">
    <h2><span class="dot"></span> NetPulse</h2>
    <p>Enter the dashboard password to view live status.</p>
    <input id="pw" type="password" autocomplete="current-password" placeholder="Password" />
    <button id="go">Unlock</button>
    <div class="err" id="err"></div>
  </div>
  <div id="app" style="display:none">
    <h1><span class="dot"></span> NetPulse</h1>
    <div class="sub" id="sub"></div>
    <div class="cards" id="cards"></div>
    <table>
      <thead><tr><th>Device</th><th>Host</th><th>Group</th><th>Status</th><th>Latency</th></tr></thead>
      <tbody id="rows"></tbody>
    </table>
    <div class="foot" id="foot"></div>
  </div>
</div>

<script>
const BLOB = __BLOB__;
const S = { salt: b64d(BLOB.salt), iv: b64d(BLOB.iv), ct: b64d(BLOB.ct), iter: BLOB.iter };
function b64d(s){ const b=atob(s); const a=new Uint8Array(b.length); for(let i=0;i<b.length;i++) a[i]=b.charCodeAt(i); return a; }
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

function render(d){
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
      <td>${esc(x.group)}</td>
      <td><span class="b ${esc(x.status)}">${esc(String(x.status).toUpperCase())}</span></td>
      <td>${fmtLat(x.latency)}</td>
    </tr>`).join("");
  document.getElementById("foot").innerHTML =
    "Updated automatically by GitHub Actions.<br>Refresh this page for the latest check.";
}

async function tryUnlock(){
  const pw = document.getElementById("pw").value;
  const err = document.getElementById("err");
  const btn = document.getElementById("go");
  err.textContent = ""; btn.disabled = true; btn.textContent = "Checking...";
  try {
    const d = await unlock(pw);
    sessionStorage.setItem("np_pw", pw);
    render(d);
  } catch (e) {
    err.textContent = "Wrong password (or corrupt data).";
    btn.disabled = false; btn.textContent = "Unlock";
  }
}

document.getElementById("go").addEventListener("click", tryUnlock);
document.getElementById("pw").addEventListener("keydown", e => { if (e.key === "Enter") tryUnlock(); });
(async () => {
  const saved = sessionStorage.getItem("np_pw");
  if (saved) {
    try { render(await unlock(saved)); return; } catch (e) {}
  }
  document.getElementById("pw").focus();
})();
</script>
</body>
</html>
"""


def main() -> int:
    out_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "docs"
    password = os.environ.get("DASHBOARD_PASSWORD", "").strip()

    payload = build_payload()

    if password:
        blob = encrypt(payload, password)
        print(f"encrypted dashboard ({len(blob['ct'])} b64 chars)")
    else:
        # No password set -> publish a placeholder rather than leaking data.
        blob = encrypt({"error": "DASHBOARD_PASSWORD not set"}, "netpulse-disabled")
        print("!! DASHBOARD_PASSWORD not set - publishing a locked placeholder")

    html = TEMPLATE.replace("__BLOB__", json.dumps(blob))
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "index.html").write_text(html, encoding="utf-8")
    (out_dir / ".nojekyll").write_text("", encoding="utf-8")

    print(f"wrote {out_dir / 'index.html'}")
    print(f"  devices: {payload['total']}  up={payload['up']} down={payload['down']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
