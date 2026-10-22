# Phase 3 verification — October 22, 2026

## Implemented

- `backend/app/backtesting/evaluation.py`: explicit chronological splits, pre-result walk-forward
  forecasts, and a training-frequency baseline.
- `backend/app/backtesting/optimization.py`: bounded multi-start SciPy fitting and validation selection.
- `backend/app/backtesting/metrics.py`: NumPy accuracy, Brier, log loss, and calibration with Pandas grouping.
- `backend/app/backtesting/report.py`: reproducible dataset/prediction exports, manifests, and four plots.
- `backend/app/predictions/model.py`: internal Davidson probability kernel needed for backtesting.
- `backend/app/elo/replay.py`: observer called before any result in its kickoff/day group is applied.
- `backend/app/ingestion/cli.py`: the `pitchrank backtest` command.
- `backend/tests/test_backtesting.py`: leakage, numerical metrics, fitting, and report tests.
- Updated dependency specifications/lock, backend CI, README, and methodology documentation.

The three-outcome kernel is the minimum needed to evaluate log loss. Phase 4's fixture service,
explanations, model-loading API, and FastAPI routes have not been implemented.

## Data and results

Trained on 2022-2023, selected on 2023-2024, and evaluated on the untouched 2024-2025 season.
Each period has 380 original football-data.co.uk matches. Selected candidate: `fit-1`.

Final-test results, computed from the saved predictions:

| Model | Matches | Accuracy | Brier (unscaled) | Log loss |
| --- | ---: | ---: | ---: | ---: |
| Selected Elo | 380 | 53.42% | 0.592591 | 0.991625 |
| Fixed Elo | 380 | 53.42% | 0.583998 | 0.979231 |
| Training frequency | 380 | 40.79% | 0.662550 | 1.090112 |

Lower Brier and log loss are better. Both Elo variants correctly classified 203 of 380 test matches.
The training-frequency baseline correctly classified 155. The selected fitted model improved
validation loss but performed worse than fixed Elo on final-test probability metrics. This result
was preserved; no parameter, split, or optimization-bound changes were made to improve test scores.

Training-fitted candidates and the default reference:

| Candidate | Converged/eligible | Training log loss | Validation log loss | Iterations |
| --- | --- | ---: | ---: | ---: |
| default | True | 1.000156 | 0.949890 | 0 |
| fit-1 | True | 0.981193 | 0.935438 | 15 |
| fit-2 | True | 0.981193 | 0.935438 | 19 |
| fit-3 | True | 0.981193 | 0.935439 | 16 |

Fitted K-factor: 29.217272; home advantage: 104.040315; goal multiplier
scale: 2.000000; draw strength: 0.674309. Goal multiplier scale reached its upper bound.
Season regression stayed at 0.25 because a single training season cannot identify its effect.
Initial rating, promotion fallback, and rating scale stayed at their Phase 2 defaults.

Completed input fingerprint: `494a39f5df52ad0c55868db1f43d5b5034537c8744e816efa822c061d6992f04`.
The manifest also records original CSV SHA-256 hashes and source locations, parameters, engine
revisions, optimizer settings/status, and exact installed numerical-library versions.

## Verification performed

- Full suite: **88 passed**, with no test warnings in the final run.
- Ruff lint and formatting: **passed**.
- Alembic metadata check: **no new upgrade operations detected**; no Phase 3 migration was needed.
- Dependency consistency: **no broken requirements**.
- All three real-data solver starts: **converged, no optimizer warnings**.
- Repeated the exact original command in a new directory with the same seed and inputs:
  `selected-config.json`, `selected-elo-config.json`, `summary.json`, `predictions.csv`,
  `dataset.csv`, and `manifest.json` were **byte-for-byte identical**.
- Recomputed metrics independently from exported CSV probabilities and compared with the summary.
- Baselines and selected model use **identical evaluation match IDs**.
- Generated and visually inspected calibration, model comparison, cumulative loss, and season charts.
- Backtesting leaves existing production Elo versions/history and processing flags unchanged.

Automated cases use synthetic temporary databases and do not call external services. They verify
future/current results cannot enter earlier forecasts, pre-group prediction order, objective/holdout
separation, identical baseline periods, hand-calculated metrics, calibration counts and empty states,
optimizer reproducibility/bounds/failures, and atomic output failure cleanup.

Only Python 3.13 was executed locally. The authored GitHub Actions workflow has not run remotely.
The first test run had a Pandas deprecation warning for the test CSV reader; that deprecated option
was removed, and the complete suite passed without warnings. No failed checks were skipped.

## Artifacts

Local report directory: `reports/phase-3/`. Exact rerun: `reports/phase-3-reproduction/`.
Both are ignored by Git. The main report includes:

- `summary.json` and `manifest.json`.
- `dataset.csv`: all 1,140 completed input matches.
- `predictions.csv`: **2,280 rows** = 760 validation/test matches × three models.
- `calibration-validation.csv`, `calibration-test.csv`.
- `selected-config.json`, `selected-elo-config.json`.
- `calibration.png`, `performance-over-time.png`, `performance-by-season.png`, `model-comparison.png`.

## Run and verify

From `/Users/darshan/Documents/PitchRank/PitchRank`:

```sh
source .venv/bin/activate
python -m pip install -r backend/requirements-dev.lock
python -m pip install --no-deps -e ./backend
MPLCONFIGDIR=/tmp/pitchrank-matplotlib pitchrank backtest \
  --train 2022-2023 --validation 2023-2024 --test 2024-2025 \
  --output reports/my-experiment --starts 3 --maxiter 150 --seed 42
pytest -q backend/tests
ruff check backend
ruff format --check backend
alembic -c backend/alembic.ini check
```

Use a new destination; an existing report directory is refused. See `backtesting-methodology.md`
for formulas, leakage protections, initialization assumptions, metrics, and report contents.

## Limits and next phase

One season for each split is a limited initial evaluation. Sparse calibration bins are noisy;
no confidence intervals or betting-profit claims are made. The original Phase 2 default ratings
remain unchanged. This phase exports fitted configurations rather than silently promoting a model
based on final-test performance. No further tuning should use this test season as an unseen holdout.

Phase 4 requires user approval before beginning. It will expose the fitted prediction model through
services and FastAPI, add understandable explanations, and test scheduled/hypothetical matchups.
The React website and Taste/Web Design Guidelines review remain in Phase 6.
