#!/usr/bin/env bash
set -euo pipefail

python deploy/seed-sqlite.py
unset PITCHRANK_SEED_URL PITCHRANK_SEED_SHA256
alembic -c backend/alembic.ini upgrade head
exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:?Render must set PORT}" --workers 1
