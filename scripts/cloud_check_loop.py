"""Long-running monitoring loop for GitHub Actions.

GitHub's cron scheduler is best-effort (runs are often late by minutes) and a
short job cannot give sub-minute resolution, so this script runs a *tight loop
inside one long-lived runner*: every ``CHECK_INTERVAL_SECONDS`` seconds it runs
one full monitoring round (reusing :func:`cloud_check.main`), so a device that
goes down is alerted within ~30 seconds.

The alert state (``cloud/state.json``) lives only inside the runner and is
never committed, so the public repository never contains the device list or
names. The trade-off: when a runner is replaced (~every 5h30m) a device that is
*still* down may produce one extra alert. ``renotify_minutes`` still governs
re-alerts inside a run.

Environment:
    TELEGRAM_BOT_TOKEN        bot token (GitHub secret, required)
    NETPULSE_CONFIG_JSON      device list as JSON (GitHub secret)
    LOOP_SECONDS              how long to run before exiting (default 19800 = 5h30m)
    CHECK_INTERVAL_SECONDS    seconds between rounds (default 30)
    DRY_RUN=1                 print alerts instead of sending them
"""
from __future__ import annotations

import asyncio
import os
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

DURATION = int(os.environ.get("LOOP_SECONDS", "19800"))
INTERVAL = float(os.environ.get("CHECK_INTERVAL_SECONDS", "30"))


async def main() -> int:
    print(f"loop start: duration={DURATION}s interval={INTERVAL}s")
    start = time.monotonic()
    rounds = 0
    while time.monotonic() - start < DURATION:
        round_start = time.monotonic()
        try:
            await cloud_check.main()
            rounds += 1
        except Exception as exc:  # noqa: BLE001
            print(f"round error: {exc}")
        spent = time.monotonic() - round_start
        await asyncio.sleep(max(1.0, INTERVAL - spent))
    print(f"loop done: {rounds} rounds in {time.monotonic() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
