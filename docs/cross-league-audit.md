# Cross-league Elo audit and isolated experiments

## Decision

Retain **A** for production Champions League predictions. No variant demonstrated a convincing
cross-league knockout improvement. B slightly improved UCL match log loss but worsened R16 and
propagated bracket accuracy; its match-level confidence interval includes no improvement.
C improved domestic match probability scores, but worsened UCL scores. It is a domestic-calibration
research candidate, not evidence of improved cross-league comparisons. D did not help overall.
E's validation gate retained B alone; no multi-component combination was justified.
No production module, parameter, endpoint, UI file, database record or historical result was changed.

## 1. Audit findings

### Shared pool, initialization and chronology

- Five domestic leagues and UCL use canonical club IDs and one connected Elo replay. Domestic
  matches transfer points between clubs in the same league. UCL provides the cross-league links,
  including opponents outside the top five. Those opponents lack domestic coverage in this dataset.
- Match updates are zero-sum: `delta = K * I * G * (S-E)` and the opponent receives `-delta`.
  K=20, H=65, scale=400; G=max(1,ln(1+goal margin)). Importance is 1 domestic, 1.25 UCL group/league,
  1.50 knockout and 1.75 semifinal/final. Large-margin victories can therefore move more points.
- Historical replay starts in July 2010 with neutral 1500 priors and 25% offseason regression
  toward 1500, once per club's observed new season; a gap uses `0.75 ** elapsed_years`.
  Unseen clubs start at 1500. Returning clubs retain their regressed historical rating.
  There is **no promotion-specific calibration** on this path. `promoted_default=1400` belongs
  to the older research replay and is not used by `services/historical.py`.
- Live ratings are a **different replay configuration**: the default window begins in 2024/25;
  `calculate_season` calls replay with its default zero offseason regression. Its initial prior is
  `1500 + clip(60*ln(value/556425000), -100, 100)`, applied once, not every season. The same market
  value gives the same prior across leagues. Missing values use 1500.
- Stored valuations date from **1–7 September 2026**. The live calculation back-applies its earliest
  available value to the start of the replay without matching `as_of` to each historical entry.
  Live history therefore must **not** be treated as a historically available forecast snapshot.
  The actual historical backtester uses no valuations and avoids that lookahead.
- Historical cutoff queries are strictly `match_date < cutoff`, excluding the entire cutoff day.
  Unknown kickoffs cause the day's results to be processed as one batch. No future outcome,
  future season membership list or current `Team.league` is used to initialize experimental history.
  Experiments infer league membership from already observed domestic participation.
- The older `elo/replay.py` research implementation precomputes full-season membership. That
  future-membership assumption is inappropriate for cutoff-safe forecasting, but is not used by
  the historical service or these experiments.
- No duplicate provider identifiers were found. Match uniqueness constraints and existing reviewed
  season/tie checks prevent repeat imports. Each replay match ID appears once. UCL history is
  already part of baseline Elo; B does not replay UCL a second time or add trophy bonuses.

### Point transfers and active-pool drift

At the 2025/26 pre-R16 cutoff, the baseline has these active domestic means and cumulative UCL
point transfers since the reconstruction start. Membership is determined from past domestic results.
A positive transfer means net points received through UCL; it is not automatically evidence of bias.

| League | Active-club mean Elo | Cumulative net UCL points | B learned offset, Elo |
|---|---:|---:|---:|
| epl | 1563.09 | +1197.19 | +25.80 |
| laliga | 1524.28 | +554.92 | -2.27 |
| bundesliga | 1524.10 | +319.66 | -8.27 |
| seriea | 1526.85 | -189.33 | -10.15 |
| ligue1 | 1526.29 | -459.94 | -5.10 |

Outside/unidentified-domestic clubs account for -1422.49 net UCL points; all six transfer buckets sum to zero within floating-point tolerance.

The top-flight pool is not closed across seasons: low-rated clubs can leave while new clubs enter at
1500. Strong retained clubs and weaker dormant clubs also undergo regression at different observed
season boundaries. Active means therefore need not stay at 1500 or match between leagues. Counts
also differ (18 versus 20 clubs). Equalizing league averages would erase genuine strength evidence.

Across all **247 observed clubs**, baseline deviation from `1500 * club_count` is
**-7656.50 points** at this cutoff. The independently accumulated non-match
initialization/regression ledger is **-7656.50**, matching that deviation.
This is structural pool drift from asynchronous regression/participation, not points created by match
arithmetic. Inactive clubs' old ratings remain in the pool but are excluded from active top-flight rankings.

EPL has accumulated net European points and has the highest active mean. That alone cannot distinguish
real strength, UCL selection effects, newcomer-prior effects or calibration error. B explicitly tests
whether past cross-league residuals predict additional league differences beyond existing club Elo.

The six-season test has 878 completed UCL matches and 10,734 domestic matches. Full imported domestic
coverage remains 28,893 matches from 2010/11–2025/26, including the documented curtailed Ligue 1 season.
Historical test metrics stop at 2025/26. The stored 2026/27 results are scored separately below; they never enter training, validation or parameter selection.

## 2. Models and parameters

**A — unchanged baseline.** Uses the production historical `replay_season`, existing Davidson
probabilities, and existing two-leg/final/tournament functions. All 48 saved R16 probabilities and
winners match exactly, as do aggregate binary Brier and log loss. The original 38/48 baseline is preserved.

**B — regularized time-varying league offsets.** The underlying Elo history is A. For a UCL game
between clubs with previously observed top-five domestic memberships, record the pre-match Elo logit
`b_m = ln(10)*(R_home-R_away+H)/400`, actual fractional result `y_m` in (1, 0.5, 0), and a league-difference
vector x (+1 home league, -1 away league). Fit offsets o by maximizing:

`sum_m w_m * [y_m*log(sigmoid(b_m+c*x_m.o)) + (1-y_m)*log(1-sigmoid(b_m+c*x_m.o))] - sum(o_l^2)/(2*sigma^2)`

where c=ln(10)/400 and `w_m=2**(-age_years/half_life)`. Newton updates use NumPy only. The zero-centered
Gaussian prior anchors the otherwise relative scale, shrinks weak evidence and prevents arbitrary
league bonuses. No club reputation is an input. Unknown outside-five memberships do not supply league
fit observations, but their UCL games still update underlying club Elo normally.

At prediction, add a club's learned league offset **once** to its rating. Do not add it as a second
match update or recurring league bonus. Domestic differences cancel because both clubs share the
same offset. Offset observations condition on the underlying model's pre-match Elo, including its
existing European history: these are correlated residual data, not independent new matches.

Match forecasts refit using only matches before the start of that calendar month. R16/bracket forecasts
refit using only matches before the cutoff, then freeze both Elo and offsets for the entire tournament.
Offset prior standard deviation sigma grid: **25, 75 Elo**; half-life grid: **1, 3 years**.

**C — calibrated newcomer/re-entry prior.** On a club's first observed domestic fixture of a season,
if it had no domestic participation in the previous season, use the already observed previous-season
bottom quarter of that league's club-ending ratings as a conservative prior, bounded to [1350,1500].
Blend the prior correction by alpha, grid **0.5, 1**. First-season/no-history cases retain 1500.
A returning club receives the same evidence-based treatment rather than blindly trusting a stale
rating. Shift its starting prior, preserving any UCL match changes already earned earlier that season.
The bottom-quarter definition and conservative bounds are fixed design assumptions, not fitted facts
or claimed optimal values. This is a testable newcomer-calibration hypothesis, not a guaranteed improvement.
No historical market values are fabricated.

**D — bounded goal margin.** Reuse the existing Elo update, rescale its delta by
`min(G,cap)/G`, and apply the negative to the opponent. Cap grid **1.25, 1.75**. Expected score,
home advantage, K, importance and regression stay unchanged. This caps the margin multiplier,
not an arbitrary team's rating. The selected cap 1.75 affects goal differences of five or more.

**E — validation-gated combination.** Only components improving validation UCL match log loss are
eligible. Compare their combination with eligible individuals and A using validation only; do not force
multiple changes if the combination is unjustified. Here only B qualifies, so **E equals B**.

### Selection, chronology and test status

- Warmup: 2010/11 onward, including UCL from 2011/12.
- Training: **2012/13–2016/17**, 625 UCL matches. Select each individual candidate using training
  pre-match UCL 90-minute log loss. Training scores are model-development scores, not independent claims.
- Validation: **2017/18–2019/20**, 369 UCL matches and 24 R16 ties. Gate combinations here.
- Parameter-held-out test: **2020/21–2025/26**, 878 UCL matches, 10,734 domestic matches, 48 R16 ties
  and 90 knockout outcomes. No test score enters the parameter/combination selection code.
- Online offsets may learn from *earlier* test-period results when forecasting a later match; this
  is chronological walk-forward learning, not future leakage. Fixed hyperparameters are never retuned.
- **The historical test is not genuinely untouched data**: these same later seasons were already evaluated in previous
  PitchRank tasks. No claim of a prospectively unseen benchmark is justified. 2026/27 knockout outcomes
  are not available for a completed fresh tournament test. A separate previously unscored current-season match holdout is reported below. A genuinely prospective blind tournament test remains required.
- Validation knockout evaluation is R16 only: 2019/20 COVID later rounds were single-leg. The existing
  two-leg tournament evaluator is not applied to them. Full-bracket tests cover 2020/21 onward only.

| Candidate | Training UCL log loss | Validation UCL log loss |
|---|---:|---:|
| A | 0.940285 | 0.949015 |
| B-sd25-h1 | 0.940152 | 0.948499 |
| B-sd25-h3 | 0.940116 | 0.947727 |
| B-sd75-h1 | 0.940593 | 0.948179 |
| B-sd75-h3 | 0.940745 | 0.946110 |
| C-blend0.5 | 0.941667 | 0.950740 |
| C-blend1 | 0.943542 | 0.953399 |
| D-cap1.25 | 0.944505 | 0.953380 |
| D-cap1.75 | 0.940748 | 0.949475 |

Selected B: sigma=25, half-life=3 years; C: alpha=0.5; D: cap=1.75. All existing Elo/Davidson
parameters were held fixed. No manual Bayern, Real Madrid or league adjustment was made.

## 3. Probability and knockout comparisons

Match Brier is the unscaled three-class sum, range 0–2. Advancement Brier is the conventional binary
score, range 0–1; these two columns across different task tables should not be compared numerically.
Log loss uses natural logarithms. Lower probability scores are better.

### Test match probabilities (pre-match, continually updated history)

| Model | UCL correct / 878 | UCL Brier | UCL log loss | Domestic correct / 10,734 | Domestic Brier | Domestic log loss |
|---|---:|---:|---:|---:|---:|---:|
| A | 497 | 0.557056 | 0.942869 | 5607 | 0.596256 | 0.999412 |
| B | 498 | 0.555795 | 0.941216 | 5607 | 0.596256 | 0.999412 |
| C | 493 | 0.558143 | 0.944451 | 5612 | 0.594925 | 0.997476 |
| D | 498 | 0.557313 | 0.943251 | 5608 | 0.596351 | 0.999547 |
| E | 498 | 0.555795 | 0.941216 | 5607 | 0.596256 | 0.999412 |

### Separate 2026/27 match holdout

The saved earlier historical experiments did not score these **54 UCL and 394 domestic matches**.
All candidate configurations and combination decisions were fixed from the earlier training and
validation periods before scoring this slice. This is a newly scored research holdout, not a claim
that its public results were unseen by every prior human/model development decision. The runner
uses stored finished matches through **29 October 2026**, without downloading or changing data.
The latest stored completed match is **26 October 2026**. It is a partial snapshot and does not establish complete current-season coverage. There are no
completed 2026/27 R16 or later knockout outcomes to evaluate yet.

| Model | UCL correct / 54 | UCL Brier | UCL log loss | Domestic correct / 394 | Domestic Brier | Domestic log loss |
|---|---:|---:|---:|---:|---:|---:|
| A | 37 | 0.514943 | 0.886398 | 202 | 0.588648 | 0.989919 |
| B | 37 | 0.509942 | 0.879677 | 202 | 0.588648 | 0.989919 |
| C | 37 | 0.517058 | 0.889167 | 207 | 0.587237 | 0.987825 |
| D | 37 | 0.515112 | 0.886632 | 202 | 0.588738 | 0.990048 |
| E | 37 | 0.509942 | 0.879677 | 202 | 0.588648 | 0.989919 |

B again improves UCL probability scores without changing the number of correctly classified matches;
C again improves domestic scores but worsens UCL scores. Those repeated directions are interesting,
but 54 European matches from part of one season cannot establish durable cross-league improvement.
The higher-Elo decision rule gets 35/54 UCL matches under A/B/D/E, 33/54 under C; its domestic counts
are also saved in JSON. This holdout does not select or change any experimental parameter.

### Test R16 (frozen pre-round ratings)

| Model | Correct / 48 | Accuracy | Binary Brier | Log loss | Accuracy Wilson 95% | Higher-Elo-wins correct / 48 |
|---|---:|---:|---:|---:|---|---:|
| A | 38 | 79.17% | 0.180565 | 0.544120 | 65.7%–88.3% | 39 |
| B | 34 | 70.83% | 0.181626 | 0.545628 | 56.8%–81.8% | 35 |
| C | 38 | 79.17% | 0.180890 | 0.545119 | 65.7%–88.3% | 39 |
| D | 38 | 79.17% | 0.181061 | 0.545259 | 65.7%–88.3% | 38 |
| E | 34 | 70.83% | 0.181626 | 0.545628 | 56.8%–81.8% | 35 |

The simple higher-Elo rule has no probability distribution, so it has no Brier/log-loss score without
an additional confidence assumption. It predicts home/away winners only at match level (draws count
as wrong), and advancing clubs at tie level. Its UCL match correct counts are A=517, B=514, C=518,
D=516, E=514 out of 878; its domestic counts and per-round tie counts are in JSON.
A's draw-strength 0.7 means draw is never the largest Davidson probability; this affects hard-class
accuracy but does not invalidate probability scoring. Neither classifier nor home advantage was changed.

### Conditional later rounds, actual participants (frozen pre-R16 ratings)

Every row uses actual future pairings and participating clubs as explicit conditions. They are not
propagated model-winner forecasts or unconditional pre-R16 historical predictions.

| Model | QF correct / 24 | QF Brier / log loss | SF correct / 12 | SF Brier / log loss | Final correct / 6 | Final Brier / log loss |
|---|---:|---|---:|---|---:|---|
| A | 17 | 0.213974 / 0.617774 | 8 | 0.222880 / 0.636180 | 3 | 0.260013 / 0.714535 |
| B | 17 | 0.216845 / 0.622775 | 8 | 0.221679 / 0.632849 | 3 | 0.263296 / 0.721053 |
| C | 17 | 0.214992 / 0.620103 | 8 | 0.223753 / 0.638003 | 3 | 0.258466 / 0.711410 |
| D | 17 | 0.213539 / 0.616887 | 8 | 0.222899 / 0.636238 | 3 | 0.260007 / 0.714488 |
| E | 17 | 0.216845 / 0.622775 | 8 | 0.221679 / 0.632849 | 3 | 0.263296 / 0.721053 |

### Conditional full bracket, using own predicted winners

Recorded later draws, slot home order and venue flags are supplied as a retrospective scenario.
No later score affects any forecast. R16 and later two-legged rules are inherited unchanged;
the final is one neutral match with extra time/penalties. Finalist counts equal semifinal advancements
and are not added again to the 90-outcome denominator.

| Model | Greedy correct / 90 | Global correct / 90 | Greedy / global champions, of 6 | Greedy / global finalists, of 12 | Exact brackets |
|---|---:|---:|---|---|---|
| A | 57 | 57 | 1 / 1 | 3 / 3 | 0/6, 0/6 |
| B | 50 | 50 | 0 / 0 | 2 / 2 | 0/6, 0/6 |
| C | 57 | 57 | 1 / 1 | 3 / 3 | 0/6, 0/6 |
| D | 57 | 57 | 1 / 1 | 3 / 3 | 0/6, 0/6 |
| E | 50 | 50 | 0 / 0 | 2 / 2 | 0/6, 0/6 |

Global optimizes joint complete-bracket probability, not observed accuracy or expected correct picks.
Actual-participant and own-winner tasks have separate labels/denominators and are never pooled.
An unconditional full-tournament backtest remains unavailable without pre-cutoff draw evidence or
an explicit valid draw-uncertainty model.

### Confidence and generalization

Paired log-loss differences use the same games under each model. Intervals below use a season-cluster
sandwich SE and t(5)=2.571 for six test seasons. They are **descriptive approximations with only six
clusters**, not definitive significance tests. The Wilson accuracy intervals above also assume
independent ties; repeated clubs/season effects limit that assumption. Multiple tested variants add
selection uncertainty. The JSON includes intervals for all three scopes.

| Model | UCL match log-loss delta vs A [approx 95%] | Domestic delta [approx 95%] | R16 delta [approx 95%] |
|---|---|---|---|
| A | +0.000000 [+0.000000, +0.000000] | +0.000000 [+0.000000, +0.000000] | +0.000000 [+0.000000, +0.000000] |
| B | -0.001653 [-0.003903, +0.000596] | +0.000000 [+0.000000, +0.000000] | +0.001508 [-0.016816, +0.019831] |
| C | +0.001582 [+0.000732, +0.002432] | -0.001936 [-0.002637, -0.001234] | +0.000999 [-0.001949, +0.003947] |
| D | +0.000382 [+0.000175, +0.000588] | +0.000136 [+0.000072, +0.000199] | +0.001138 [+0.000358, +0.001919] |
| E | -0.001653 [-0.003903, +0.000596] | +0.000000 [+0.000000, +0.000000] | +0.001508 [-0.016816, +0.019831] |

B's small UCL match gain is not separated from zero by this interval and does not carry over to
R16 or bracket accuracy. C's domestic improvement is consistent across these seasons and worth
further investigation, but it sacrifices European match calibration. D marginally helps some
later-round probability scores while worsening UCL and domestic overall scores. No uniform
improvement across tasks or convincing cross-league knockout gain has been established.

## 4. Bayern and rankings

All historical cutoff top tens, Elo values and gaps to first place appear in
[cross-league-rankings.md](cross-league-rankings.md). Rankings use clubs observed in that season's
five supported domestic leagues before cutoff, not future rosters or dormant clubs. The full connected
rating pool still includes UCL opponents outside those leagues; this is not a complete all-UEFA ranking.

| Pre-R16 season | A: Bayern Elo (rank) | B | C | D | E |
|---|---|---|---|---|---|
| 2020/21 | 1806.81 (#1) | 1804.88 (#1) | 1798.38 (#1) | 1804.33 (#1) | 1804.88 (#1) |
| 2021/22 | 1797.67 (#1) | 1794.52 (#2) | 1788.74 (#1) | 1796.04 (#1) | 1794.52 (#2) |
| 2022/23 | 1782.12 (#1) | 1787.19 (#1) | 1773.76 (#1) | 1779.86 (#1) | 1787.19 (#1) |
| 2023/24 | 1739.54 (#4) | 1743.69 (#4) | 1731.51 (#4) | 1737.47 (#4) | 1743.69 (#4) |
| 2024/25 | 1743.33 (#5) | 1737.20 (#7) | 1734.75 (#5) | 1741.69 (#6) | 1737.20 (#7) |
| 2025/26 | 1817.09 (#1) | 1808.82 (#2) | 1808.49 (#1) | 1815.40 (#1) | 1808.82 (#2) |

A lower Bayern rating is not a success criterion. B moves Bayern down at some cutoffs but worsens
R16 and full-bracket accuracy. C and D also lower Bayern slightly without improving UCL log loss.
At other cutoffs B raises Bayern. These are consequences of shared rules and learned evidence,
not adjustments targeted at that club. Rank movement does not prove a better model.

## 5. Reproduction, tests and boundaries

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.cross_league \
  --output docs/cross-league-results.json
.venv/bin/pytest backend/tests -q
```

Only isolated research files were added: `backend/app/backtesting/cross_league.py`,
`backend/tests/test_cross_league.py`, the JSON results, this report and the ranking appendix.
The runner checks database SHA-256 before/after, saves the data hash and every tested configuration,
and uses no new dependency. Baseline/current-season modules, stored ratings, APIs and UI are unchanged.
No experiment is deployed, committed or pushed by this task.

The existing suite passed **182 tests** (one pre-existing AnyIO deprecation warning). Four focused
new tests cover strict-past regularized offsets, decay, bounded zero-sum margins, newcomer evidence
preservation, baseline parity, and future-result/membership leakage across variants. Ruff passes.
Saved baseline R16 probabilities were also compared exactly and the database checksum verified.
All five existing frontend navigation tests also passed; no frontend code was changed.

Limits include top-five-only domestic coverage, sparse UCL cross-league links and participant-selection
bias, no historical market valuations/lineups/injuries, incomplete neutral-venue metadata, retrospective
result corrections, fixed Davidson/extra-time/shootout assumptions, small knockout samples, and the
absence of a truly fresh historical test period. Training fit or a prettier ranking is insufficient
reason to change production. Keep A for Champions League forecasting; retain C as an undeployed
candidate for further domestic probability calibration research.
