# Interpretation and verification

The 2,000-model xG search found **43/48 (89.58%) exploratory** and **41/48 (85.42%) primary
walk-forward** accuracy. This is promising evidence in the previously examined historical sample,
not proof of 40+/48 accuracy on genuinely unseen matches. Keep Model A in production and freeze
this research protocol for a prospective shadow evaluation before considering deployment.

The 43/48 model has worse Brier/log loss than the old evaluation-selected 42/48 model:
.171481/.525434 versus .149449/.460356. Accuracy alone therefore gives an incomplete picture.
The best exploratory xG model is a 50/50 xG-Elo/attack-defence ensemble, without an additional A
probability contribution. Its K=10, xG outcome share=25%, no offseason regression, attack/defence
learning rate=.1, prior goals=1.5 and log-home effect=.15 were selected on the 48 evaluation ties.
Do not treat this fixed model's 43/48 as walk-forward performance.

The primary walk-forward protocol scored 6, 5, 7, 7, 8, 8 correct by season (2020/21–2025/26).
It used ensemble/attack-defence configurations initially, then xG-differential/recent-form models.
It improved five baseline errors and introduced two, for a net gain of three. The exact paired
sign test on those seven disagreements is p=0.453125; the seasonal paired log-loss difference is
−.068889, with approximate 95% interval [−.150840, +.013062]. With just six season clusters, there
is not strong evidence of a reliable generalization gain despite better measured proper scores.

The separately declared accuracy-first selector scored 38/48. This difference reinforces that
selecting the search objective is part of the experiment and cannot be chosen after seeing results.

## Primary walk-forward changed predictions

| Season | Tie | Actual advancing team | A P(team A) | Walk-forward P(team A) | Effect |
|---|---|---|---:|---:|---|
| 2020-2021 | Atalanta – Real Madrid | Real Madrid | 48.183% | 51.336% | new_error |
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | 56.005% | 47.838% | corrected |
| 2020-2021 | Atlético de Madrid – Chelsea | Chelsea | 59.879% | 46.146% | corrected |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | 48.380% | 58.465% | corrected |
| 2021-2022 | Paris Saint-Germain – Real Madrid | Real Madrid | 49.003% | 61.520% | new_error |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 64.293% | corrected |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | 45.366% | 74.504% | corrected |

The exploratory 43/48 model differs from the old 42/48 reference on only Atlético–Chelsea
(2020/21), correcting the prediction to Chelsea. Its Atlético advancement probability is 49.68%,
only 0.32 percentage points below the decision boundary. That historical extra correct pick is fragile.

## Does xG add information beyond goals?

A diagnostic kept the primary walk-forward-selected configurations, fixture availability and code
fixed, but used observed goals as the training signal instead of observed xG. This matched control
scored **38/48**, Brier **.164290**, log loss **.509360**, versus xG's **41/48**, **.150995**, **.475231**.
This supports investigating the xG signal. It is an ablation of xG-selected settings, not a separately
tuned goals-only competitor or an additional out-of-sample experiment. No control values were written
to the xG database, and no goals were reported as genuine xG.

All five family-specific chronological probability selectors scored 39–41/48, though the best family
cannot be chosen using these same evaluation outcomes and then called untouched performance.
Raw domestic xG differences remain sensitive to domestic opponent strength. The attack/defence model
adjusts for opponents within its observed pool but has no UCL xG to directly link domestic pools;
Model A and xG-Elo's UCL result updates remain important cross-league anchors.

## Data and verification

Imported xG counts: Premier League **4,444**, La Liga **4,413**, Serie A **4,488**,
Bundesliga **3,625**, Ligue 1 **4,150**. Total **21,120**. No pre-2014/15 or UCL xG is available.
The archive extends into April 2026; every forecast excludes the cutoff day and all later observations.
15 of the 48 evaluation ties fall back to Model A because at least one club lacks sufficient fresh xG.
The original source was unavailable, so the frozen Understat archive is explicitly identified below.
There are 469 existing fixtures without matched xG across the archive's 2014/15–2025/26 seasons;
this includes archive gaps, date/score disagreements, and games after the archive ends. Another 152
source rows are quarantined (150 exact-date mismatches, two score mismatches). There are no unmatched
club names among the five supported leagues. Excluded RFPL rows are not used.

Production preservation: all ten existing application tables have identical row hashes before/after
migration, import, research and canonical backtesting. Only the additive xG table and Alembic revision
were changed. No API/UI/production engine behavior changed. A fresh original backtester still yields
38/48; the accelerated A probabilities agree within 3.4e-15. Independent scalar replay of the best xG
ensemble agrees across 120 historical ties within 1.2e-15. A completed resume repeated no model trials
and preserved CSV/checkpoint bytes exactly.

**204 backend tests, five existing frontend navigation tests, lint and formatting passed.** Tests cover
idempotence/corrections, ambiguous IDs, malformed/mismatched rows, source score/date validation,
future-xG isolation, zero-xG-share baseline equivalence, missing-xG fallback, reproducibility and
independence of model batch ordering. Existing fold-selection leakage tests remain passing.

See `verification.json`, `goals-control.json`, `provenance.json`, `coverage.json` and `cutoff-coverage.json`.
A later CLI resume regenerates the automated report; this interpretation remains independently saved.

---

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
| Best exploratory xG | 43/48 | 89.58% | 0.171481 | 0.525434 |
| Walk-forward probability | 41/48 | 85.42% | 0.150995 | 0.475231 |
| Walk-forward accuracy | 38/48 | 79.17% | 0.178184 | 0.539452 |

Tested **2000 unique xG configurations**, seed 20261112.
Search is fixed seeded random sampling, not adapted using evaluation labels.

## Best exploratory xG model

```json
{
  "family": "ensemble",
  "window": 10,
  "half_life": 60,
  "shrink": 5,
  "feature_scale": 100,
  "k": 10.0,
  "xg_share": 0.25,
  "regression": 0.0,
  "learning_rate": 0.1,
  "prior_goals": 1.5,
  "home_log": 0.15,
  "blend": 1.0
}
```

This configuration was selected using the original 48 ties. Its historical score is exploratory.

| Season | Tie | Actual advancing team | A P(team A) | xG P(team A) | Change |
|---|---|---|---:|---:|---|
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | 56.005% | 48.824% | corrected |
| 2020-2021 | Atlético de Madrid – Chelsea | Chelsea | 59.879% | 49.682% | corrected |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | 48.380% | 56.802% | corrected |
| 2021-2022 | Paris Saint-Germain – Real Madrid | Real Madrid | 49.003% | 56.528% | new_error |
| 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | 53.119% | 49.244% | corrected |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 62.452% | corrected |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | 45.366% | 53.154% | corrected |

## Family comparisons

| Family | Exploratory correct | Log loss | Walk-forward correct | Walk-forward log loss |
|---|---:|---:|---:|---:|
| attack_defence | 42/48 | 0.538207 | 40/48 | 0.512094 |
| differential | 40/48 | 0.443931 | 39/48 | 0.457518 |
| ensemble | 43/48 | 0.525434 | 41/48 | 0.524929 |
| recent | 40/48 | 0.449782 | 39/48 | 0.466597 |
| xg_elo | 42/48 | 0.540006 | 40/48 | 0.528407 |

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
| probability | 2020-2021 | d1639f74eddfe8d6 | 6/8 | 0.602748 |
| probability | 2021-2022 | 36822ad2f95521cd | 5/8 | 0.645037 |
| probability | 2022-2023 | 338c02feedd1fd99 | 7/8 | 0.510776 |
| probability | 2023-2024 | 1a8f35467070e9ee | 7/8 | 0.428074 |
| probability | 2024-2025 | e86e4aa62ede35ca | 8/8 | 0.368763 |
| probability | 2025-2026 | e86e4aa62ede35ca | 8/8 | 0.295988 |
| accuracy | 2020-2021 | fce52ff359e7183f | 5/8 | 0.638236 |
| accuracy | 2021-2022 | 347619f1d73803c8 | 5/8 | 0.619323 |
| accuracy | 2022-2023 | 46e568d5c933c90b | 7/8 | 0.514782 |
| accuracy | 2023-2024 | 4e8e9969e40e42c4 | 7/8 | 0.496213 |
| accuracy | 2024-2025 | 9263f61856f3266e | 6/8 | 0.534545 |
| accuracy | 2025-2026 | 4e8e9969e40e42c4 | 8/8 | 0.433613 |

## Uncertainty

```json
{
  "probability": {
    "accuracy_wilson95": [
      0.7283255295714138,
      0.9275184258620602
    ],
    "paired_log_loss_delta": -0.06888939849462099,
    "paired_log_loss_seasonal95": [
      -0.15084033794643215,
      0.01306154095719017
    ]
  },
  "accuracy": {
    "accuracy_wilson95": [
      0.6574082647864651,
      0.8826985220411018
    ],
    "paired_log_loss_delta": -0.0046683741794567475,
    "paired_log_loss_seasonal95": [
      -0.03168271867871543,
      0.022345970319801938
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
