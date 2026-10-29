# Does extra Champions League history improve PitchRank?

## Recommendation

Keep **Model A** for the future bracket predictor. Model B slightly improved probability scores,
but reduced advancement accuracy and performed worse on the earlier validation set. Model C's
selected coefficient was zero: its best validated version makes exactly the baseline forecasts.
These results do not establish that an additional European-history adjustment improves predictions.
Production Elo, predictions, database contents, and frontend were not changed.

## Inspection: what the baseline already knows

Domestic and UCL matches enter the same chronological replay, using consistent club IDs:

`E_home = 1 / (1 + 10 ** ((R_away - R_home - H) / 400))`

`delta = 20 * importance * max(1, ln(1 + abs(goal_difference))) * (S_home - E_home)`

Home advantage H is 65 Elo points, or zero at recorded neutral venues. S is 1/0.5/0 for
win/draw/loss. The home club gains delta; its opponent loses delta. Domestic importance is 1;
UCL group/league phase 1.25, knockout 1.50, semifinal/final 1.75. Opponent strength, unexpected
results, and goal margins therefore already change ratings. Each club's deviation from 1500
retains 75% across an offseason (or 0.75 ** elapsed_seasons across a gap). Later results also
change the effect of earlier results through evolving opponent expectations.

Historical replay starts in July 2010 at 1500, carries ratings forward, and uses **no present-day
squad valuations**. The live model's valuation prior is not injected into historical forecasts.
UCL data begins in 2011/12. There is no discrete trophy, reputation, or last-five-years bonus.
European history is present implicitly through all pre-cutoff UCL rating updates and their
subsequent effects on domestic opponents. It cannot be reduced to a fixed percentage of Elo.

For scale, removing UCL matches from the replay, leaving everything else fixed, changes these
ratings immediately before the 2020/21 R16 (full replay minus domestic-only replay):

| Club | Baseline Elo | Existing UCL effect, Elo points |
|---|---:|---:|
| Bayern Munich | 1806.81 | +66.26 |
| Man City | 1777.38 | +36.79 |
| Real Madrid | 1683.92 | +1.11 |
| FC Barcelona | 1726.21 | +25.28 |
| Paris Saint-Germain | 1729.52 | +11.03 |
| Porto | 1596.93 | +96.93 |

This is a descriptive ablation, not a sum of points earned directly in UCL: removing matches
also changes later expectations and results' rating effects. Porto has no Portuguese domestic
coverage, so its domestic-only comparator remains at 1500. Outside-five clubs are included
in UCL replay but have incomplete total performance evidence.

An extra feature could capture persistent UCL-specific over/underperformance after accounting
for general Elo strength. It cannot supply new matches, unseen tactical information, injuries,
or evidence of a permanent "European pedigree" effect simply by reusing the same results.

## Experimental mathematics

**A:** Call the existing R16 backtester unchanged. Its Davidson probabilities are converted to
score distributions using only pre-cutoff match scores. Both legs, recorded neutral venues,
historical away goals, extra time, and penalties use the existing backtest functions.
All predictions for a round freeze immediately before its earliest first leg.

**B:** Extract the pre-match residual `r_team,m = S_team,m - E_team,m` for each historical
UCL match from the unchanged Elo replay. Away residuals are the negative of home residuals.
Aggregate `z_team = sum(r_team,m) / (10 + number_of_UCL_matches)`.
Ten zero-residual pseudo-matches shrink sparse histories toward zero. This fixed shrinkage
assumption was not selected using held-out outcomes.

If A gives first-leg-home club a an advancement probability p, adjust it with:

`p_B = sigmoid(logit(p) + beta * (z_a - z_b))`

This is a probability-calibration covariate, not an extra Elo update. A coefficient of zero
returns A's exact original probability; negative coefficients are permitted during fitting.
The fixture and both-leg calculations remain inherited from A.

**C:** Use the same offset but weight each UCL residual by
`w_m = 2 ** (-age_in_years / half_life_years)`:

`z_team = sum(w_m * r_team,m) / (10 + sum(w_m))`

The decay is configurable, and older observations exert less influence. There is no trophy bonus,
club-name lookup, or second inclusion of UCL fixtures in Elo. Each unique match contributes one
residual per participant. Residuals still come from information already used by Elo: they are
**not independent new evidence**. The learned offset tests their incremental predictive value
conditional on the baseline rather than treating the same wins as fresh rating points.

## Selection protocol and coverage

- Warmup: 2010/11 domestic history and 2011/12 UCL; 2011/12 R16 is excluded from fitting because
  the European-history warmup is short.
- Training: **2012/13–2016/17, 40 ties**. For each feature, choose beta minimizing training log loss.
- Validation: **2017/18–2019/20, 24 ties**. Select C's half-life by validation log loss, not accuracy.
  B uses its training-fit coefficient unchanged. No refitting after validation.
- Final comparison: **2020/21–2025/26, 48 ties**, matching the original saved baseline.
- Beta grid: **-8, -4, -2, -1, 0, 1, 2, 4, 8**. C half-lives: **0.5, 1, 2, 4 years**.
- Default shrinkage: **10 effective matches**. No Elo or Davidson parameters were tuned.

There are 112 evaluated R16 ties across 14 seasons, with eight reviewed two-legged ties per
season. Every feature query uses `match_date < cutoff`; expected scores are from before each
historical match. Score calibration uses the same strict prefix. There are 1,215 UCL matches
in the 2020/21 prefix (20,489 total matches), increasing to 1,968 UCL matches in the 2025/26
prefix (30,400 total). Full per-season counts, cutoffs, hashes, and forecasts are saved in JSON.

The evaluation outcomes and baseline accuracy were already known before this experiment.
They were withheld from coefficient/decay selection, but this is not a prospectively unseen
benchmark. Future changes inspired by these findings need a fresh evaluation sample.

### Parameters selected using earlier seasons

| Feature | Training-selected beta | Training log loss | Validation correct | Validation log loss |
|---|---:|---:|---:|---:|
| B: all history | 4 | 0.473629 | 15/24 | 0.660773 |
| C: 0.5-year half-life | 0 | 0.482728 | 17/24 | 0.630894 |
| C: 1-year half-life | 2 | 0.481323 | 18/24 | 0.636747 |
| C: 2-year half-life | 4 | 0.478014 | 16/24 | 0.646050 |
| C: 4-year half-life | 4 | 0.475822 | 15/24 | 0.651093 |

B selected beta=4. C selected a 0.5-year half-life with beta=0. This means the validated
recency adjustment turned itself off; it does not demonstrate that six-month memory is optimal.
The one-year candidate had higher validation accuracy but worse validation log loss. Choosing
it afterward for its accuracy would change the declared selection objective.

## Measured final comparison

Binary Brier is mean `(p - outcome)^2`; log loss uses natural logarithms. Lower is better.
Accuracy changes are percentage points. The original saved baseline artifact matched exactly,
including every forecast, cutoff, input hash, and configuration hash.

| Model | Correct / ties | Accuracy | Brier | Log loss | Accuracy vs A | Brier vs A | Log loss vs A |
|---|---:|---:|---:|---:|---:|---:|---:|
| A | 38/48 | 79.17% | 0.180565 | 0.544120 | +0.00 | +0.000000 | +0.000000 |
| B | 37/48 | 77.08% | 0.173047 | 0.526798 | -2.08 | -0.007518 | -0.017322 |
| C | 38/48 | 79.17% | 0.180565 | 0.544120 | +0.00 | +0.000000 | +0.000000 |
| Higher-Elo-wins | 39/48 | 81.25% | N/A | N/A | +2.08 | N/A | N/A |

Higher-Elo-wins ignores leg order and selects the higher frozen rating (A on exact ties).
It is a decision rule without probabilities, so assigning it Brier/log-loss scores would require
an arbitrary confidence assumption. It beat A by one tie but cannot supply bracket probabilities.

| Split | A: correct, Brier, log loss | B: correct, Brier, log loss | C: correct, Brier, log loss |
|---|---|---|---|
| training | 35/40, 0.149828, 0.482728 | 35/40, 0.146762, 0.473629 | 35/40, 0.149828, 0.482728 |
| validation | 17/24, 0.219795, 0.630894 | 15/24, 0.233478, 0.660773 | 17/24, 0.219795, 0.630894 |
| evaluation | 38/48, 0.180565, 0.544120 | 37/48, 0.173047, 0.526798 | 38/48, 0.180565, 0.544120 |

Training values describe fitted performance, not independent evaluation.

### Where decisions changed

C has no disagreements with A. B changes nine final-sample decisions: four corrections and five
new errors. Examples include both successful and unsuccessful adjustments involving major clubs:

| Season | Tie | A: probability of first club | B: probability of first club | Actual advancing club |
|---|---|---:|---:|---|
| 2020-2021 | FC Barcelona – Paris Saint-Germain | 49.58% | 52.27% | Paris Saint-Germain |
| 2020-2021 | RB Leipzig – Liverpool | 49.77% | 52.80% | Liverpool |
| 2021-2022 | Atlético de Madrid – Man United | 48.38% | 52.70% | Atlético de Madrid |
| 2022-2023 | Milan – Tottenham | 51.03% | 43.57% | Milan |
| 2022-2023 | Borussia Dortmund – Chelsea | 53.12% | 43.57% | Chelsea |
| 2024-2025 | Paris Saint-Germain – Liverpool | 50.25% | 45.68% | Paris Saint-Germain |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | 49.50% | 57.33% | Bayern Munich |
| 2024-2025 | Borussia Dortmund – LOSC | 45.37% | 54.86% | Borussia Dortmund |
| 2025-2026 | Bodø/Glimt – Sporting CP | 47.58% | 52.51% | Sporting CP |

For example, the adjustment incorrectly favors Barcelona over PSG in 2020/21, correctly favors
Bayern over Leverkusen in 2024/25, and incorrectly favors Liverpool over PSG that same season.
A history-based correction is not reliably helpful even for well-known European clubs.

## Strength of evidence and limitations

- B loses one correct decision: -2.08 percentage points, with four paired gains and five losses.
  The exact two-sided paired discordance test gives p=1.00. Nine changed decisions do not
  establish an accuracy improvement. C is identical to A.
- B improves Brier by 0.007518 and log loss by 0.017322 on the 48 evaluation ties, but worsens both
  scores on validation. Better probability scores can coexist with worse threshold accuracy:
  confidently wrong forecasts may become less wrong without crossing 50%, while borderline
  correct forecasts may flip. This evidence is insufficient to deploy B.
- A simple independence-based approximate 95% interval for B-minus-A mean log loss is
  [-0.0470, +0.0123], including no improvement. Clubs and seasons are correlated, so this
  interval is descriptive rather than a reliable independence-based significance claim.
- Only 40 training and 24 validation ties support parameter selection; 48 evaluation ties are
  also small. Grid selection adds uncertainty. This tests these residual-offset variants,
  not every possible use of European history.
- Top-five domestic coverage excludes other countries, Europa/Conference League matches,
  injuries, lineups, managerial changes, and historical squad values. UCL participation is
  selective; missing domestic evidence for outside-five clubs affects their expected scores.
- Neutral-venue metadata can be incomplete. The existing extra-time score thinning assumption,
  equal 50/50 penalties, and frozen pre-round ratings are inherited limitations.
- The database contains retrospectively corrected final results, not publication-time snapshots.
  Cutoff protection prevents future match outcomes from entering forecasts, but cannot reconstruct
  which corrections or venue details were publicly available on a historical day.
- Historical UCL starts in 2011/12, so earlier European achievements are absent. All five domestic
  sources are present from 2010/11, with documented curtailed seasons; current data was not edited.

## Implementation and reproduction

Only these files were added:

- `backend/app/backtesting/europe_experiment.py`: isolated replay-derived residual features,
  calibrated probability offsets, earlier-season parameter selection, and evaluation runner.
- `backend/tests/test_europe_experiment.py`: identity/symmetry, cutoff and future-result isolation,
  sparse-history shrinkage, decay, missing history, and earlier-only deterministic selection.
- `docs/europe-experiment.json`: measured comparisons, all forecasts, coverage and provenance.
- This report, `docs/europe-experiment.md`.

From the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.europe_experiment \
  --output docs/europe-experiment.json
.venv/bin/pytest backend/tests -q
```

Optional flags: `--half-lives 0.5 1 2 4`, `--coefficients -8 -4 -2 -1 0 1 2 4 8`,
`--prior-matches 10`. Changing grids after inspecting evaluation results invalidates a fresh
held-out claim. The runner checks the database file SHA-256 before/after and refuses to save
if it changed during the run. No migrations, production configuration changes, or new dependencies.

Verification: **173 tests passed**, including the three new experiment tests; Ruff passed for
both new Python files. One existing AnyIO deprecation warning remains. A final focused rerun
also passed all nine experiment/backtester tests.

## Explaining this in an internship interview

“I started by checking what the model already knew. Champions League games were already changing
Elo, so adding points for European success could reward the same wins twice. I kept the production
model fixed and built an offline experiment around its mistakes: did a club repeatedly do better
in Europe than its rating predicted? I tested that signal with and without time decay.

“I fitted the adjustment using older seasons, chose the decay on a separate validation period,
and compared the frozen variants on later seasons. I tested that changing a future score cannot
change a past feature or prediction. The baseline reproduced exactly. The extra history signal
slightly improved probability scores but lost one correct prediction; the best validated recency
variant applied no adjustment. I recommended keeping the simpler baseline rather than assuming
that an extra feature must help.”
