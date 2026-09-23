#!/usr/bin/env bash
set -uo pipefail

# Rebuild the static dashboard and publish it to the netpulse-link repo so the
# public dashboard stays fresh without waiting on GitHub's unreliable cron.
# Called by cloud_check_loop.py on a short interval (DASHBOARD_EVERY_SECONDS).
#
# The link repo is cloned ONCE into RUNNER_TEMP and reused across refreshes
# (a fresh `--depth 1` clone every few seconds would be wasteful); we `git pull
# --ff-only` before writing so we never clobber a newer commit.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python scripts/build_dashboard.py docs || { echo "dashboard build failed"; exit 1; }

if [ -z "${LINK_REPO_TOKEN:-}" ]; then
  echo "LINK_REPO_TOKEN not set - skipping publish"
  exit 0
fi

TMP="${RUNNER_TEMP:-/tmp}"
LINK="$TMP/netpulse-link-cache"

if [ -d "$LINK/.git" ]; then
  cd "$LINK"
  git fetch --depth 1 origin main >/dev/null 2>&1 || true
  git reset --hard origin/main >/dev/null 2>&1 || true
else
  rm -rf "$LINK"
  git clone --depth 1 \
    "https://x-access-token:${LINK_REPO_TOKEN}@github.com/mahfuztitas01/netpulse-link.git" "$LINK" \
    || { echo "clone failed"; exit 1; }
  cd "$LINK"
fi

rm -f "$LINK/index.html" "$LINK/.nojekyll"
rm -rf "$LINK/client"
cp -r "$ROOT/docs/." "$LINK/"

git config user.name "netpulse-bot"
git config user.email "netpulse-bot@users.noreply.github.com"
git add -A
if git diff --cached --quiet; then
  echo "dashboard unchanged"
else
  git commit -m "chore: update NetPulse dashboard [skip ci]"
  git push
  echo "dashboard published"
fi
