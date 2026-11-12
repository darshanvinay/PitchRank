# Offline Elo search

Run from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.model_search \
  --trials 10000 --seed 20261111 --search-method hybrid --batch-size 512 \
  --max-seconds 600 --output-dir experiments
```

Add `--resume` to continue the same configuration/data/source manifest. Increase `--max-seconds`
if needed. The current installation has no Optuna; `hybrid` uses seeded random search and local
refinement based only on early training seasons. `random` skips local refinement. No package is
installed and the production SQLite database is read-only throughout.

Optional cohort arguments are `--training-seasons 2013-2014 ... 2019-2020` and
`--evaluation-seasons 2020-2021 ... 2025-2026`. Defaults reproduce these cohorts. Each evaluation
fold selects using its last three completed earlier seasons. Primary selection balances log loss
and seasonal stability; the declared accuracy-oriented secondary strategy is reported separately.

Outputs:

- `report.md`: baseline, exploratory results, both walk-forward protocols and robustness analysis.
- `results.csv`: every search and diagnostic trial, parameters, scores, time and per-season metrics.
- `top_models.json`: search top 20, early-development top 20 and all-trial top five.
- `walk_forward.json`: every fold's selected configuration, past validation seasons and predictions.
- `robustness.json`, `analysis.json`: perturbations, ablations, changed ties and uncertainty.
- `manifest.json`, `summary.json`, `timing.json`, `benchmark.json`: provenance/runtime metadata.
- Local `trials.jsonl` and `diagnostics.jsonl`: full raw/calibrated forecasts and resume checkpoints.
  These large checkpoints are ignored by Git; retain them locally to resume without recomputing.

All trial timings are amortized batch wall time. Required CSV/JSON reports do not depend on a
checkpoint being published. To reproduce all raw predictions on another machine, rebuild the same
reviewed historical database and rerun with the saved manifest parameters. This research run assumes
the production baseline and its helper functions remain unchanged. Model A's evaluation predictions
are compared with a fresh run of the original backtester before search.

The highest exploratory score is selected on the same historical sample. It is not a reason to
change production. Historical seasons have already appeared in other PitchRank studies, so even
chronological walk-forward results need a fresh prospective test before promotion.

`interpretation.md` is the final human analysis, also prefixed to the finalized `report.md`.
A later CLI resume regenerates the automated report; retain `interpretation.md` for the original
conclusions. `verification.json` records byte-identical resume checks. The independent scalar check
for this run's simple best candidate can be repeated with:

```sh
PYTHONPATH=backend .venv/bin/python experiments/verify_selected.py
```

`scalar-verification.json` records agreement across 120 ties. The helper intentionally rejects a
future best candidate with an unsupported complex profile rather than falsely claiming verification.

CSV accuracy values are fractions (multiply by 100 for percentages). Per-trial `seconds` is
amortized replay time; the log's ETA estimates remaining replay work, while `summary.json` includes
cache, ranking, reporting and resume wall time. `run.log` and `resume.log` retain this completed run's
progress and verification output.
