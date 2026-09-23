#!/usr/bin/env bash
set -uo pipefail

# Rebuild the static dashboard and publish it to the netpulse-link repo so the
# public dashboard stays fresh even though GitHub's own scheduler delays the
# separate dashboard.yml cron by hours. Called by cloud_check_loop.py every few
# minutes.

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

python scripts/build_dashboard.py docs || { echo "dashboard build failed"; exit 1; }

if [ -z "${LINK_REPO_TOKEN:-}" ]; then
  echo "LINK_REPO_TOKEN not set - skipping publish"
  exit 0
fi

echo "=== publishing dashboard ==="
TMP="${RUNNER_TEMP:-/tmp}"
LINK="$TMP/netpulse-link"
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
