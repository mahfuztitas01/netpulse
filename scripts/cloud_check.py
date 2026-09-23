"""Standalone monitor for GitHub Actions (no database, no web server).

Runs ONE round of checks against ``cloud/config.json``, sends Telegram alerts
for state changes to the right client group, and rewrites ``cloud/state.json``
so the next run remembers what happened.

Why a separate script: a GitHub Actions job is ephemeral, so it cannot use the
SQLite database or the FastAPI app. This keeps the dependency list tiny
(``httpx`` only) so each run costs ~15 seconds of runner time.

Environment:
    TELEGRAM_BOT_TOKEN   required - bot token from @BotFather (GitHub secret)
    DRY_RUN=1            optional - print alerts instead of sending them
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

# GitHub runners are UTF-8, but a Windows console is not - make prints safe.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "cloud" / "config.json"
STATE_PATH = ROOT / "cloud" / "state.json"

TOKEN = (os.environ.get("TELEGRAM_BOT_TOKEN") or "").strip()
DRY_RUN = os.environ.get("DRY_RUN", "").strip() in ("1", "true", "yes")
API = "https://api.telegram.org"


# ---------------------------------------------------------------- helpers
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.replace(microsecond=0).isoformat()


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def esc(value: object) -> str:
    return str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def humanize(delta: timedelta) -> str:
    total = max(0, int(delta.total_seconds()))
    days, rem = divmod(total, 86400)
    hours, rem = divmod(rem, 3600)
    minutes, seconds = divmod(rem, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if not parts:
        parts.append(f"{seconds}s")
    return " ".join(parts)


def load_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


# ---------------------------------------------------------------- checks
async def check_ping(host: str, params: dict, timeout: float) -> tuple[bool, float | None, str]:
    count = int(params.get("count", 1))
    if sys.platform.startswith("win"):
        args = ["ping", "-n", str(count), "-w", str(int(timeout * 1000)), host]
    else:
        args = ["ping", "-c", str(count), "-W", str(max(1, int(round(timeout)))), host]
    started = time.perf_counter()
    try:
        proc = await asyncio.create_subprocess_exec(
            *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        try:
            await asyncio.wait_for(proc.communicate(), timeout=timeout + 3)
        except asyncio.TimeoutError:
            proc.kill()
            return False, None, "ping timeout"
        if proc.returncode == 0:
            return True, round((time.perf_counter() - started) * 1000, 2), ""
        return False, None, "no ICMP reply"
    except FileNotFoundError:
        return False, None, "ping binary not available"
    except Exception as exc:  # noqa: BLE001
        return False, None, f"ping error: {exc}"


async def check_tcp(host: str, params: dict, timeout: float) -> tuple[bool, float | None, str]:
    port = params.get("port")
    if not port:
        return False, None, "tcp check needs a port"
    started = time.perf_counter()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, int(port)), timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:  # noqa: BLE001
            pass
        return True, round((time.perf_counter() - started) * 1000, 2), ""
    except asyncio.TimeoutError:
        return False, None, f"tcp {port} timeout"
    except (socket.gaierror, ConnectionRefusedError, OSError) as exc:
        return False, None, f"tcp {port}: {exc}"


async def check_http(host: str, params: dict, timeout: float) -> tuple[bool, float | None, str]:
    url = params.get("url") or f"http://{host}/"
    expect = int(params.get("expect_status", 200))
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=timeout, verify=False) as client:
            resp = await client.get(url, follow_redirects=True)
        if resp.status_code == expect:
            return True, round((time.perf_counter() - started) * 1000, 2), ""
        return False, None, f"http {resp.status_code} (expected {expect})"
    except httpx.HTTPError as exc:
        return False, None, f"http: {exc}"


async def run_check(check: dict, host: str, timeout: float):
    ctype = str(check.get("type", "ping")).lower()
    params = check.get("params") or {}
    if ctype == "ping":
        return await check_ping(host, params, timeout)
    if ctype == "tcp":
        return await check_tcp(host, params, timeout)
    if ctype == "http":
        return await check_http(host, params, timeout)
    return False, None, f"unsupported check type in cloud: {ctype}"


# GitHub-hosted runners block outbound ICMP, so a ping check can never succeed
# there. When that happens we fall back to a TCP connect on a common port and
# report the device as reachable if any of them answers.
FALLBACK_TCP_PORTS = (443, 80, 22, 53)


async def ping_with_fallback(host: str, params: dict, timeout: float):
    ok, latency, error = await check_ping(host, params, timeout)
    if ok:
        return ok, latency, error
    for port in FALLBACK_TCP_PORTS:
        ok2, lat2, _ = await check_tcp(host, {"port": port}, timeout)
        if ok2:
            return True, lat2, ""
    return False, None, f"{error} (tcp fallback {','.join(map(str, FALLBACK_TCP_PORTS))} also failed)"


# ---------------------------------------------------------------- telegram
async def send(text: str, chat_id: str) -> bool:
    if DRY_RUN:
        print(f"[DRY_RUN] would send to {chat_id}:\n{text}\n")
        return True
    if not TOKEN:
        print("!! TELEGRAM_BOT_TOKEN is not set - cannot send")
        return False
    if not chat_id:
        print("!! no chat id configured for this alert - skipping")
        return False
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                f"{API}/bot{TOKEN}/sendMessage",
                json={
                    "chat_id": str(chat_id),
                    "text": text,
                    "parse_mode": "HTML",
                    "disable_web_page_preview": True,
                },
            )
        if resp.status_code != 200:
            print(f"!! telegram error {resp.status_code}: {resp.text[:200]}")
            return False
        print(f"telegram sent -> chat {chat_id}")
        return True
    except httpx.HTTPError as exc:
        print(f"!! telegram request failed: {exc}")
        return False


# ---------------------------------------------------------------- main
async def main() -> int:
    config = load_json(CONFIG_PATH, {})
    devices = config.get("devices") or []
    groups = config.get("groups") or {}
    default_chat = str(config.get("default_chat_id") or groups.get("default") or "")
    renotify_minutes = int(config.get("renotify_minutes", 30))
    digest_minutes = int(config.get("digest_minutes", 60))
    latency_threshold = config.get("latency_threshold_ms")
    ping_fallback = bool(config.get("ping_fallback_tcp", True))

    if not devices:
        print("cloud/config.json has no devices - nothing to do")
        return 0

    state = load_json(STATE_PATH, {})
    prev_devices = state.get("devices") or {}
    last_digest = parse_iso(state.get("last_digest"))
    now = utcnow()

    print(f"checking {len(devices)} device(s) at {iso(now)}")

    async def one(dev: dict):
        name = dev.get("name") or dev.get("host") or "unnamed"
        host = dev.get("host") or ""
        timeout = float(dev.get("timeout_seconds", 5))
        checks = dev.get("checks") or [{"type": "ping", "params": {}}]

        async def rc(check: dict):
            ctype = str(check.get("type", "ping")).lower()
            if ctype == "ping" and ping_fallback:
                return await ping_with_fallback(host, check.get("params") or {}, timeout)
            return await run_check(check, host, timeout)

        results = await asyncio.gather(*(rc(c) for c in checks))
        ok = any(r[0] for r in results)
        lats = [r[1] for r in results if r[0] and r[1] is not None]
        latency = min(lats) if lats else None
        errors = "; ".join(f"{c.get('type')}: {r[2]}" for c, r in zip(checks, results) if not r[0])
        return name, host, ok, latency, errors or "no response"

    results = await asyncio.gather(*(one(d) for d in devices))

    new_state: dict[str, dict] = {}
    up = down = 0
    down_names: list[str] = []

    for dev, (name, host, ok, latency, errors) in zip(devices, results):
        group_name = str(dev.get("alert_group") or "default")
        chat_id = str(groups.get(group_name) or default_chat)
        prev = prev_devices.get(name) or {}
        prev_status = prev.get("status")
        status = "up" if ok else "down"
        entry = dict(prev)
        entry["status"] = status
        entry["latency_ms"] = latency

        if status == "up":
            up += 1
        else:
            down += 1
            down_names.append(name)

        if status == "down" and prev_status != "down":
            # fires on a real transition AND the first time we ever see a device down
            entry["last_down"] = iso(now)
            entry["last_change"] = iso(now)
            entry["last_alert"] = iso(now)
            await send(
                "🔴 <b>DEVICE DOWN</b>\n"
                f"<b>Name:</b> {esc(name)}\n"
                f"<b>Host:</b> <code>{esc(host)}</code>\n"
                f"<b>Group:</b> {esc(group_name)}\n"
                f"<b>Reason:</b> {esc(errors)}\n"
                f"<i>via GitHub Actions</i>",
                chat_id,
            )
        elif status == "up" and prev_status == "down":
            down_at = parse_iso(entry.get("last_down"))
            dtxt = humanize(now - down_at) if down_at else "unknown"
            entry["last_change"] = iso(now)
            entry["last_alert"] = iso(now)
            await send(
                "🟢 <b>DEVICE UP</b>\n"
                f"<b>Name:</b> {esc(name)}\n"
                f"<b>Host:</b> <code>{esc(host)}</code>\n"
                f"<b>Group:</b> {esc(group_name)}\n"
                f"<b>Downtime:</b> {esc(dtxt)}\n"
                f"<i>via GitHub Actions</i>",
                chat_id,
            )
        elif status == "down" and prev_status == "down":
            last_alert = parse_iso(entry.get("last_alert"))
            if last_alert is None or (now - last_alert) >= timedelta(minutes=renotify_minutes):
                entry["last_alert"] = iso(now)
                await send(
                    "🔴 <b>DEVICE STILL DOWN</b>\n"
                    f"<b>Name:</b> {esc(name)}\n"
                    f"<b>Host:</b> <code>{esc(host)}</code>\n"
                    f"<b>Reason:</b> {esc(errors)}",
                    chat_id,
                )
        elif status == "up" and latency_threshold and latency and latency > latency_threshold:
            print(f"  {name}: high latency {latency} ms")

        new_state[name] = entry
        print(f"  {name:24} {status:4} latency={latency}")

    # ---- per-group digest
    digest_due = last_digest is None or (now - last_digest) >= timedelta(minutes=digest_minutes)
    if digest_due:
        labels = config.get("group_labels") or {}
        buckets: dict[str, list[str]] = {}
        for dev in devices:
            g = str(dev.get("alert_group") or "default")
            buckets.setdefault(g, []).append(dev.get("name") or dev.get("host") or "?")
        for group_name, names in buckets.items():
            g_down = [n for n in names if new_state.get(n, {}).get("status") == "down"]
            if not g_down:
                continue  # only summarize groups that have something down
            chat_id = str(groups.get(group_name) or default_chat)
            label = labels.get(group_name) or (
                "Default" if group_name == "default" else group_name
            )
            g_up = len(names) - len(g_down)
            lines = [
                f"🔴 <b>NetPulse — {esc(label)}</b>",
                f"Total: <b>{len(names)}</b>   Up: <b>{g_up}</b>   Down: <b>{len(g_down)}</b>",
                "",
                "<b>DOWN now:</b>",
            ]
            lines += [f"• {esc(n)}" for n in g_down[:15]]
            await send("\n".join(lines), chat_id)
        state["last_digest"] = iso(now)
    else:
        state["last_digest"] = state.get("last_digest")

    state["devices"] = new_state
    state["updated_at"] = iso(now)
    STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True), encoding="utf-8")

    print(f"done: up={up} down={down}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
