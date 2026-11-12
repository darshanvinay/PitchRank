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

