"""Keep the GitHub Pages link page pointing at the current tunnel URL.

Reads the latest trycloudflare URL from cf.err.log and, if it changed, updates
https://mahfuztitas01.github.io/netpulse-link/ so the stable link always works.

Run by the "NetPulse-Link" scheduled task every 5 minutes.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "cf.err.log"
STATE = ROOT / "tools" / ".last_link_url"

OWNER = "mahfuztitas01"
REPO = "netpulse-link"
API = "https://api.github.com"


def token() -> str:
    t = os.environ.get("GITHUB_TOKEN", "")
    if t:
        return t
    # fall back to the user-scope registry value (works in scheduled tasks)
    try:
        import winreg  # type: ignore
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as k:
            return winreg.QueryValueEx(k, "GITHUB_TOKEN")[0]
    except Exception:
        return ""


def current_url() -> str | None:
    if not LOG.exists():
        return None
    text = LOG.read_text(encoding="utf-8", errors="ignore")
    urls = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", text)
    return urls[-1] if urls else None


def page_html(target: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta name="theme-color" content="#0b1020" />
<title>NetPulse</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; min-height:100vh; display:grid; place-items:center; background:#0b1020;
          color:#e6ebf5; font-family:"Segoe UI",system-ui,sans-serif; padding:24px; }}
  .card {{ background:#141a2e; border:1px solid #26304f; border-radius:16px;
           padding:28px 24px; width:min(420px,100%); text-align:center; }}
  .dot {{ width:12px; height:12px; border-radius:50%; background:#3b82f6; display:inline-block;
          box-shadow:0 0 14px #3b82f6; margin-right:8px; }}
  h1 {{ font-size:22px; margin:0 0 6px; }}
  p {{ color:#8a97b5; font-size:14px; margin:0 0 20px; line-height:1.6; }}
  a.btn {{ display:block; background:#3b82f6; color:#fff; text-decoration:none; padding:15px;
           border-radius:10px; font-weight:700; font-size:16px; }}
  code {{ font-size:12px; color:#8a97b5; word-break:break-all; display:block; margin-top:16px; }}
  .note {{ margin-top:18px; font-size:12px; color:#64748b; line-height:1.6; }}
</style>
</head>
<body>
  <div class="card">
    <h1><span class="dot"></span>NetPulse</h1>
    <p>Network monitoring dashboard<br>Tap below to open.</p>
    <a class="btn" href="{target}">Open Dashboard &rarr;</a>
    <code>{target}</code>
    <div class="note">Login with your NetPulse username &amp; password.<br>
      If this fails, your PC / tunnel is offline.</div>
  </div>
  <script>setTimeout(function(){{location.href="{target}";}},1200);</script>
</body>
</html>
"""


def main() -> int:
    url = current_url()
    if not url:
        print("no tunnel url found")
        return 0

    STATE.parent.mkdir(exist_ok=True)
    last = STATE.read_text(encoding="utf-8").strip() if STATE.exists() else ""
    if last == url:
        print(f"unchanged: {url}")
        return 0

    tok = token()
    if not tok:
        print("ERROR: GITHUB_TOKEN not available")
        return 1

    h = {
        "Authorization": f"Bearer {tok}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "netpulse-link",
    }
    with httpx.Client(timeout=45, headers=h) as c:
        content = base64.b64encode(page_html(url).encode("utf-8")).decode("ascii")
        body = {"message": f"Update dashboard link -> {url}", "content": content, "branch": "main"}
        ex = c.get(f"{API}/repos/{OWNER}/{REPO}/contents/index.html")
        if ex.status_code == 200:
            body["sha"] = ex.json()["sha"]
        r = c.put(f"{API}/repos/{OWNER}/{REPO}/contents/index.html", json=body)
        print(f"update -> {r.status_code}  ({url})")
        if r.status_code in (200, 201):
            STATE.write_text(url, encoding="utf-8")
            return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
