# Backtesting and optimization methodology

## What Phase 3 implements

The experiment runner reads a consistent SQLite snapshot, fits candidates, selects a configuration
using validation log loss, evaluates frozen models walk-forward, and exports a complete local report.
It does not modify production Elo model versions, match processing flags, or rating history.
No HTTP prediction endpoints or live fixture forecasts are implemented in this phase.

## Three outcomes

Backtesting needs a three-outcome model before prediction endpoints are implemented. The internal
probability kernel uses the [Davidson extension of paired comparisons with ties](https://www.tandfonline.com/doi/abs/10.1080/01621459.1970.10481082).
For a normalized Elo difference `d = ln(10) * (home - away + HFA) / rating_scale` and positive fitted
draw strength `nu`, unnormalized home/draw/away weights are:

```
exp(d / 2), nu, exp(-d / 2)
```

Normalize by their sum to obtain probabilities. The implementation uses a max-shifted softmax for
numerical stability. At equal effective strength, draw probability is `nu / (2 + nu)`; it decreases
as the strength gap increases. Conditional on a decisive result, the home/away odds follow the Elo
logistic curve. This is a probability model, not a claim that Elo expected score is home-win probability.
The draw parameter is fitted on historical training outcomes jointly with Elo parameters; it is
never estimated from validation or test outcome frequencies.

## Splits and information boundaries

The initial experiment uses:

| Role | Season | Matches | Use |
| --- | --- | ---: | --- |
| Training | 2022-2023 | 380 | Fit parameters and outcome-frequency baseline |
| Validation | 2023-2024 | 380 | Select among training-fitted candidates and untuned reference |
| Final test | 2024-2025 | 380 | Evaluate the frozen selected model and baselines |

The CLI requires explicit, unique, chronological season lists. Every selected database season must
be assigned exactly once, and actual match dates across roles must not overlap. Multiple seasons
per role are supported. Unfinished fixtures are excluded. Season membership is inferred from completed
data; use complete historical seasons. Names/rosters are not inferred from future goal counts.

`fit_parameters(train, validation)` has no test-data argument. The objective receives training
matches only. Validation is replayed after the full training period and used only to choose among
frozen candidates. The final test is not passed to the fitter or candidate selector. Training
loss is an in-sample objective, validation performance is selection-biased, and final test results
are held out. Do not change parameters after inspecting the final test and continue calling it an
unseen holdout. A repeat with the exact same data/configuration/seed is a reproducibility check,
not new model selection.

## Walk-forward order

The Phase 2 replay engine now accepts a pre-match observer. For every kickoff group it calls all
prediction observers before applying any match update. Missing kickoff time makes the entire local
date one conservative group. Each forecast reads only pre-group Elo ratings and fixed parameters.
After predictions are recorded, actual outcomes update ratings for subsequent groups. Test-season
ratings therefore learn from earlier test results, as they would in operation; model parameters
remain frozen. Results from the current or later match cannot affect its prediction.

## Optimization

SciPy's [bounded L-BFGS-B optimizer](https://docs.scipy.org/doc/scipy/reference/optimize.minimize-lbfgsb.html)
minimizes training multiclass log loss. Every objective evaluation replays all training matches
from initial ratings with that candidate's Elo parameters. Parameters are normalized into [0,1]
for the solver, then transformed back into these bounds:

| Parameter | Bounds |
| --- | --- |
| K-factor | 5 to 60 |
| Home advantage | 0 to 150 Elo points |
| Goal multiplier scale | 0.5 to 2 |
| Davidson draw strength | 0.05 to 2 |
| Season regression, when identifiable | 0 to 0.75 |

The run uses three deterministic starts: the default configuration and two NumPy RNG starts with
seed 42, at most 150 solver iterations each. Training with only one season provides no season
transition signal, so regression is kept at the default 0.25. With multiple training seasons it is
also optimized. Initial rating, promotion fallback, and rating scale remain fixed.

Validation selects the successful candidate with minimum log loss. The untuned configuration is
also a candidate; fitting is never assumed to improve performance. Failed solver statuses are saved
and printed as warnings, and those candidates cannot be selected. Parameters at bounds are reported
as fitted, without expanding bounds in response to final-test results. Local optimization does not
guarantee a global optimum.

## Baselines

All three models use identical validation/test match IDs and chronological evaluation periods:

- **Selected Elo:** training-fitted configuration chosen on validation; may fall back to defaults.
- **Fixed Elo:** Phase 2 default Elo parameters and fixed draw strength 0.7, with no tuning.
- **Training frequency:** fixed home/draw/away counts from training, with one Laplace pseudocount per
  class. No validation/test outcomes enter these baseline frequencies.

## Metrics

NumPy computes classification accuracy (argmax, ties resolved H then D then A), multiclass log loss
(mean negative natural log of actual-outcome probabilities), and the unscaled multiclass Brier score
(mean sum of squared errors across all three outcomes, range 0 to 2). Logarithms are clipped at
1e-15 only for numerical stability. Invalid/nonfinite probability rows and unknown outcomes fail.

Pandas groups results by season and predicted outcome. A predicted class with no matches has count
zero and null metrics; the report never invents a score. Calibration uses ten equal-width bins per
outcome and records sample count, average probability, and observed frequency. Empty bins have null
means/frequencies. Sparse bins are noisy; no calibration or significance guarantee is implied.

## Artifacts and reproducibility

Each new output directory is published only after all exports and plots succeed. Existing output
directories are refused, and failed reports do not leave a partial published directory.

| Artifact | Contents |
| --- | --- |
| `manifest.json` | Dataset fingerprint, import hashes/locations, splits, seed, optimizer settings/status, all candidates, selected/default parameters, engine revisions, package versions, limitations |
| `dataset.csv` | Completed input records, including results, season, team IDs, and optional kickoffs |
| `predictions.csv` | Validation/test probabilities, pre-match Elo, actual outcome, IDs/names, date, model, and period |
| `summary.json` | Overall, seasonal, and predicted-class metrics plus calibration, for each model/period |
| `calibration-validation.csv`, `calibration-test.csv` | Counts and bin statistics for all models |
| `selected-config.json` | Full frozen probability model configuration |
| `selected-elo-config.json` | Elo-only configuration usable by `pitchrank elo rebuild --config ...` |
| Four PNG charts | Final-test calibration, cumulative log loss, model comparison, season comparison |

`reports/` is ignored by Git; retain an experiment directory to preserve its results. The pinned
Python dependency lock and recorded data hashes support reproduction on the documented Python
version. Tiny numerical differences may occur across numerical-library versions or platforms.
No betting-profit estimates, confidence intervals, cross-league claims, or live-data claims are made.
A single training/validation/test season is a limited first experiment; more data and a fresh holdout
are needed before drawing stronger conclusions.
