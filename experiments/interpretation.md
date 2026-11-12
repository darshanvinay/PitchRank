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
