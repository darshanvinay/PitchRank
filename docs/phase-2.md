# Phase 2 verification — October 22, 2026

## Implemented

- `backend/app/core/elo.py`: validated immutable parameters, JSON loading, version hashes.
- `backend/app/elo/engine.py`: pure expected score, margin multiplier, zero-sum match updates.
- `backend/app/elo/replay.py`: deterministic kickoff/day grouping and season transitions.
- `backend/app/services/ratings.py`: atomic versioned replay, stale checks, historical rankings.
- `backend/app/ingestion/cli.py`: `elo rebuild` and `elo rankings` commands.
- `backend/app/db/models.py` and migration `f53fc3259700`: replay input fingerprint.
- `backend/tests/test_elo.py`: Elo, replay, model isolation, correction, and rollback tests.
- README, data design notes, Elo methodology, and example JSON configuration.

## Checks performed

- Full local suite: **61 passed** (22 existing tests plus 39 Phase 2 test cases).
- Ruff lint and formatting: **passed; 20 Python files formatted**.
- Forced replay of the real dataset: **exactly reproduced all stored rating values**.
- Unchanged replay: **no-op, with 2,280 history rows retained**.
- Real-data zero-sum check: **all 1,140 matches passed**.
- SQLite integrity and foreign keys after replay: **passed**.
- Alembic migration applied to the existing Phase 1 database: **passed**.
- Alembic metadata check: **no new upgrade operations detected**.
- Migration upgrade/downgrade/upgrade round trip: **passed in the automated suite**.
- Real-data replay: **1,140 completed matches, 2,280 rating-history rows**.
- Historical rankings: **20 clubs, season 2024-2025, as of May 25, 2025**.

The initial correction test picked Newcastle's unchanged pre-match rating rather than the shared
club's changed rating. That assertion was corrected to inspect downstream pre-match ratings; the
full suite then passed. No failed test was skipped or disabled.

Test cases cover expected scores, home advantage, wins/draws/losses, exact opposite deltas, margin
behavior, extreme/invalid inputs, configuration identity, chronological ordering, ambiguous dates,
season regression, promotion averages, returning clubs, missing seasons, repeat/forced replay,
model separation, corrected results, stale reads, unfinished statuses, and write-failure rollback.
All automated tests use synthetic data and temporary databases; real imports remain separate.

No new external dependency was required. GitHub CI has not run; Python 3.13 was verified locally.
No optimization, backtesting metrics, three-outcome predictions, HTTP endpoints, website, or live
synchronization was added. Ratings use documented untuned parameters.

## Run and verify

From `/Users/darshan/Documents/PitchRank/PitchRank`:

```sh
source .venv/bin/activate
alembic -c backend/alembic.ini upgrade head
pitchrank elo rebuild
pitchrank elo rankings
pytest -q backend/tests
ruff check backend
ruff format --check backend
alembic -c backend/alembic.ini check
```

The rebuild returns `rebuilt: false` when inputs and configuration have not changed. Add `--force`
to reproduce the full replay. See `elo-methodology.md` for configuration and season assumptions.

Phase 3 (walk-forward evaluation and parameter optimization) requires user approval before starting.
