#!/usr/bin/env bash
set +x
set -euo pipefail

export DATABASE_URL=sqlite:///.render-seed/pitchrank.sqlite3
python deploy/seed-sqlite.py
unset PITCHRANK_SEED_URL PITCHRANK_SEED_SHA256
alembic -c backend/alembic.ini upgrade head
