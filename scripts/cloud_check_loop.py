"""Long-running monitoring loop for GitHub Actions.

GitHub's cron scheduler is best-effort (runs are often delivered minutes to
hours late), so a short job per tick cannot give sub-minute resolution. Instead
this script runs a *tight loop inside one long-lived runner*: every
``CHECK_INTERVAL_SECONDS`` seconds it runs one full round of
:func:`cloud_check.main`, so a device that goes down is alerted within ~30
seconds.

Alert state (``cloud/state.json``) lives only inside the runner and is never
committed, so the public repository never contains the device list or names.
The trade-off: when a runner is replaced (~every 5h30m) a device that is
*still* down may produce one extra alert; ``renotify_minutes`` still governs
re-alerts inside a run.

Because GitHub's dashboard cron is equally unreliable, this loop also rebuilds
and re-publishes the static dashboard every ``DASHBOARD_EVERY_SECONDS`` seconds
(calling ``scripts/refresh_dashboard.sh``), so the public dashboard stays fresh
without depending on GitHub's scheduler. Secrets required: ``TELEGRAM_BOT_TOKEN``,
``NETPULSE_CONFIG_JSON``, ``DASHBOARD_PASSWORD``, ``DASHBOARD_GH_TOKEN``,
``CLIENT_PW_UID5001..5003`` and ``LINK_REPO_TOKEN``.
"""
from __future__ import annotations

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cloud_check  # noqa: E402

for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

LOOP_SECONDS = int(os.environ.get("LOOP_SECONDS", "19800"))
CHECK_INTERVAL_SECONDS = float(os.environ.get("CHECK_INTERVAL_SECONDS", "30"))
DASHBOARD_EVERY_SECONDS = float(os.environ.get("DASHBOARD_EVERY_SECONDS", "300"))


def refresh_dashboard() -> None:
    """Rebuild + republish the static dashboard (best-effort)."""
    try:
        r = subprocess.run(
            ["bash", "scripts/refresh_dashboard.sh"],
            capture_output=True, text=True, timeout=240,
        )
        if r.stdout.strip():
            print(r.stdout.strip()[-1000:])
        if r.returncode != 0 and r.stderr.strip():
            print(r.stderr.strip()[-1000:])
    except Exception as exc:  # noqa: BLE001
        print(f"dashboard refresh error: {exc}")


def main() -> int:
    print(
        f"loop start: {LOOP_SECONDS}s total, {CHECK_INTERVAL_SECONDS}s interval, "
        f"dashboard every {DASHBOARD_EVERY_SECONDS}s"
    )
    start = time.monotonic()
    last_dash = 0.0
    rounds = 0
    while time.monotonic() - start < LOOP_SECONDS:
        round_start = time.monotonic()
        try:
            await cloud_check.main()
            rounds += 1
        except Exception as exc:  # noqa: BLE001
            print(f"round error: {exc}")
        if time.monotonic() - last_dash >= DASHBOARD_EVERY_SECONDS:
            refresh_dashboard()
            last_dash = time.monotonic()
        spent = time.monotonic() - round_start
        await asyncio.sleep(max(1.0, CHECK_INTERVAL_SECONDS - spent))
    print(f"loop done: {rounds} rounds in {time.monotonic() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
