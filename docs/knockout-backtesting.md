# Historical Champions League Round-of-16 backtesting

Backend only: reuse existing historical Elo, Davidson probabilities, SQLite match/tie metadata
and evaluation metrics. No Elo formula changes, database writes, frontend work, Monte Carlo,
bracket simulation, optimization or trained new rating model.

## Implementation

- `backend/app/backtesting/knockout.py`: validate eight two-legged ties, freeze pre-round Elo,
  fit a pre-cutoff score adapter, exactly enumerate advancement and evaluate actual winners.
- `backend/app/ingestion/cli.py`: `knockout-backtest` with selected seasons/config/report output.
- `backend/tests/test_knockout.py`: six focused rule, probability, metric and leakage tests.
- `docs/knockout-backtest-results.json`: measured six-season, per-tie reproducible report.

```sh
cd /Users/darshan/Documents/PitchRank/PitchRank
.venv/bin/pitchrank knockout-backtest --seasons 2020-2021
.venv/bin/pitchrank knockout-backtest --seasons 2020-2021 2021-2022 2022-2023 2023-2024 2024-2025 2025-2026 --output /tmp/knockout-report.json
```

Backend functions: `backtest_round_of_16(engine, season, config, draw_strength)` and
`backtest_seasons(engine, seasons, config, draw_strength)`. Optional `--config` uses the same
SeasonConfig JSON as historical Elo; `--draw-strength` defaults to the existing Davidson 0.7.
No parameter is optimized on these evaluated ties. Freeze any tuned parameters using earlier
training/validation periods before evaluating held-out seasons.

## Prediction construction and leakage protection

Each season's cutoff is the earliest R16 first-leg date. All matches ON that date and later are
excluded from both historical Elo reconstruction and score-distribution fitting. Ratings are
frozen for BOTH legs, including ties starting a week later; there are no between-leg updates.

Pairing, nominal home order and match dates come from stored bracket metadata; actual scores
are only used in the later evaluation phase. Forecast functions receive an immutable TieFixture
containing club IDs and neutral flags, not Match objects or observed goals. All forecasts are
computed before actual-winner resolution. A read-only database transaction keeps the source
snapshot consistent. The report includes cutoff, input/config hashes, parameters, counts,
frozen ratings, both advancement probabilities, predicted and actual winners.

The reused Davidson model supplies P(home win, draw, away win). This cannot by itself determine
aggregate goals or away-goals tiebreakers. The necessary score adapter estimates
P(home goals, away goals | H/D/A) from finished domestic/UCL matches strictly before the cutoff,
then multiplies each conditional distribution by the existing Davidson outcome probability.
Its score PMF therefore sums to one and preserves the existing W/D/L marginals exactly.
Neutral venues remove home advantage and symmetrize the fitted winning-score shape.

Both regulation-time legs are enumerated exhaustively over the empirical score support, without
sampling, arbitrary goal truncation or Monte Carlo error. This assumes independent legs at the
frozen Elo strengths; tactical dependence on the first-leg score is not modeled.

If aggregate/away goals require extra time, thin each modeled 90-minute goal count independently
with binomial probability 1/3 to approximate 30 minutes. This is a fixed approximation, not a
trained or validated extra-time model. Use nominal second-leg home advantage (zero if neutral).
Unresolved ties go to a 50/50 shootout prior; no invented player-level penalty ability.

## Historical rules and actual labels

Team A is first-leg home/second-leg away; B has the reversed home order. Resolve total aggregate
first, then away goals through 2020/21. If still tied, play extra time. Under the old rule, a
scoring extra-time draw advances away A; a scoreless extra-time draw requires penalties.
From 2021/22 there are no away-goal tiebreakers, including in extra time.

Rules verified against UEFA:
https://www.uefa.com/news/027d-17172d2190e2-03070c1a3001-1000--does-the-away-goals-rule-still-apply/
and the 2021 abolition notice. Actual advancement uses stored 90-minute scores plus separate
full after-extra-time and penalty scores. The resolver subtracts the second-leg regulation
score to recover goals added in extra time. Missing/inconsistent tie data causes an error,
not a fabricated advancing club. Require exactly 16 clubs, 16 matches, eight ties and two
chronologically ordered reversed-home legs. Duplicate requested seasons are rejected.

## Measured results

Accuracy = correct advancing-club picks / evaluated ties. Brier is the conventional binary
mean `(p_A - y_A)^2`, range 0–1. Existing multiclass Brier sums both complementary class errors,
so divide that result by two. Log loss is the mean negative natural log of the actual winner's
predicted probability. A probability tie deterministically picks first-leg home A.

| Season | Correct / ties | Accuracy | Binary Brier | Log loss |
| --- | ---: | ---: | ---: | ---: |
| 2020-2021 | 5/8 | 62.50% | 0.245292 | 0.679946 |
| 2021-2022 | 5/8 | 62.50% | 0.217178 | 0.614570 |
| 2022-2023 | 7/8 | 87.50% | 0.171201 | 0.529590 |
| 2023-2024 | 7/8 | 87.50% | 0.141205 | 0.460051 |
| 2024-2025 | 6/8 | 75.00% | 0.181529 | 0.546941 |
| 2025-2026 | 8/8 | 100.00% | 0.126985 | 0.433624 |

Overall: **38/48 correct (79.1667%)**, binary Brier **0.180565**, log loss **0.544120**.
The 2020/21 cutoff is 16 February 2021; 20,489 earlier results end on 15 February. All eight ties
were evaluated with no skipped labels.

| 2020/21 first-leg home A | First-leg away B | A advances | Predicted | Actual |
| --- | --- | ---: | --- | --- |
| Lazio | Bayern Munich | 28.32% | Bayern Munich | Bayern Munich |
| Borussia Mönchengladbach | Man City | 27.68% | Man City | Man City |
| Atalanta | Real Madrid | 48.18% | Real Madrid | Real Madrid |
| Sevilla FC | Borussia Dortmund | 56.01% | Sevilla FC | Borussia Dortmund |
| FC Barcelona | Paris Saint-Germain | 49.58% | Paris Saint-Germain | Paris Saint-Germain |
| Atlético de Madrid | Chelsea | 59.88% | Atlético de Madrid | Chelsea |
| Porto | Juventus | 36.15% | Juventus | Porto |
| RB Leipzig | Liverpool | 49.77% | Liverpool | Liverpool |

## Tests, preservation and limitations

170 backend tests pass, including six new focused tests. Tests demonstrate old/new away-goals
rules, extra-time scoring draws, penalties, missing tie data, score mass/marginal preservation,
neutral symmetry, binary metric conventions and duplicate/incomplete tie rejection. Changing a
future R16 result changes labels/metrics but not any frozen prediction, Elo, calibration count
or input/config hash; adding a high-scoring future domestic match also changes no prediction.

The backend only reads the database and writes an optional report file. No current-season
ratings, matches or historical ratings are updated. No frontend or schema changes are needed.

Limitations:
- Only Round-of-16 advancement is evaluated, not complete knockout brackets.
- Forty-eight ties is a small sample; the six-season result is a descriptive default-parameter
  benchmark, not proof of out-of-sample superiority or calibrated advancement probabilities.
- Score distributions are conditional empirical shapes, with zero support for scorelines never
  observed in the pre-cutoff sample. Extra time uses a 1/3 approximation; shootouts use 50/50.
- Freeze both legs before R16; injuries, lineups, form updates, first-leg tactics and later
  changes in strength are absent. No market odds or future squad valuations are used.
- Stored neutral-venue metadata is incomplete, especially COVID relocations. Nominal home
  advantage may therefore be inaccurate. Pairing/venue metadata is assumed known; there is no
  archived schedule-publication feed proving when a later relocation became known.
- Outside-five opponents have UCL-only domestic coverage gaps; initial priors and regression
  remain assumptions. Archived result corrections are not publication-time vintage records.
- Historical R16 pairings are treated as known pre-round fixtures, rather than predicting draws.
- Football-Data source reuse restrictions still apply; no paid source has been introduced.
