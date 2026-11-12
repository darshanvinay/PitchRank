# Final interpretation — 10,000-model search

**Model A should remain in production.** The requested score was reached only through exploratory
selection, while neither declared walk-forward selection protocol exceeded A's 38/48 accuracy.
No model was deployed and the existing production code, API, UI, parameters and database are unchanged.

| Result | Correct / 48 | Accuracy | Brier | Log loss |
|---|---:|---:|---:|---:|
| Original A | 38 | 79.17% | 0.180565 | 0.544120 |
| Best main-search model (evaluation-selected) | 41 | 85.42% | 0.143582 | 0.451513 |
| Best including diagnostics (further evaluation-selected) | 42 | 87.50% | 0.149449 | 0.460356 |
| Primary walk-forward probability/stability | 33 | 68.75% | 0.176652 | 0.523379 |
| Secondary walk-forward accuracy strategy | 37 | 77.08% | 0.170127 | 0.515842 |

**Counts:** 10,000 distinct main search configurations (8,000 broad/anchor trials, 2,000 local
refinements), plus 515 new perturbation/ablation configurations: **10,515 unique configurations**
in results.csv. The preliminary 8/32-configuration smoke checks and 256-configuration benchmark
were engineering/runtime checks, not additional independent validation samples or extra counted
main trials. Initial full-search/diagnostic/report runtime was **143.37s**.
Completed-checkpoint resume verification took 71.00s and reproduced identical
checkpoint/CSV bytes, selected configurations and scores without executing another trial.

The primary walk-forward method got 33/48; the highest accuracy among the two predeclared protocols
was 37/48. Reporting the latter does not silently replace the primary strategy or create an independent
new test. Both strategies improved probability scores numerically, but their paired seasonal intervals
include no improvement. Neither meets the 40/48 accuracy target through past-only selection.

There were **91/10,000 main-search configurations at 40/48 or higher**. Selecting their maximum after
seeing the 48 results is exactly the hindsight-selection effect the protocol must disclose. All of
these historical seasons were already discussed in earlier PitchRank studies; a fresh prospectively
specified evaluation remains necessary even for a correctly implemented past-only selection rule.

## Highest exploratory candidate, including the required robustness study

Candidate **66fb758a013eebb5** scored **42/48 (87.50%)**, with Brier **0.149449**
and log loss **0.460356**. It was found by a joint -10% perturbation of a
main-search parent selected on evaluation outcomes. It is therefore *more* adaptively selected,
not a separate out-of-sample discovery. Its K=9 is a permitted robustness perturbation of grid K=10,
not an undisclosed change to the declared broad K grid.

Its 42-pick accuracy is higher than the main search's 41-pick winner, but the main winner's log loss
(0.451513) is better. Higher accuracy and better probability quality are
different objectives. The full configuration is:

```json
{
  "k_domestic": 9.0,
  "k_ucl": 9.0,
  "home": 22.5,
  "home_mode": "league",
  "neutral_factor": 0.0,
  "regression": 0.09000000000000001,
  "regression_target": "initial",
  "regression_asymmetry": 0.0,
  "regression_league": 0.0,
  "margin": "linear",
  "margin_cap": 4.0,
  "margin_adjust": 0.0,
  "k_gap": 0.0,
  "k_stage": 0.0,
  "ucl_group": 1.25,
  "ucl_knockout": 1.5,
  "ucl_finals": 1.75,
  "opponent_league": 0.0,
  "form_window": 10,
  "form_weight": 0.0,
  "form_kind": "residual",
  "form_ew": false,
  "form_venue": false,
  "european_weight": 0.0,
  "offsets": "none",
  "offset_sd": 50.0,
  "head": "expected",
  "draw_strength": 0.7,
  "logistic_rate": 0.05,
  "logistic_ridge": 0.1,
  "logistic_features": 7,
  "calibration": "none"
}
```

The `expected` head preserves Elo's expected score while assigning a draw probability estimated
from prior completed games: H=E-d/2, D=d, A=1-E-d/2, with d bounded so all outcomes remain positive.
It does not mistake expected score for outright win probability. `home_mode=league` means a
regularized past-competition estimate (each domestic league, or UCL), with `home` as its prior.
It is not a manual bonus for any country or club.

## Top five across all search and diagnostic configurations

All five have 42 correct picks. They are ordered by accuracy then log loss. Several are nearby
versions of the same parent, not five independent validations. Full settings and changed forecasts
are preserved in top_models.json and analysis.json.

| ID | K domestic/UCL | Home prior/policy | Regression | Margin | Head | Brier | Log loss |
|---|---|---|---:|---|---|---:|---:|
| 66fb758a013eebb5 | 9/9 | 22.5, league | 9.0% | linear, cap 4 | expected | 0.149449 | 0.460356 |
| 3ab3bdf77f6d8dac | 10/10 | 65, fixed | 25.0% | linear, uncapped | regularized | 0.158721 | 0.491363 |
| 661f0f73cfe8a19c | 9/9 | 45, league | 9.0% | linear, uncapped | logistic | 0.159528 | 0.494599 |
| 1124b18ca75bd770 | 10/11 | 50, league | 10.0% | linear, uncapped | logistic | 0.159684 | 0.494789 |
| f8631e6e56d1e9c4 | 9.5/9.5 | 47.5, league | 9.5% | linear, uncapped | logistic | 0.159742 | 0.494990 |

The second candidate also uses UCL phase multipliers 2/3/1.5 and an online regularized residual/
European-feature head. The last three use a 10% venue-specific last-three-game goal feature.
The first candidate has no recent-form feature, league offset, or probability calibrator.

## Exact changed ties for the highest exploratory candidate

Probabilities refer to the first-named, first-leg home club advancing. A positive gain means the
candidate corrects A; a regression means it changes a previously correct A prediction into an error.

| Season | Tie | Actual advancing club | A probability | Candidate probability | Result |
|---|---|---|---:|---:|---|
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | 56.005% | 48.191% | corrected |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | 48.380% | 51.101% | corrected |
| 2021-2022 | Paris Saint-Germain – Real Madrid | Real Madrid | 49.003% | 55.078% | new error |
| 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | 53.119% | 47.343% | corrected |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 53.787% | corrected |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | 45.366% | 50.101% | corrected |

That is five corrections and one new error, a net gain of four. The Dortmund–LOSC forecast is only
**50.1005%**, so one of the extra correct picks rests just 0.1005 percentage points above the decision
threshold. This is a meaningful sensitivity concern despite arithmetic reproducibility.

## Which predictions change under walk-forward selection?

These are separate from the evaluation-selected candidate above. Every chosen configuration uses
only earlier resolved validation seasons. No diagnostic configuration enters either candidate pool.

| Strategy | Season | Tie | Actual advancing club | A probability | Selected probability | Result |
|---|---|---|---|---:|---:|---|
| probability | 2020-2021 | FC Barcelona – Paris Saint-Germain | Paris Saint-Germain | 49.577% | 58.217% | new error |
| probability | 2020-2021 | RB Leipzig – Liverpool | Liverpool | 49.768% | 51.576% | new error |
| probability | 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | 53.119% | 34.116% | corrected |
| probability | 2022-2023 | Liverpool – Real Madrid | Real Madrid | 44.815% | 58.810% | new error |
| probability | 2022-2023 | Inter – Porto | Inter | 62.618% | 49.238% | new error |
| probability | 2023-2024 | Napoli – FC Barcelona | FC Barcelona | 42.854% | 87.255% | new error |
| probability | 2024-2025 | Paris Saint-Germain – Liverpool | Paris Saint-Germain | 50.254% | 40.658% | new error |
| probability | 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 52.024% | corrected |
| probability | 2025-2026 | Real Madrid – Man City | Real Madrid | 51.649% | 39.322% | new error |
| accuracy | 2020-2021 | Atlético de Madrid – Chelsea | Chelsea | 59.879% | 47.789% | corrected |
| accuracy | 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | 53.119% | 34.116% | corrected |
| accuracy | 2022-2023 | Liverpool – Real Madrid | Real Madrid | 44.815% | 58.810% | new error |
| accuracy | 2022-2023 | Inter – Porto | Inter | 62.618% | 49.238% | new error |
| accuracy | 2023-2024 | Napoli – FC Barcelona | FC Barcelona | 42.854% | 87.255% | new error |
| accuracy | 2024-2025 | Paris Saint-Germain – Liverpool | Paris Saint-Germain | 50.254% | 38.719% | new error |
| accuracy | 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 54.192% | corrected |

## Robustness and parameter findings

The 20 evaluation-selected main-search models completed all requested core numeric perturbations
and grouped ablations. Nearby variants range from **38 to 42 correct**. For two of the first five
parents all 24 recorded perturbation coordinates retained at least 40 picks. Thus there are local
regions of strong *exploratory* performance; the score is not exclusively a single numerical spike.
That local stability still does not generalize into improved walk-forward accuracy.

Relative perturbations cover domestic/UCL K, home prior, regression and draw strength, jointly and
one at a time at ±5%/±10%. Zero or inactive values can produce unchanged coordinates; unique trial
counts do not double-count those cases. Other policy groups are assessed through ablations. The
new diagnostic 42-pick descendants were not recursively treated as another top 20: doing that would
be further evaluation-driven optimization, not validation.

Ablations give a stronger warning than the exploratory maximum:

- Resetting selected parents' K policies to baseline **improves earlier validation** median log loss
  by about 0.00447 but worsens evaluation loss by 0.00294.
- Resetting regression to baseline improves validation by about 0.00479, while worsening evaluation
  by 0.02608. This reversal does not support a reliably better regression choice.
- Resetting margins or prediction heads likewise slightly improves validation but worsens the
  selected evaluation sample. These are sample-specific gains, not established general rules.
- Removing recent features helps both median validation and evaluation loss in the small active-parent
  subset. Offsets show the same direction for only one active parent. There is no supported general
  recent-form or league-offset gain from this selected subset.
- European-weight and goal-feature ablation deltas are small or reverse between periods. Their
  minimal/unstable impact does not justify treating them as reliable additional signal.
- One calibrated parent benefits substantially on evaluation while calibration hurts earlier validation;
  that is a warning about sample selection, not evidence to deploy its calibrator.

These paired diagnostics are themselves conditional on evaluation-selected parents and are not
causal estimates over all football models. The report below retains every parent and measured delta.
The highest candidate's extra wins are spread across three seasons (net gains 1,0,1,0,2,0), with half
the net improvement coming from 2024/25. That is broader than one season, but remains six correlated
seasonal clusters after thousands of attempted configurations.

## Engineering verification

- **193 backend tests and 5 existing frontend navigation tests passed.** Ruff passed across the backend;
  the new source files pass formatting checks. One existing AnyIO deprecation warning remains.
- The original Model A backtester was run freshly and reproduced 38/48, Brier 0.18056490331282316,
  and log loss 0.5441203012681248. No production source file was modified.
- The accelerated probability contraction matched the original two-leg enumerator within floating-point
  tolerance. An **independent scalar replay of the highest candidate**, calling the original
  `update_ratings` with the experimental multiplier adapter and direct score enumeration, checked
  **120 historical ties** with maximum difference **4.218847493575595e-15**.
- The optimizer cannot exploit floating-point noise at 50%: probabilities within 1e-12 of a mathematical
  tie are treated as 0.5. This does not change any saved baseline evaluation probability.
- Resume produced byte-identical trial checkpoints and results.csv with no added trial, and the
  SQLite database SHA-256 is unchanged. Proofs are in verification.json and scalar-verification.json.
- Raw local checkpoints are retained for resumption but ignored by Git because they exceed 50 MB.
  The required CSV and JSON reports remain available. To regenerate raw forecasts on another machine,
  rebuild the same historical database and rerun the documented command/seed.

No experiment was deployed, committed or pushed. Treat 42/48 as a reproducible discovery hypothesis.
The strongest recommendation is **retain Model A**, preserve the 42-pick region for a preregistered
future comparison, and do not tune again on these 48 ties to claim an out-of-sample accuracy gain.

---

# Automatically generated full search tables

# PitchRank large-scale Elo search

## Recommendation and status

Production Model A was preserved. This is a retrospective study on seasons already examined in
previous PitchRank experiments. Exploratory selection on the original evaluation ties is explicitly
in-sample selection. Walk-forward selection uses only resolved earlier seasons, but does not restore
a prospectively blind benchmark. A score of 40+/48 alone is insufficient for promotion.

Search status: **complete**.
Evaluated **10000 distinct search configurations**, plus saved robustness configurations.
Method: hybrid; seed 20261111. Optuna available: False.
The implementation adds no dependency and makes no database, API, UI or production-parameter change.

## Architecture and baseline audit

Historical forecasts replay domestic + UCL games chronologically from July 2010; club IDs are shared
across competitions. Initial ratings are 1500 with no current squad values. Default K=20, H=65,
scale=400, offseason regression=25%, log margin, UCL importance 1.25/1.5/1.75. A's update is zero-sum.
Unknown kickoff times make the whole day a simultaneous batch. Every R16 forecast excludes the entire
cutoff day and freezes before the earliest first leg. The two-leg scorer retains historical away goals,
extra time and penalties. Current squad priors used by the live leaderboard are not used in this search.
The older membership-precomputing research replay is not used.

Fresh canonical baseline: **38/48 (79.17%)**,
Brier 0.180565, log loss 0.544120.
The optimized contraction was checked against the original enumerator; Model A itself uses the original
backtester probabilities in artifacts, rather than replacing production mathematics.

Data audit: {
  "domestic_matches": 28432,
  "ucl_matches": 1972,
  "clubs": 247,
  "source_start": "2010-08-07",
  "latest_replay_match": "2026-03-10",
  "chronology": "Date batches if any kickoff unknown; cutoff excludes its entire day",
  "valuation_prior": "None; neutral 1500",
  "limitations": [
    "UCL main draw starts 2011/12; outside-five domestic games unavailable",
    "Historical results/venue metadata are retrospective, not publication-time snapshots",
    "Earlier test seasons have already been examined in PitchRank experiments"
  ]
}

Training seasons: 2013-2014, 2014-2015, 2015-2016, 2016-2017, 2017-2018, 2018-2019, 2019-2020. Evaluation seasons: 2020-2021, 2021-2022, 2022-2023, 2023-2024, 2024-2025, 2025-2026.
The last three available earlier seasons form each walk-forward validation fold; a minimum of four
earlier seasons is required. Each fold validates that the earlier tie outcomes resolved before cutoff.
Candidate local refinement uses only the early part of the initial training period, never the evaluation
sample. Probability calibration receives only resolved prior R16 probabilities/outcomes. Platt needs
32 ties and both classes; isotonic needs 64, with 50% shrinkage toward identity. Sparse folds use identity.
Online match-head/offset/HA learning publishes changes only after a complete kickoff batch. Features
are fixed-scale pre-match quantities; no full-data normalization or future membership is used.

## Models actually searched

- Independent domestic/UCL K, K gap/stage modifiers and UCL phase importance.
- Fixed, past-league and recent empirical home advantage; recorded neutral-venue handling.
- Initial/global/observed-domestic regression targets, strong/weak and league adjustments.
- Binary, linear, logarithmic and square-root margins; caps and rating-gap adjustment.
- Last 3/5/8/10/15/20 match residual, goal or opponent-performance features; exponential and venue
  variants; 0–50% feature blends. Features come from pre-match baseline innovations, not trophies.
- European residual features; fixed warmup-fitted or online/shrunk league offsets. Fixed offsets freeze
  before the first initial training season; no hand-entered country bonuses exist.
- Davidson, score-preserving Elo H/D/A, conditional logistic H/D/A and regularized symmetric match
  logistic heads. The learned head trains online on prior games with physical feature scaling.
- Optional past-only Platt/isotonic advancement calibration. These modify predictions, not rating updates.

These are proposed experimental rules, not proven optimal formulas. Home-strength estimates from
fractional past home results may retain schedule bias. The initial/global/league means use only
already observed clubs. League offsets condition on existing Elo and may re-use correlated information;
they do not add a second UCL result update. A different bias/variance trade-off is not automatically better.

## Baseline by season

| Season | Correct | Brier | Log loss |
|---|---:|---:|---:|
| 2020-2021 | 5/8 | 0.245292 | 0.679946 |
| 2021-2022 | 5/8 | 0.217178 | 0.614570 |
| 2022-2023 | 7/8 | 0.171201 | 0.529590 |
| 2023-2024 | 7/8 | 0.141205 | 0.460051 |
| 2024-2025 | 6/8 | 0.181529 | 0.546941 |
| 2025-2026 | 8/8 | 0.126985 | 0.433624 |

## Best exploratory model — selected on the evaluation sample

**41/48 (85.42%)**, Brier 0.143582, log loss 0.451513.

```json
{
  "k_domestic": 15.0,
  "k_ucl": 15.0,
  "home": 100.0,
  "home_mode": "fixed",
  "neutral_factor": 0.0,
  "regression": 0.0,
  "regression_target": "initial",
  "regression_asymmetry": 0.0,
  "regression_league": 0.0,
  "margin": "log",
  "margin_cap": 99.0,
  "margin_adjust": 0.5,
  "k_gap": 0.5,
  "k_stage": 0.5,
  "ucl_group": 1.25,
  "ucl_knockout": 1.5,
  "ucl_finals": 1.75,
  "opponent_league": 0.0,
  "form_window": 10,
  "form_weight": 0.0,
  "form_kind": "residual",
  "form_ew": false,
  "form_venue": false,
  "european_weight": 0.2,
  "offsets": "none",
  "offset_sd": 50.0,
  "head": "davidson",
  "draw_strength": 0.7,
  "logistic_rate": 0.05,
  "logistic_ridge": 0.1,
  "logistic_features": 7,
  "calibration": "isotonic"
}
```

This is the maximum observed among many configurations, not out-of-sample evidence.

### Top five exploratory configurations

| ID | Correct | Brier | Log loss | Key settings |
|---|---:|---:|---:|---|
| b79442f0fcb0422e | 41/48 | 0.143582 | 0.451513 | K=15.0/15.0, H=100.0, regression=0.0, margin=log, head=davidson, calibration=isotonic |
| 385e44018b4c4dfa | 41/48 | 0.150234 | 0.461918 | K=10.0/10.0, H=25.0, regression=0.1, margin=linear, head=expected, calibration=none |
| 89c4b19c3da792d1 | 41/48 | 0.148977 | 0.463714 | K=15.0/15.0, H=125.0, regression=0.0, margin=log, head=expected, calibration=none |
| df0df9ca49331af1 | 41/48 | 0.158619 | 0.491056 | K=10.0/10.0, H=65.0, regression=0.25, margin=linear, head=regularized, calibration=none |
| 87830a96e0c42bb6 | 41/48 | 0.159098 | 0.494577 | K=15.0/15.0, H=125.0, regression=0.0, margin=log, head=davidson, calibration=none |

Complete configurations are in top_models.json; every trial and per-season score is in results.csv.

### Changed exploratory picks

| Season | Tie | Actual | A P(first) | Candidate P(first) | Change | Margin from 50% |
|---|---|---|---:|---:|---|---:|
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | 56.005% | 48.984% | corrected | 1.016% |
| 2020-2021 | FC Barcelona – Paris Saint-Germain | Paris Saint-Germain | 49.577% | 56.164% | new error | 6.164% |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | 48.380% | 50.218% | corrected | 0.218% |
| 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | 53.119% | 37.433% | corrected | 12.567% |
| 2024-2025 | Paris Saint-Germain – Liverpool | Paris Saint-Germain | 50.254% | 33.332% | new error | 16.668% |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.503% | 58.361% | corrected | 8.361% |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | 45.366% | 52.634% | corrected | 2.634% |

## Walk-forward — past-selected configurations

Two strategies were declared before the search. Primary ranks past validation log loss plus 0.1 times
its season standard deviation, then accuracy and simplicity; secondary prioritizes past-validation
accuracy before the same probability/stability ranking. The highest observed secondary strategy is
not silently substituted for the primary. Earlier evaluation seasons may train later folds only after
their outcomes are resolved. No fold selects on its own or a future outcome.

### probability: 33/48 (68.75%)

Brier 0.176652; log loss 0.523379.

| Evaluation season | Past validation seasons | Selected ID | Correct | Log loss |
|---|---|---|---:|---:|
| 2020-2021 | 2017-2018, 2018-2019, 2019-2020 | 22598ee8abbb31cf | 3/8 | 0.722317 |
| 2021-2022 | 2018-2019, 2019-2020, 2020-2021 | 81fd97604f642dc8 | 5/8 | 0.635518 |
| 2022-2023 | 2019-2020, 2020-2021, 2021-2022 | d7df423af6753030 | 6/8 | 0.469427 |
| 2023-2024 | 2020-2021, 2021-2022, 2022-2023 | 9c071fc6db74d1f1 | 6/8 | 0.562818 |
| 2024-2025 | 2021-2022, 2022-2023, 2023-2024 | 8e3439e839aa5fda | 6/8 | 0.441045 |
| 2025-2026 | 2022-2023, 2023-2024, 2024-2025 | 9e25fe8f6246be53 | 7/8 | 0.309152 |
### accuracy: 37/48 (77.08%)

Brier 0.170127; log loss 0.515842.

| Evaluation season | Past validation seasons | Selected ID | Correct | Log loss |
|---|---|---|---:|---:|
| 2020-2021 | 2017-2018, 2018-2019, 2019-2020 | 01109e6ea752a6b0 | 6/8 | 0.588979 |
| 2021-2022 | 2018-2019, 2019-2020, 2020-2021 | 81fd97604f642dc8 | 5/8 | 0.635518 |
| 2022-2023 | 2019-2020, 2020-2021, 2021-2022 | d7df423af6753030 | 6/8 | 0.469427 |
| 2023-2024 | 2020-2021, 2021-2022, 2022-2023 | 9c071fc6db74d1f1 | 6/8 | 0.562818 |
| 2024-2025 | 2021-2022, 2022-2023, 2023-2024 | 442a660d119fce47 | 6/8 | 0.437638 |
| 2025-2026 | 2022-2023, 2023-2024, 2024-2025 | df0df9ca49331af1 | 8/8 | 0.400674 |

Full past-selection configurations, probabilities and fold metrics are saved in walk_forward.json.

## Robustness and ablations

The evaluation-selected top 20 receive joint and one-at-a-time ±5%/±10% perturbations of K, home,
regression and draw strength, plus grouped parameter ablations. These diagnostics are post-selection
exploration, not additional independent validation or an input to walk-forward selection.

| Model | Diagnostics complete | Perturbed correct range | Median perturbed correct |
|---|---|---|---|
| b79442f0fcb0422e | True | 38–41 | 41.0 |
| 385e44018b4c4dfa | True | 40–42 | 41.0 |
| 89c4b19c3da792d1 | True | 39–41 | 41.0 |
| df0df9ca49331af1 | True | 39–41 | 40.5 |
| 87830a96e0c42bb6 | True | 40–41 | 41.0 |
| 4fff0aa9f1d98fa4 | True | 39–42 | 41.0 |
| 643e1e2b8ead8e8c | True | 41–41 | 41.0 |
| c4f201e904719a54 | True | 41–41 | 41.0 |
| ff5985b0a1acc540 | True | 41–41 | 41.0 |
| 6872cbb844e470dc | True | 40–41 | 41.0 |
| ba05ccce948629f4 | True | 40–41 | 41.0 |
| 8469ca87f7872796 | True | 38–41 | 41.0 |
| 7e99d5de2a1efc4d | True | 40–41 | 41.0 |
| 845cbeef5a91ae01 | True | 39–42 | 41.0 |
| 62e57295b5289d19 | True | 39–41 | 40.5 |
| 4a87aabeda6e9b90 | True | 40–41 | 41.0 |
| c1fc52d856100fcd | True | 40–41 | 41.0 |
| f9b16be6e6bdfc84 | True | 40–42 | 41.0 |
| c21042973c19df33 | True | 40–41 | 41.0 |
| fad801d29f2dd22a | True | 39–41 | 41.0 |

Detailed perturbation/ablation metrics are in robustness.json. Leave-one-season-out and per-season
changes should be interpreted as diagnostics, not a new search objective. Small-margin flips, isolated
season gains and wide perturbation ranges are warning signs of selection noise.

The primary walk-forward result changes accuracy by -10.42 percentage points, Brier by -0.003913, and log loss by -0.020741.

Production recommendation: **retain A pending a fresh prospectively specified evaluation**.
A higher exploratory score is not a promotion criterion. Even a past-only algorithm evaluated
after many research iterations on these same six seasons has limited independent evidence. There
are only six seasonal clusters and 48 correlated ties; selection over thousands of models inflates
the exploratory maximum. Missing outside-five domestic evidence and retrospective corrections/venue
metadata remain limitations. Draw outcomes themselves are not averaged here: this study scores R16
known ties, not unconditional later tournament draws.

## Rerun / resume

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.model_search --trials 10000 --seed 20261111 --search-method hybrid --batch-size 512 --max-seconds 600.0 --output-dir /Users/darshan/Documents/PitchRank/PitchRank/experiments --training-seasons 2013-2014 2014-2015 2015-2016 2016-2017 2017-2018 2018-2019 2019-2020 --evaluation-seasons 2020-2021 2021-2022 2022-2023 2023-2024 2024-2025 2025-2026 --resume
```

Configuration/data/source-code manifests are checked before resume. A completed trial is never
replayed unnecessarily; a partially appended final record is repaired. Runtime caps stop between
batches, saving all completed results. Increase --max-seconds when resuming if necessary. Custom
--training-seasons and --evaluation-seasons accept space-separated YYYY-YYYY season strings.

## Additional statistical and robustness analysis

The search pool contains 10000 configurations; diagnostics add 515 distinct configurations. Diagnostics are excluded from every walk-forward selection, since their proposal uses evaluation-selected parents. Execution time per trial is amortized batch wall time; cache and reporting time are in summary.json.

Highest exploratory score including diagnostics: **42/48**, configuration 66fb758a013eebb5 (robustness). This is further hindsight-selected evidence. Full settings and changed ties are in top_models.json/analysis.json.

| All-trial top five ID | Phase | Correct | Brier | Log loss |
|---|---|---:|---:|---:|
| 66fb758a013eebb5 | robustness | 42/48 | 0.149449 | 0.460356 |
| 3ab3bdf77f6d8dac | robustness | 42/48 | 0.158721 | 0.491363 |
| 661f0f73cfe8a19c | robustness | 42/48 | 0.159528 | 0.494599 |
| 1124b18ca75bd770 | robustness | 42/48 | 0.159684 | 0.494789 |
| f8631e6e56d1e9c4 | robustness | 42/48 | 0.159742 | 0.494990 |

### Primary/secondary uncertainty

| Strategy | Accuracy Wilson 95% | Paired log-loss delta [approx 95%] | Corrections/new errors | Paired accuracy exact p |
|---|---|---|---|---:|
| probability | 54.7%–80.1% | -0.020741 [-0.115253, +0.073771] | 2/7 | 0.1797 |
| accuracy | 63.5%–86.7% | -0.028278 [-0.111096, +0.054540] | 3/4 | 1.0000 |

Wilson and exact-discordance intervals/tests assume independent ties, which repeated clubs violate. Paired loss intervals use seasonal clusters and a t critical value; six clusters give only descriptive uncertainty. Multiple searches and two declared strategies add selection uncertainty. These are not claims of statistically proven superiority.

### Best-model seasonal stability

| Season | A correct | Candidate correct | Difference |
|---|---:|---:|---:|
| 2020-2021 | 5/8 | 6/8 | +1 |
| 2021-2022 | 5/8 | 5/8 | +0 |
| 2022-2023 | 7/8 | 8/8 | +1 |
| 2023-2024 | 7/8 | 7/8 | +0 |
| 2024-2025 | 6/8 | 8/8 | +2 |
| 2025-2026 | 8/8 | 8/8 | +0 |

Net gains by season: [1, 0, 1, 0, 2, 0]. Leaving out the single strongest gain season removes 2 of the net 4 extra correct picks. This check is descriptive and does not constitute a new independent sample.

### Paired parameter ablations

Positive loss delta means removing that parameter group worsens predictions; negative means the ablation helps. Parents were selected using evaluation outcomes, so this diagnoses those parents rather than establishing a general causal parameter effect.

| Removed group | Active parents | Median validation log-loss delta | Median evaluation log-loss delta |
|---|---:|---:|---:|
| K | 20 | -0.004471 | +0.002943 |
| home | 17 | -0.000168 | +0.000325 |
| regression | 18 | -0.004787 | +0.026084 |
| margin | 17 | -0.000860 | +0.006394 |
| Europe | 6 | -0.000784 | +0.000194 |
| calibration | 1 | -0.024885 | +0.049587 |
| head | 11 | -0.000400 | +0.002612 |
| recent | 3 | -0.000121 | -0.000171 |
| goal_feature | 3 | -0.000203 | +0.000219 |
| offsets | 1 | -0.001696 | -0.001324 |
