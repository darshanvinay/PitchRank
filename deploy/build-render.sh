#!/usr/bin/env bash
set -euo pipefail

export DATABASE_URL=sqlite:///.render-seed/pitchrank.sqlite3
python deploy/seed-sqlite.py
alembic -c backend/alembic.ini upgrade head
