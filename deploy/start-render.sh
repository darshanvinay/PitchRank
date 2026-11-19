#!/usr/bin/env bash
set -euo pipefail

if [[ ! -s .render-seed/pitchrank.sqlite3 ]]; then
  echo "SQLite snapshot missing. Run the Render build command before starting." >&2
  exit 1
fi

# Open the build's snapshot read-only on every cold start.
export DATABASE_URL='sqlite:///file:.render-seed/pitchrank.sqlite3?mode=ro&immutable=1&uri=true'
export PITCHRANK_PUBLIC=1 PITCHRANK_DAILY_REFRESH=0
unset PITCHRANK_SEED_URL PITCHRANK_SEED_SHA256 PITCHRANK_PROJECTION_DIR
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:?Render must set PORT}" --workers 1
