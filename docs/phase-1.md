# Phase 1 verification — October 22, 2026

## Implemented

Created the backend package and development configuration (`backend/pyproject.toml` and the
resolved `requirements-dev.lock`), SQLAlchemy schema and SQLite session setup, initial Alembic
migration, explicit club mappings, historical ingestion service and CLI, and deterministic tests.
Added `.env.example`, `.gitignore`, backend CI, README, data design notes, and the original brief.

Tables: teams, team_aliases, matches, import_runs, match_observations, model_versions, rating_history.

## Actual results

Verified locally using Python 3.13.13:

- `pytest -q backend/tests`: **22 passed**.
- `ruff check backend`: **passed**.
- `ruff format --check backend`: **12 files already formatted**.
- `alembic -c backend/alembic.ini upgrade head`: **passed**.
- `alembic -c backend/alembic.ini check`: **no new upgrade operations detected**.
- Migration upgrade, downgrade to base, and upgrade again: **passed in isolated test database**.
- Original provider CSV imports: **380 matches each** for 2022-2023, 2023-2024, and 2024-2025.
- Local repeat import of 2023-2024: **0 inserted, 0 updated, 380 unchanged**.
- Database: **51 canonical clubs; 1,140 unique matches**.
- SQLite `PRAGMA integrity_check`: **ok**.
- SQLite `PRAGMA foreign_key_check`: **no violations**.

The downloaded CSVs remain in ignored `data/raw/`, and the migrated/populated database remains
in ignored `data/pitchrank.sqlite3`. The original Python download failed because its default TLS
trust store could not validate the certificate. Retrying with `SSL_CERT_FILE=/etc/ssl/cert.pem`
succeeded, with TLS verification enabled. Local automated tests do not need network access.

The GitHub Actions workflow was authored for Python 3.12 and 3.13 but has not run on GitHub.
Only Python 3.13 was executed locally. No remote code was pushed and no deployment was performed.

## Verify on this machine

From `/Users/darshan/Documents/PitchRank/PitchRank`:

```sh
source .venv/bin/activate
pitchrank status
pitchrank import --season 2023-2024 --file data/raw/E0-2023-2024.csv
pytest -q backend/tests
ruff check backend
ruff format --check backend
alembic -c backend/alembic.ini check
```

See the README for installation and fresh database migration/import instructions.

## Phase boundary

Phase 2 has not started. No Elo engine, predictions, backtests, live API integration, FastAPI routes,
or frontend has been built. The empty model and rating tables prepare the schema for later work.
User approval is required before proceeding to Phase 2, per the project brief.

## Website design requirement

Use the installed Taste Skill for frontend direction and visual verification, and Web Design
Guidelines for the UI review. The installed collection contains many design styles but no separately
named Awesome Design MD skill. Choose an appropriate style with the user when the design decision
is concrete; Phase 1 makes no visual design commitment. Honor actual data, accessible controls,
responsive behavior, and working light/dark modes as required by the brief.
