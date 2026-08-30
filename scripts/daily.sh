#!/usr/bin/env bash
# Daily pipeline: fetch -> extract -> export -> push (only when something changed).
# Scheduled via Windows Task Scheduler (see README); logs to data/daily.log.
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
LOG=data/daily.log
{
  echo "=== $(date -u +%Y-%m-%dT%H:%M:%SZ) daily run ==="
  .venv/bin/cti fetch || echo "FETCH FAILED (exit $?)"
  .venv/bin/cti extract --limit 30 || echo "EXTRACT FAILED (exit $?)"
  .venv/bin/cti export || { echo "EXPORT FAILED (exit $?)"; exit 1; }
  if [ -n "$(git status --porcelain site)" ]; then
    git add site
    git commit -m "data: scheduled refresh $(date -u +%F)"
    git push origin main && echo "pushed"
  else
    echo "no site changes"
  fi
} >> "$LOG" 2>&1
