#!/usr/bin/env bash
set -uo pipefail

# Build the static dashboard and publish it to netpulse-link.
# Called periodically by the long-running monitor loop so the dashboard stays
# fresh even though GitHub's scheduler delays the separate cron workflow.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== [dashboard] building ==="
python scripts/build_dashboard.py docs || { echo "build failed"; exit 1; }

if [ -z "${LINK_REPO_TOKEN:-}" ]; then
  echo "LINK_REPO_TOKEN not set - skipping publish"
  exit 0
fi

echo "=== [dashboard] publishing ==="
TMP="${RUNNER_TEMP:-/tmp}"
LINK="$TMP/netpulse-link-pub"
rm -rf "$LINK"
git clone --depth 1 "https://x-access-token:${LINK_REPO_TOKEN}@github.com/mahfuztitas01/netpulse-link.git" "$LINK"
rm -f "$LINK/index.html" "$LINK/.nojekyll"
rm -rf "$LINK/client"
cp -r "$ROOT/docs/." "$LINK/"
cd "$LINK"
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
