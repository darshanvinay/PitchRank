# Recent-form Elo and probability-ensemble experiment

## Recommendation

**Retain Model A. Do not deploy the recent-form model or either ensemble.**
Training selected a rolling three-year replay with K=25 as B. B did not correct any of A's ten
wrong evaluation R16 predictions and introduced two additional errors. Both ensembles introduced
one additional error, with slightly worse Brier scores and log loss than A. Their conditional
full-bracket accuracy also fell. These estimates are uncertain, but there is no demonstrated
benefit to justify adding this ensemble to production.

This conclusion applies to the tested neutral-prior rolling-window Elo variants. It does not prove
that all possible recent-form features are useless. No player, injury, lineup or tactical information
was added, and no genuinely independent form signal was measured.

## 1. Frozen protocol and leakage controls

- **A** is the existing historical Elo model: chronological domestic and UCL matches from July 2010,
  neutral 1500 starting ratings, K=20, existing home advantage/goal margin/importance, 25% offseason
  regression and unchanged Davidson probabilities. All 48 saved evaluation probabilities and winners
  reproduced **exactly**, including Brier and log loss.
- **B** reuses precisely the same replay and probability functions, but resets at a rolling cutoff
  minus **1, 2 or 3 calendar years**. These are season-length windows, not July-to-June roster slices.
  Every artifact records the exact start date. A February 2021 three-year replay starts in February
  2018. A leap-day subtraction uses 28 February if necessary.
- B's K grid is **20 (window-only control), 25, 30, 40**. The 3x4 factorial grid separates window
  truncation from faster updates. All other Elo/Davidson parameters remain unchanged. No squad-value
  prior is read, historical or current. B has no rating information from before its replay start.
- **Shared goal-score calibration:** both models use all available pre-cutoff results to fit the
  existing empirical score-shape adapter. Only Elo's replay horizon/K changes. B is a recent-*Elo*
  experiment, not a separately tuned recent-goal or draw model.
- **Common cutoff:** reconstruct both models strictly before the earliest R16 first-leg date, freeze
  all forecasts, then read labels. This is before *every* tie, and is stricter than updating between
  the first and second R16 weeks. Tie-specific later cutoffs are intentionally not used: they would
  change A's original comparison and permit information from earlier R16 ties.
- The entire knockout forecast retains those same frozen ratings. Every later hypothetical matchup
  uses them; no first-leg, later-round, or future domestic result can update either model.
- Missing pre-cutoff history for a participating club raises an error. No future membership list or
  current squad-value estimate is used to fill a rating.

### Chronological splits

| Purpose | Seasons | Ties | Selection role |
|---|---|---:|---|
| Training | 2013/14–2016/17 | 32 | Select B window/K using R16 log loss |
| Validation | 2017/18–2019/20 | 24 | Select B's ensemble weight using log loss |
| Evaluation | 2020/21–2025/26 | 48 | Report frozen choices; no fitting |

Training originally considered 2012/13, but before inspecting performance it was moved to 2013/14:
a three-year window in early 2013 would begin before the domestic archive starts. All training
windows now have full three-year **domestic** coverage. UCL begins in 2011/12, so the oldest part
of the earliest three-year training window still lacks 2010/11 UCL results. No unavailable results
were fabricated. Later evaluation windows have the available complete main-draw archive.

All these historical seasons have been examined in prior PitchRank studies. This is a retrospective
parameter-held-out comparison, **not a fresh blind benchmark**. Reusing a split does not undo previous
exposure or repeated experimentation. A completed prospective 2026/27 knockout test is not available.

The weight grid was declared before inspecting errors: **B weights 0, 0.1, …, 1.0**. The fixed 50/50
ensemble was also declared in advance. Training chooses B; validation chooses its mixing weight.
Evaluation error analysis never chooses a window, K, weight, or calibration adjustment.

## 2. Individual models — inspected before any ensemble run

B was selected by lowest training log loss, not evaluation accuracy. Its selected configuration was
**three rolling years, K=25**. All candidates and all tie-level forecasts are saved in the individual
JSON, so errors of the unselected candidates can also be inspected.

| Candidate | Training correct / 32 | Training log loss | Validation correct / 24 | Validation Brier / log loss | Evaluation correct / 48 | Evaluation Brier / log loss |
|---|---:|---:|---:|---|---:|---|
| A | 28 | 0.483605 | 17 | 0.219795 / 0.630894 | 38 | 0.180565 / 0.544120 |
| B-window1-K20 | 28 | 0.516767 | 16 | 0.223510 / 0.639218 | 34 | 0.194207 / 0.575574 |
| B-window1-K25 | 26 | 0.506868 | 16 | 0.223835 / 0.640326 | 34 | 0.192990 / 0.571769 |
| B-window1-K30 | 26 | 0.501434 | 16 | 0.224604 / 0.642614 | 33 | 0.193226 / 0.571192 |
| B-window1-K40 | 26 | 0.498612 | 15 | 0.226738 / 0.648918 | 32 | 0.196288 / 0.576019 |
| B-window2-K20 | 28 | 0.490051 | 17 | 0.219543 / 0.630041 | 37 | 0.182990 / 0.549864 |
| B-window2-K25 | 28 | 0.485865 | 17 | 0.220317 / 0.632237 | 35 | 0.183831 / 0.550314 |
| B-window2-K30 | 28 | 0.485466 | 17 | 0.221382 / 0.635350 | 33 | 0.185808 / 0.553437 |
| B-window2-K40 | 26 | 0.490689 | 16 | 0.223890 / 0.642809 | 31 | 0.191511 / 0.563983 |
| B-window3-K20 | 28 | 0.484659 | 17 | 0.219165 / 0.629400 | 37 | 0.180940 / 0.545109 |
| B-window3-K25 | 28 | 0.481982 | 17 | 0.219562 / 0.631101 | 36 | 0.182575 / 0.547376 |
| B-window3-K30 | 28 | 0.482691 | 17 | 0.220281 / 0.633762 | 33 | 0.185077 / 0.551754 |
| B-window3-K40 | 26 | 0.489367 | 17 | 0.222246 / 0.640538 | 31 | 0.191320 / 0.563708 |

The one-year variants performed worse on evaluation. Increasing K within those short windows did
not generalize into better hard-pick accuracy. No one of the 12 tested B configurations beat A on
evaluation Brier or log loss. The selected B had a small training advantage that did not persist.
This is consistent with discarded strength evidence, restart effects and noisy fast updates; the
experiment does not isolate those causal explanations from one another.

### Probability calibration of A and selected B

Brier is conventional binary advancement Brier, mean `(p-y)^2`; log loss uses natural logarithms.
Lower is better. The following reliability table bins the probability that the **first-leg home club**
advances. Predictions are not re-calibrated using evaluation labels.

| Probability bin | A: count | A: mean predicted / actual rate | B: count | B: mean predicted / actual rate |
|---|---:|---|---:|---|
| 0%–20% | 3 | 17.4% / 0.0% | 3 | 16.9% / 0.0% |
| 20%–40% | 19 | 30.4% / 15.8% | 19 | 29.8% / 15.8% |
| 40%–60% | 20 | 49.1% / 35.0% | 19 | 48.7% / 36.8% |
| 60%–80% | 6 | 64.1% / 83.3% | 7 | 64.4% / 71.4% |
| 80%–100% | 0 | — | 0 | — |

A's mean favorite confidence is 63.00%, against 79.17%
correct favorites; B's is 63.54%, against 75.00% correct.
These are descriptive underconfidence patterns in this sample, not a stable calibration diagnosis.
Several bins have only 3–7 ties or are empty. Bin membership also changes with the model, so these
small-bin rates should not be treated as independent proof that a particular probability range is
miscalibrated. Overall Brier/log loss give no calibration improvement for selected B.

### Which evaluation ties are wrong?

The table contains the union of wrong predictions. A dash means the model was correct. P(first)
is the probability that the first-named, first-leg-home club advances.

| Season | Tie | Actual advancing club | A wrong pick | B wrong pick | A P(first) | B P(first) |
|---|---|---|---|---|---:|---:|
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | Sevilla FC | Sevilla FC | 56.01% | 57.99% |
| 2020-2021 | Atlético de Madrid – Chelsea | Chelsea | Atlético de Madrid | Atlético de Madrid | 59.88% | 61.43% |
| 2020-2021 | Porto – Juventus | Porto | Juventus | Juventus | 36.15% | 35.55% |
| 2020-2021 | RB Leipzig – Liverpool | Liverpool | — | RB Leipzig | 49.77% | 52.48% |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | Man United | Man United | 48.38% | 47.37% |
| 2021-2022 | Villarreal CF – Juventus | Villarreal CF | Juventus | Juventus | 37.11% | 36.66% |
| 2021-2022 | Benfica – Ajax | Benfica | Ajax | Ajax | 33.50% | 34.44% |
| 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | Borussia Dortmund | Borussia Dortmund | 53.12% | 54.78% |
| 2023-2024 | Inter – Atlético de Madrid | Atlético de Madrid | Inter | Inter | 64.14% | 65.82% |
| 2024-2025 | Club Brugge – Aston Villa | Aston Villa | — | Club Brugge | 46.81% | 50.30% |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | Bayer Leverkusen | Bayer Leverkusen | 49.50% | 48.82% |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | LOSC | LOSC | 45.37% | 43.43% |

On validation both models miss the same seven ties:

| Season | Tie | Shared wrong pick | Actual advancing club |
|---|---|---|---|
| 2017-2018 | Sevilla FC – Man United | Man United | Sevilla FC |
| 2017-2018 | Real Madrid – Paris Saint-Germain | Paris Saint-Germain | Real Madrid |
| 2018-2019 | Man United – Paris Saint-Germain | Paris Saint-Germain | Man United |
| 2018-2019 | Roma – Porto | Roma | Porto |
| 2018-2019 | Ajax – Real Madrid | Real Madrid | Ajax |
| 2019-2020 | Olympique Lyonnais – Juventus | Juventus | Olympique Lyonnais |
| 2019-2020 | Atlético de Madrid – Liverpool | Liverpool | Atlético de Madrid |

### Disagreement and complementary errors

| Split | Both correct | Both wrong | B corrects A | B spoils A | Disagreements | Oracle union correct |
|---|---:|---:|---:|---:|---:|---:|
| validation | 17 | 7 | 0 | 0 | 0/24 | 17/24 |
| test | 36 | 10 | 0 | 2 | 2/48 | 38/48 |

Evaluation disagreement is **2/48 = 4.17%**. Forecast-probability Pearson correlation is **0.9960**.
B's two different picks are Leipzig over Liverpool in 2020/21 and Club Brugge over Aston Villa
in 2024/25; both are wrong. It supplies **zero complementary correct picks** in either validation
or evaluation. The oracle union is a hindsight upper bound, not a usable forecasting strategy.

More strongly, on all ten A-wrong evaluation ties, **both probabilities lie on the wrong side of
50%**. A convex probability average cannot cross to the correct side on those ties. Therefore this
A/B ensemble cannot beat A's 38/48 hard-pick accuracy on this particular sample; it can at best
retain those 38 correct picks. Probability losses could still improve without changing winners,
which is why the ensembles were measured rather than dismissed solely from hard errors.

## 3. Probability ensembles — tested after individual/error inspection

For any known matchup, use `p_E = (1-w)*p_A + w*p_B`, with w the B weight. Probabilities, not Elo
ratings, are averaged. A weight of zero or one reproduces the corresponding component exactly.
The same fixed weight is used at every tournament node, including the single-match final.

This defines a local conditional-probability ensemble. Its complete-bracket probability multiplies
those blended node probabilities; it is not a latent-model mixture that chooses A or B once for
an entire tournament. It does not provide a new ensemble Elo rating.

### Earlier validation weight selection

| B weight | Validation correct / 24 | Brier | Log loss |
|---:|---:|---:|---:|
| 0.0 | 17 | 0.219795 | 0.630894449 |
| 0.1 | 17 | 0.219755 | 0.630862950 |
| 0.2 | 17 | 0.219719 | 0.630842621 |
| 0.3 | 17 | 0.219687 | 0.630833608 |
| 0.4 | 17 | 0.219658 | 0.630836061 |
| 0.5 | 17 | 0.219633 | 0.630850139 |
| 0.6 | 17 | 0.219612 | 0.630876005 |
| 0.7 | 17 | 0.219594 | 0.630913828 |
| 0.8 | 17 | 0.219580 | 0.630963783 |
| 0.9 | 17 | 0.219569 | 0.631026054 |
| 1.0 | 17 | 0.219562 | 0.631100829 |

Validation selects **w=0.3**, meaning 70% A and 30% B. Its validation log-loss improvement over A
is only about **0.000061**, with no additional correct picks. Such a shallow minimum from 24 ties
is weak evidence for a reliably optimal weight. It is not retuned after seeing evaluation results.

### Evaluation R16 results

| Model | Correct / ties | Accuracy | Brier | Log loss | Accuracy vs A, percentage points |
|---|---:|---:|---:|---:|---:|
| A: historical | 38/48 | 79.17% | 0.180565 | 0.544120 | +0.00 |
| B: 3 years, K=25 | 36/48 | 75.00% | 0.182575 | 0.547376 | -4.17 |
| 50/50 probabilities | 37/48 | 77.08% | 0.181521 | 0.545665 | -2.08 |
| 70% A / 30% B | 37/48 | 77.08% | 0.181127 | 0.545027 | -2.08 |
| Higher-Elo-wins, A ratings | 39/48 | 81.25% | N/A | N/A | +2.08 |
| Higher-Elo-wins, B ratings | 36/48 | 75.00% | N/A | N/A | -4.17 |

Both ensembles retain A's ten common mistakes and additionally predict Leipzig over Liverpool.
Neither repeats B's Club Brugge error. A's higher-Elo decision rule gets one extra tie correct, but
has no probability distribution to score. No arbitrary certainty was assigned to it for Brier or
log loss, and its one-tie advantage does not justify replacing a probability model.

## 4. Conditional full-knockout comparison

All models freeze before the R16. Recorded later pairings, home order and venue flags are explicitly
supplied as a **retrospective bracket scenario**. They were not established as known at the cutoff.
Later results never enter Elo reconstruction or probability calibration. This is **not unconditional
historical tournament prediction** and does not model draw uncertainty.

Two-legged ties preserve the historical away-goals rule through 2020/21 and its later absence,
extra-time scoring and shootouts. The final is a single neutral match. All use the existing functions.
The 2019/20 single-leg COVID later rounds are not scored as two-legged fixtures: validation concerns
R16 only; full-bracket evaluation begins in 2020/21.

### Propagating each model's own winners

| Model | Greedy correct / 90 | Global correct / 90 | Greedy/global champions, of 6 | Greedy/global finalists, of 12 | Exact brackets |
|---|---:|---:|---|---|---|
| A: historical | 57 | 57 | 1/1 | 3/3 | 0/6, 0/6 |
| B: 3 years, K=25 | 55 | 54 | 1/1 | 3/3 | 0/6, 0/6 |
| 50/50 probabilities | 56 | 56 | 1/1 | 3/3 | 0/6, 0/6 |
| 70% A / 30% B | 56 | 56 | 1/1 | 3/3 | 0/6, 0/6 |
| Higher-Elo-wins, A ratings | 58 | Decision rule only | 1 | 3 | 0/6 |
| Higher-Elo-wins, B ratings | 55 | Decision rule only | 1 | 3 | 0/6 |

Global optimization maximizes joint complete-bracket probability, not realized accuracy. B's global
bracket scores one outcome worse than its greedy bracket; this does not indicate a DP error.
Finalists are semifinal advancements and are not counted a second time in the 90-outcome total.
Exact-bracket and champion rates have only six tournament trials.

### Actual participants in each later round (a separate conditional task)

Each round here receives its actual clubs, even if a model eliminated them in its own bracket.
These scores measure matchup predictions conditional on those participants, not a coherent pre-R16
propagated forecast. They must not be combined with the own-winner accuracy above.

| Model | QF correct / 24 | QF Brier / log loss | SF correct / 12 | SF Brier / log loss | Final correct / 6 | Final Brier / log loss |
|---|---:|---|---:|---|---:|---|
| A: historical | 17 | 0.213974 / 0.617774 | 8 | 0.222880 / 0.636180 | 3 | 0.260013 / 0.714535 |
| B: 3 years, K=25 | 17 | 0.213588 / 0.616735 | 8 | 0.221846 / 0.633708 | 3 | 0.263112 / 0.721111 |
| 50/50 probabilities | 17 | 0.213716 / 0.617123 | 8 | 0.222317 / 0.634855 | 3 | 0.261522 / 0.717733 |
| 70% A / 30% B | 17 | 0.213804 / 0.617353 | 8 | 0.222531 / 0.635363 | 3 | 0.260909 / 0.716432 |

The higher-Elo rules score 17/24 quarterfinals, 8/12 semifinals and 3/6 finals with actual
participants under either rating set. Small improvements in B's conditional QF/SF probability
losses do not translate into improved propagated brackets; final probability scores worsen.

## 5. Uncertainty, limitations and decision

| Model | R16 accuracy Wilson 95% | Paired log-loss delta vs A | Approx season-cluster 95% |
|---|---|---:|---|
| A: historical | 65.7%–88.3% | +0.000000 | [+0.000000, +0.000000] |
| B: 3 years, K=25 | 61.2%–85.1% | +0.003255 | [-0.008978, +0.015489] |
| 50/50 probabilities | 63.5%–86.7% | +0.001545 | [-0.004544, +0.007634] |
| 70% A / 30% B | 63.5%–86.7% | +0.000907 | [-0.002740, +0.004554] |

The accuracy intervals assume independent ties, which is imperfect because clubs and seasons repeat.
Paired log-loss intervals use six season-mean differences, their standard error and t(5)=2.571.
They are descriptive approximations from only six clusters, not definitive significance tests.
All nonbaseline paired intervals include zero. The exact paired A-versus-B hard-pick discordance
test gives p=0.5 (zero gains, two losses); this does not establish a statistically certain disadvantage
either. One correct champion in six has a Wilson interval of roughly 3.0%–56.4%.

Additional limitations:

- Only 32 training and 24 validation ties select 12 replay candidates and 11 mixing weights.
  Model-selection variance and repeated historical experimentation are substantial.
- Evaluation outcomes were already discussed in prior experiments. The selection code excludes
  them, but that does not make the research history prospectively blind.
- UCL-only clubs outside the five leagues lack domestic results, especially damaging for a short
  reset window. Window truncation changes cold-start/convergence as well as recency; it is not a
  pure temporal weighting experiment.
- Current squad values are excluded. No historical values, lineups, injuries or unavailable games
  are invented. Neutral-venue metadata and retrospectively corrected source data retain existing limits.
- Match outcomes within a propagated bracket are dependent; 90 outcomes are not 90 independent
  tournament observations. Historical draw assumptions limit what full-tournament scores mean.
- Proper scoring gains can exist without extra correct picks, but neither tested ensemble improves
  R16 probability scores. Selecting a different weight/window now using these test results would
  invalidate the declared comparison.

The strongest supported decision is to **keep A and leave these models undeployed**. The proposed
recent-form Elo is largely redundant with A and supplies no complementary R16 correct picks here.
Future research would need a genuinely different, historically timestamped signal and a predeclared
fresh evaluation period. This report does not recommend another parameter sweep on the same 48 ties.

## 6. Reproduction and verification

From the repository root, keep the two stages separate:

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.recent_form \
  --stage individual --output docs/recent-form-individual.json
# Inspect individual metrics, errors and complementarity first.
PYTHONPATH=backend .venv/bin/python -m app.backtesting.recent_form \
  --stage ensemble --input docs/recent-form-individual.json \
  --output docs/recent-form-ensemble.json
.venv/bin/pytest backend/tests -q
```

The two JSON artifacts include all candidate R16 forecasts, selected-model errors, calibration bins,
window dates/counts/input hashes, the validation weight grid, full conditional brackets and database
SHA-256. The second stage verifies the database matches the first artifact and records that artifact's
SHA-256. Both stages reject database changes during a run. Only local report files are written.

Added files: `backend/app/backtesting/recent_form.py`, `backend/tests/test_recent_form.py`,
`docs/recent-form-individual.json`, `docs/recent-form-ensemble.json`, and this report. No production
code, API, UI, database or dependency was modified. Earlier cross-league experiment files were preserved.
Nothing was deployed, committed or pushed.

Verification: **186 backend tests passed**, including four focused recent-form tests; Ruff passed.
Tests cover exact baseline replay parity, future/cutoff-day isolation, exclusion of results outside
the recent window, leap-date handling, split separation, complementary-error accounting, probability
mixture endpoints, validation-only weight selection, and full-bracket probability blending/scoring.
The original 48 R16 probabilities and winners, aggregate baseline metrics and database checksum were
also verified exactly. One existing AnyIO deprecation warning remains.
