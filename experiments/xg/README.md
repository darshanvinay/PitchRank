# Understat xG research

This experiment adds a nullable-by-absence `match_xg` observation table. It never changes
existing matches, production Elo, APIs or UI. Raw source files are ignored by Git. Numerical
results, every configuration, fixture coverage and quarantine reasons are retained here.

## Reproduce acquisition and import

Understat's league page and `getLeagueData` endpoints returned "We will come back soon" on
2026-11-12. The explicit fallback is genuine archived Understat data from pannadata's frozen
`understat-latest` release, **not** its newer Opta data. Metadata asset ID **399247157**, updated
2026-04-18, SHA256 **edddd2a00f259ea631e9c5089939b6b35d64bef79c8ba4c4d8d8cec0534d18d3**.

Run from the PitchRank repository root. Parquet reading needs a temporary acquisition tool;
no application dependency or dependency lock file is changed:

```sh
.venv/bin/python -m pip install --target /tmp/pitchrank-xg-tools pyarrow
PYTHONPATH=backend:/tmp/pitchrank-xg-tools .venv/bin/python experiments/xg/acquire.py
.venv/bin/alembic -c backend/alembic.ini upgrade head
PYTHONPATH=backend .venv/bin/python -m app.ingestion.understat \
  data/raw/understat/metadata.json.gz \
  --archive-sha256 edddd2a00f259ea631e9c5089939b6b35d64bef79c8ba4c4d8d8cec0534d18d3 \
  --report experiments/xg/import-dry-run.json
```

Inspect the report, then add `--apply` and choose a new report filename to write xG.
The importer never creates teams/results, changes scores or marks production ratings stale.
It requires a unique existing fixture with exact historical team identities, season, date and
score. Unknown names, date/score conflicts, invalid xG and conflicting duplicate IDs are
quarantined rather than guessed. Same-source xG corrections update only the xG table; rerun
research to reflect corrections. No forecast can retrospectively know provider revisions.

## Run/resume search

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.xg_search \
  --trials 2000 --seed 20261112 --batch-size 256 --output-dir experiments/xg
```

Add `--resume` for an existing run. Checkpoints must match source, match data, xG values,
seed and configuration count. A complete run resumes without replaying completed trials.
If a checkpoint has an incomplete last line, remove only that partial line before resuming;
the runner intentionally rejects malformed checkpoints rather than silently dropping data.
The balanced finite search supports at most 2,250 unique configurations (450 per family).

Primary walk-forward: probability loss/stability. Secondary: accuracy-first. Both include A
as a fallback eligible candidate and select on three previously completed R16 seasons.
The original 42/48 reference is never eligible for selection: its settings already saw the
historical evaluation outcomes. All 48 ties are previously examined, not an untouched test set.

## Artifacts

- `report.md`, `summary.json`: measured comparisons and interpretation.
- `results.csv`: all unique xG configurations and metrics; accuracy is a fraction.
- `trials.jsonl`: all per-season probabilities and amortized batch runtime.
- `top-models.json`: exploratory top 20 with full probabilities.
- `walk-forward.json`: fold selections, validation metrics and changed predictions.
- `coverage.json`, `reimport.json`: fixture matching, league-season coverage and idempotence.
- `cutoff-coverage.json`: each club's prior xG count, latest xG date and tie fallbacks.
- `archive-crosscheck.json`: independent older Understat scrape agrees on 13,354 overlapping
  match observations within 0.0001 xG. This supports provenance, not publication-time integrity.
- `production-before.json`, `verification.json`: existing-table hashes and checks.
- `search-manifest.json`, `provenance.json`: source/data hashes and acquisition metadata.

The independent older archive is
`https://raw.githubusercontent.com/mhsendur/understat-football-data-2014-2023/7fc2d32037ea9bcb83edfbae366c70c938f03e26/football_data_csv.zip`.
Its team-history CSVs were cross-checked by league, season, home team and date against the
primary archive; no observations from it were used to fill missing values or replace data.

`interpretation.md` preserves final interpretation when a CLI resume regenerates the automated report.
Run `PYTHONPATH=backend .venv/bin/python experiments/xg/verify.py` to repeat independent replay,
matched goals-only control and existing-table preservation checks.
