# PitchRank: historical Understat xG experiment

**Recommendation: retain production Model A pending genuinely new prospective matches.**
All 48 evaluation ties have been examined previously. Walk-forward selection uses only earlier
resolved seasons, but this is a retrospective re-evaluation, not an untouched test set.
The fixed 42/48 model is an evaluation-selected comparator only; it cannot enter fold selection.

## Measured results

| Model/protocol | Correct | Accuracy | Brier | Log loss |
|---|---:|---:|---:|---:|
| Model A | 38/48 | 79.17% | 0.180565 | 0.544120 |
| Fixed exploratory 42/48 reference | 42/48 | 87.50% | 0.149449 | 0.460356 |
| Best exploratory xG | 41/48 | 85.42% | 0.175252 | 0.533391 |
| Walk-forward probability | 38/48 | 79.17% | 0.158438 | 0.492469 |
| Walk-forward accuracy | 36/48 | 75.00% | 0.169092 | 0.515954 |

Tested **20 unique xG configurations**, seed 20261112.
Search is fixed seeded random sampling, not adapted using evaluation labels.

## Best exploratory xG model

```json
{
  "family": "attack_defence",
  "window": 10,
  "half_life": 60,
  "shrink": 5,
  "feature_scale": 100,
  "k": 20,
  "xg_share": 1,
  "regression": 0.1,
  "learning_rate": 0.1,
  "prior_goals": 1.2,
  "home_log": 0.4,
  "blend": 0.75
}
```

This configuration was selected using the original 48 ties. Its historical score is exploratory.

| Season | Tie | Actual advancing team | A P(team A) | xG P(team A) | Change |
|---|---|---|---:|---:|---|
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | 56.005% | 49.653% | corrected |
| 2020-2021 | Atlético de Madrid – Chelsea | Chelsea | 59.879% | 48.065% | corrected |
| 2020-2021 | RB Leipzig – Liverpool | Liverpool | 49.768% | 54.897% | new_error |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | 48.380% | 58.059% | corrected |
| 2021-2022 | Paris Saint-Germain – Real Madrid | Real Madrid | 49.003% | 57.016% | new_error |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 60.785% | corrected |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | 45.366% | 52.529% | corrected |

## Family comparisons

| Family | Exploratory correct | Log loss | Walk-forward correct | Walk-forward log loss |
|---|---:|---:|---:|---:|
| attack_defence | 41/48 | 0.533391 | 38/48 | 0.537506 |
| differential | 38/48 | 0.481495 | 39/48 | 0.485696 |
| ensemble | 38/48 | 0.529381 | 38/48 | 0.529863 |
| recent | 38/48 | 0.532925 | 38/48 | 0.525680 |
| xg_elo | 40/48 | 0.532606 | 39/48 | 0.539623 |

## Walk-forward methodology

Initial xG development/validation seasons: 2015/16–2019/20; evaluation: 2020/21–2025/26.
For each evaluation fold select among the fixed candidate pool and Model A using only the last
three completed earlier R16 seasons. Primary objective: mean log loss + 0.1 × seasonal log-loss
standard deviation; accuracy breaks ties. A separately declared accuracy-first strategy is secondary.
Four or more earlier seasons are required. Earlier evaluation seasons become available only after
their ties resolve. Neither the 42/48 reference nor evaluation-selected perturbations are eligible.
All teams are forecast before the first R16 match day, stricter than forecasting separately before each tie.
Ratings, xG features and score-shape distributions are frozen at that cutoff; both legs use those ratings.
The existing away-goals/extra-time/penalty resolution and past-only conditional goal shapes are reused.

| Strategy | Season | Selected ID | Correct | Log loss |
|---|---|---|---:|---:|
| probability | 2020-2021 | f8c7e1557b6555f3 | 4/8 | 0.627062 |
| probability | 2021-2022 | d0709a0f929f90de | 5/8 | 0.615566 |
| probability | 2022-2023 | 6238cf3a721df6cb | 6/8 | 0.525814 |
| probability | 2023-2024 | d52b24dfada86179 | 7/8 | 0.427823 |
| probability | 2024-2025 | d52b24dfada86179 | 8/8 | 0.447415 |
| probability | 2025-2026 | d52b24dfada86179 | 8/8 | 0.311133 |
| accuracy | 2020-2021 | 0286e7ac58ce5cb7 | 3/8 | 0.643596 |
| accuracy | 2021-2022 | d0709a0f929f90de | 5/8 | 0.615566 |
| accuracy | 2022-2023 | a16dba4a80e59c8b | 7/8 | 0.517658 |
| accuracy | 2023-2024 | a16dba4a80e59c8b | 7/8 | 0.494474 |
| accuracy | 2024-2025 | f8c7e1557b6555f3 | 6/8 | 0.513298 |
| accuracy | 2025-2026 | d52b24dfada86179 | 8/8 | 0.311133 |

## Uncertainty

```json
{
  "probability": {
    "accuracy_wilson95": [
      0.6574082647864651,
      0.8826985220411018
    ],
    "paired_log_loss_delta": -0.05165161189440392,
    "paired_log_loss_seasonal95": [
      -0.10465985079433432,
      0.0013566270055264881
    ]
  },
  "accuracy": {
    "accuracy_wilson95": [
      0.6121535625207293,
      0.8507951119028996
    ],
    "paired_log_loss_delta": -0.028166379730316788,
    "paired_log_loss_seasonal95": [
      -0.08375663299844695,
      0.027423873537813375
    ]
  }
}
```
Wilson intervals treat ties as independent, which repeated clubs violate. Paired loss intervals
cluster by season, with only six clusters. Many candidate tests and previously examined seasons
add selection uncertainty; nominal intervals do not account for all researcher choices.

## Models and interpretation

- **Differential:** exponentially weighted domestic-season xG for minus xG against, shrunk by
  zero-differential pseudo-games. Add scale × the difference of the two club features to Model A Elo difference.
- **Recent:** the same feature using the last 3/5/8/10/15/20/40 xG matches within 365 days.
- **xG Elo:** use Sx = P(Poisson(xGh)>Poisson(xGa)) + 0.5P(draw); blend Sx with realized S.
  Apply existing chronological K × importance × goal-margin × (blended S − E) updates.
  K, xG share and offseason regression are experimental. UCL and other missing-xG matches
  use actual results; all clubs start at 1500 without current squad-value priors.
- **Attack/defence:** log expected xG = log(prior goal rate) + attack_home − defence_away + home_log/2
  (away sign reversed). Online quasi-Poisson residual updates train separate attack and defence
  strengths only after observing each match; offseason regression shrinks toward zero.
  Predicted Poisson H/D/A feed the existing two-leg conditional-score machinery.
- **Ensemble:** average xG-Elo and attack/defence advancement probabilities; blend that component
  with A. All families test probability blends of 10/25/50/75/100% xG weight.
- Fallback to A for a tie if either club has fewer than five prior xG matches or its latest xG is
  more than 90 days old. Missing xG is never treated as zero. Outside-five opponents have no xG.
- xG differential is domestic-league-relative; it does not by itself solve cross-league strength.

## Data provenance and limitations

Understat.com league pages and getLeagueData endpoints returned a maintenance HTML page.
Used the explicitly documented frozen Understat archive, not Opta/FBref or invented xG:
[archive repository](https://github.com/peteowen1/pannadata),
[metadata asset](https://github.com/peteowen1/pannadata/releases/download/understat-latest/understat_metadata.parquet).
Release asset ID 399247157, updated 2026-04-18. See provenance.json for retrieval date, hashes,
source inspection and an independent older Understat scrape cross-check.
21,120 existing fixtures received xG. Exact league/season, resolved home/away IDs, date and scores
must agree. No fuzzy mapping or ±day guessing: 152 rows quarantined, 189 duplicate source rows removed.
Full league-season counts and every rejected row are in coverage.json. No unknown top-five names.
No xG before 2014/15, no UCL xG, incomplete 2025/26 and historical gaps. No new matches were added.
Archived xG was retrieved retrospectively; provider model revisions and original publication delays
cannot be audited. Match-date cutoff protection does not prove point-in-time publication availability.
See cutoff-coverage.json for xG freshness/fallbacks in every prediction cohort.

## Rerun

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.xg_search --trials 2000 --seed 20261112 --output-dir experiments/xg
```
Use --resume to retain completed batches with matching data/config/source hashes. Source acquisition
and additive database migration are documented in README.md. Existing production tables and rating
predictions were checked unchanged after the import. No experimental model is deployed.
