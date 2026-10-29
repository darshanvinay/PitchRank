# Full Champions League knockout forecasts

## What was implemented

Model A now predicts all 15 knockout outcomes: eight R16 ties, four quarterfinals, two semifinals,
and one final. It returns both greedy and maximum-joint-probability complete brackets, with the
same pre-R16 Elo ratings frozen for the entire forecast. The historical endpoint covers
2020/21–2025/26. No Elo/Davidson parameters, historical data, schema, or dependencies changed.

The existing two-legged score enumerator handles home advantage, goal distributions, extra time,
penalties, and the historical away-goals rule. Away goals apply through 2020/21; subsequent seasons
use aggregate goals without away goals. The final uses a **single neutral match**, adding the existing
extra-time distribution and 50/50 shootout assumption only after a regulation draw. A scoring draw
in final extra time does not trigger away goals.

## Historical honesty: two explicit scenarios

1. **Fixed R16 order (`r16_order`, default):** sort the eight R16 tie IDs and pair adjacent winner
   slots into quarterfinals, then semifinals and the final. The left slot hosts the first leg.
   Later two-legged venues are assumed non-neutral. This is a reproducible hypothetical bracket;
   it does not read later fixture pairings, scores, or venue outcomes. It is not represented as
   the historical draw, and later-format draw restrictions have not been verified for this ordering.
2. **Recorded later draws (`observed_draw`):** later fixture participants map the R16 slots into
   the recorded bracket. First-leg home order and recorded venue flags are supplied as additional
   conditions. No later score is used to choose winners or calculate probabilities. However,
   the slot mapping uses later participants and pairings: this is a **retrospective conditional
   scenario**, not an unconditional prediction made before the R16 draw/date.

The database does not establish when each bracket, home-order decision, or venue change was known.
This implementation does not model draw uncertainty or assign draw probabilities. Even where a
later season has partially fixed paths, the available metadata does not certify pre-cutoff knowledge.
Every response states `conditional: true` and `unconditional_historical_forecast: false`.
The exact scenario tree and its hash are returned with the match-prefix and configuration hashes.

The results below score the **recorded-draw conditional scenario only**. There is no defensible
unconditional historical full-bracket accuracy from these results. The fixed-order scenario can be
forecast without later draws but is not scored against a different historical bracket.

## Measured results, 2020/21–2025/26

| Outcome | Own winners: greedy | Own winners: global | Actual participants, frozen Elo |
|---|---:|---:|---:|
| R16 advancements | 38/48 | 38/48 | 38/48 |
| Quarterfinal advancements | 15/24 | 15/24 | 17/24 |
| Semifinal advancements / finalists | 3/12 | 3/12 | 8/12 |
| Final winners / champions | 1/6 | 1/6 | 3/6 |
| Total advancement outcomes | 57/90 (63.33%) | 57/90 (63.33%) | 66/90 (73.33%) |
| Exact complete brackets | 0/6 (0%) | 0/6 (0%) | Not a propagated bracket |

**Own winners:** later matchups contain the model's own previous winners. A wrongly eliminated club
cannot re-enter. Each stage is scored by whether the winner of the corresponding recorded bracket
slot matches the real advancing club. Finalists are the two semifinal winners, so the 3/12 finalist
score is the same statistic as semifinal advancement, not an extra contribution to the 90 outcomes.

**Actual participants:** every round uses its actual clubs and pairings but still uses frozen pre-R16
ratings and pre-cutoff score calibration. This has future participant/draw information as a condition;
it measures matchup skill given the real participants. It is a separate conditional, round-by-round
evaluation and is never combined with the own-winners denominator. It does not represent a single
coherent tournament forecast made before the R16.

Greedy and global produced exactly the same complete bracket in each of these six recorded-draw
scenarios. Global optimization did not improve measured accuracy here. This is not an implementation
shortcut: a separate non-transitive probability test verifies the optimizer against all 32,768 possible
complete brackets and demonstrates a case where it beats greedy on joint probability.

### Season details (recorded-draw conditional scenario)

| Season | Predicted champion (both methods) | Actual champion | Own outcomes correct | Actual-participant outcomes correct | Complete-bracket probability |
|---|---|---|---:|---:|---:|
| 2020-2021 | Bayern Munich | Chelsea | 7/15 | 9/15 | 0.0274% |
| 2021-2022 | Bayern Munich | Real Madrid | 8/15 | 9/15 | 0.0728% |
| 2022-2023 | Bayern Munich | Man City | 9/15 | 12/15 | 0.0427% |
| 2023-2024 | Man City | Real Madrid | 9/15 | 12/15 | 0.0813% |
| 2024-2025 | Paris Saint-Germain | Paris Saint-Germain | 12/15 | 12/15 | 0.0314% |
| 2025-2026 | Bayern Munich | Paris Saint-Germain | 12/15 | 12/15 | 0.1017% |

The complete-bracket probability is the product of the 15 selected conditional advancement
probabilities. It is **not** the predicted champion's marginal title probability. The latter would
sum across all paths and is not implemented here. Small complete-bracket probabilities are expected
because every one of 15 outcomes must happen exactly as specified.

## Dynamic programming: mathematics and interview explanation

Greedy chooses the more likely winner at each tie and advances that club immediately. It does not
consider how that choice changes later opponents.

For each bracket node n and possible winner t, global optimization stores the best probability
of a complete subtree ending with t:

`V_n(t) = max over a in left, b in right, t in {a,b} [V_left(a) * V_right(b) * P_n(t | a,b)]`

At a team leaf, V(team)=1. The implementation adds logarithms instead of multiplying small numbers.
It also remembers the winning choice at each node, so it can reconstruct all 15 selections.
The final maximizes V over possible champions. Matchup probabilities depend on the supplied slot's
home/neutral rules and the two clubs' frozen ratings. An isolated global choice can have less than
50% probability if that full path has higher joint probability than the alternatives.

This works because, with frozen ratings and a fixed bracket, a later matchup depends on **which club
survived**, not on the earlier path it took. Once the best way for a club to win a subtree is known,
other paths ending with that same club cannot improve an otherwise identical later prediction.
Conditional independence of tie outcomes given the fixed ratings/scenario is a modeling assumption.

Interview version: “I broke the bracket into small sub-brackets. For each possible winner of a
sub-bracket, I saved its most likely complete path. Then I combined those saved possibilities at
the next round instead of recalculating every earlier path. Greedy asks who should win this tie;
my dynamic program asks which consistent set of all tournament outcomes is most probable.
I checked it against exhaustive enumeration, kept ratings frozen to prevent future-score leakage,
and labeled later-draw information as a condition instead of pretending it was known earlier.”

Maximum probability is a different objective from maximizing the number of correct picks or
maximizing a champion's marginal probability. An optimizer cannot guarantee greater observed accuracy.

## API, UI and reproduction

```text
GET /api/ucl/bracket?season=2020-2021&scenario=r16_order
GET /api/ucl/bracket?season=2020-2021&scenario=observed_draw
```

Both methods are returned in one response, with all 15 matchups, probabilities, champion, club Elo
ratings/crests, cutoff, rule settings, scenario tree/hash, and input/config hashes. Historical evaluation
labels are not needed or returned by the forecast endpoint.

The new sidebar entry opens `/champions-league/bracket`. Season, scenario, method and selected matchup
are URL state. Desktop has connected horizontal rounds; mobile stacks the rounds. Selecting a tie
opens a native keyboard-accessible dialog with its probabilities, Elo ratings and tie rules. The
existing neutral dark theme, Geist typography, crests, spacing and page shell are reused.

Run the backend comparison from the repository root:

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.tournament \
  --output docs/tournament-backtest-results.json
.venv/bin/pytest backend/tests -q
cd frontend
npm run build
npm run lint
npm test
```

`--seasons 2020-2021` restricts the backend report to the initial season. The backtester reads one
consistent SQLite snapshot per forecast; its CLI verifies the database SHA-256 before/after the run.
It writes only the requested report. Historical scores and production ratings are not recalculated
or persisted by this feature.

## Verification and limitations

- **178 backend tests passed**, including five focused tournament tests. Existing two-leg/away-goal
  tests remain intact. New tests cover round progression, duplicate/invalid tree rejection,
  reproducibility, a neutral single final, shootout labels, API validation, future-result isolation,
  ignoring later draws in the fixed scenario, and global optimization versus exhaustive enumeration.
- All **48 original R16 probabilities, selected winners, and input hashes matched exactly**.
- Frontend TypeScript/Vite build, ESLint and five existing navigation tests passed.
- The database checksum is unchanged. There are no new database tables, migrations or dependencies.
- This is six seasons and 90 correlated outcomes, not 90 independent tournaments. Only six champion
  predictions and six exact-bracket trials make those rates particularly uncertain.
- Metadata lacks publication-time draw/venue snapshots. Later pairing knowledge cannot be inferred
  from final results. An unconditional tournament backtest remains unavailable without such evidence
  or a valid draw-uncertainty model.
- Recorded neutral-venue flags may be incomplete, including historical relocations. The existing
  empirical score distribution, binomial extra-time approximation and 50/50 shootout assumption are
  retained. No lineups, injuries, changing in-tournament form or extra time updates enter frozen Elo.
- Source coverage excludes domestic results outside the five supported leagues. UCL-only clubs have
  less performance evidence. Retrospectively corrected results are not publication-time snapshots.

## Files changed in this feature

- Added `backend/app/backtesting/tournament.py` and `backend/tests/test_tournament.py`.
- Added the bracket endpoint to `backend/app/main.py`.
- Added `frontend/src/ChampionsBracket.tsx`; extended sidebar/screen selection in `App.tsx` and
  appended scoped bracket styles to `style.css`.
- Added this report and `docs/tournament-backtest-results.json`; documented the command in `README.md`.

TasteSkill's actual SKILL.md and app-screen guidance were consulted for component reuse, truthful
figures, one accent, readable data, and responsive inspection. web-design-guidelines SKILL.md and
its current upstream rules were read for semantic controls, labels, focus, loading/error states,
URL state, image dimensions, dark-mode controls, and responsive overflow. AwesomeDesign was not
found in the installed skill paths. No random design direction was applied: this is an extension
of an existing design system, not a redesign.

Responsive inspection at **1440, 768 and 390px** found no page horizontal overflow, low-contrast
text or console errors. A small-data-text warning was fixed by increasing matchup text to 13px
(14px on mobile). The remaining generic below-fold warning is intentional: showing every one of
15 ties at readable size requires vertical scrolling. The connected bracket is retained rather
than capping/hiding rounds. Browser checks verified both selection methods/scenarios, a matchup
dialog and Escape-to-close. The new page extends the installed design system without a redesign.

The accessibility review used the [current Web Interface Guidelines](https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md).
