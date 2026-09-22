"""Long-running monitoring loop for GitHub Actions.

GitHub's cron scheduler is best-effort (runs are often late by minutes) and a
short job cannot give sub-minute resolution, so this script runs a *tight loop
inside one long-lived runner*:

  * every ``CHECK_INTERVAL_SECONDS`` seconds it runs one full monitoring round
    (reusing :func:`cloud_check.main`), so a device that goes down is alerted
    within ~30 seconds;
  * every ``STATE_COMMIT_SECONDS`` seconds it commits ``cloud/state.json`` so
    the next job - queued by the ``*/5`` cron with ``cancel-in-progress: false``
    - resumes with the previous alert state instead of re-alerting.

Environment:
    TELEGRAM_BOT_TOKEN        bot token (GitHub secret, required)
    LOOP_SECONDS              how long to run before exiting (default 19800 = 5h30m)
    CHECK_INTERVAL_SECONDS    seconds between rounds (default 30)
    STATE_COMMIT_SECONDS      seconds between state commits (default 600)
    DRY_RUN=1                 print alerts instead of sending them
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

ROOT = Path(__file__).resolve().parent.parent

DURATION = int(os.environ.get("LOOP_SECONDS", "19800"))
INTERVAL = float(os.environ.get("CHECK_INTERVAL_SECONDS", "30"))
COMMIT_EVERY = float(os.environ.get("STATE_COMMIT_SECONDS", "600"))


def commit_state() -> None:
    """Stage, commit and push cloud/state.json if it changed."""
    try:
        subprocess.run(["git", "add", "-f", "cloud/state.json"], cwd=ROOT, check=False)
        staged = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=ROOT)
        if staged.returncode == 0:
            return
        subprocess.run(
            ["git", "commit", "-m", "chore(monitor): update state [skip ci]"],
            cwd=ROOT,
            check=False,
        )
        push = subprocess.run(["git", "push"], cwd=ROOT, check=False)
        print(f"state committed + pushed (push rc={push.returncode})")
    except Exception as exc:  # noqa: BLE001
        print(f"state commit failed: {exc}")


async def main() -> int:
    print(
        f"loop start: duration={DURATION}s interval={INTERVAL}s "
        f"commit_every={COMMIT_EVERY}s"
    )
    start = time.monotonic()
    last_commit = time.monotonic()
    rounds = 0
    while time.monotonic() - start < DURATION:
        round_start = time.monotonic()
        try:
            await cloud_check.main()
            rounds += 1
        except Exception as exc:  # noqa: BLE001
            print(f"round error: {exc}")
        if time.monotonic() - last_commit >= COMMIT_EVERY:
            commit_state()
            last_commit = time.monotonic()
        spent = time.monotonic() - round_start
        await asyncio.sleep(max(1.0, INTERVAL - spent))
    commit_state()
    print(f"loop done: {rounds} rounds in {time.monotonic() - start:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
