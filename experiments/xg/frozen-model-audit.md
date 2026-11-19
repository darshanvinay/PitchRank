# Frozen xG model audit

The 43/48 exploratory result came entirely from the 33 ties with fresh xG for both clubs. Model A scored 25/33 there, the frozen ensemble 30/33 and the walk-forward selector 28/33. Every model scored 13/15 on fallbacks. The frozen ensemble had six corrections and one regression. The walk-forward run had the five corrections and two regressions discussed below. All 48 outcomes were previously examined.

## Targeted ablations

Each row changes one setting or isolates one component. The baseline and frozen ensemble reproduce the existing outputs. No settings were selected for deployment.

| Configuration | Correct / 48 | Brier | Log loss |
|---|---:|---:|---:|
| Model A | 38 | 0.1806 | 0.5441 |
| frozen | 43 | 0.1715 | 0.5254 |
| Elo leg only | 41 | 0.1698 | 0.5221 |
| attack and defence only | 40 | 0.1750 | 0.5326 |
| zero Elo xG share | 42 | 0.1707 | 0.5237 |
| half Elo xG share | 43 | 0.1722 | 0.5271 |
| K 20 | 39 | 0.1739 | 0.5301 |
| 25% offseason regression | 41 | 0.1747 | 0.5332 |
| attack learning rate .05 | 41 | 0.1722 | 0.5268 |
| goal prior 1.35 | 43 | 0.1715 | 0.5255 |
| home log effect zero | 43 | 0.1710 | 0.5244 |
| 50% baseline blend | 39 | 0.1755 | 0.5340 |

The frozen model averages a low-K Elo component and an opponent-adjusted attack/defence component. Elo uses a 25% xG-based outcome target on covered matches and actual results everywhere else. Attack/defence learns separate team strengths from observed xG. The ensemble does not use the recent-form feature. Restoring K=20 cost four picks and mixing in Model A at 50% also cost four. Restoring 25% offseason regression or halving the attack/defence learning rate cost two each. Removing Elo’s xG target cost one pick but slightly improved log loss. The isolated Elo component had better log loss than the ensemble. These are local sensitivities of a selected model and include interactions. In particular the regression setting affects both components.

## Changed ties

Probabilities refer to the first named club advancing. Elo and attack/defence refer to the two frozen ensemble components. Asterisks mark picks that changed versus Model A.

| Season | Tie | Advanced | A | Elo | Attack/defence | Frozen | Walk-forward |
|---|---|---|---:|---:|---:|---:|---:|
| 2020-2021 | Atalanta – Real Madrid | Real Madrid | 48.2% | 44.0% | 51.1% | 47.6% | 51.3%* |
| 2020-2021 | Sevilla FC – Borussia Dortmund | Borussia Dortmund | 56.0% | 48.1% | 49.6% | 48.8%* | 47.8%* |
| 2020-2021 | Atlético de Madrid – Chelsea | Chelsea | 59.9% | 55.7% | 43.6% | 49.7%* | 46.1%* |
| 2021-2022 | Atlético de Madrid – Man United | Atlético de Madrid | 48.4% | 51.9% | 61.7% | 56.8%* | 58.5%* |
| 2021-2022 | Paris Saint-Germain – Real Madrid | Real Madrid | 49.0% | 52.7% | 60.4% | 56.5%* | 61.5%* |
| 2022-2023 | Borussia Dortmund – Chelsea | Chelsea | 53.1% | 46.9% | 51.5% | 49.2%* | 51.8% |
| 2024-2025 | Bayern Munich – Bayer Leverkusen | Bayern Munich | 49.5% | 58.7% | 66.2% | 62.5%* | 64.3%* |
| 2024-2025 | Borussia Dortmund – LOSC | Borussia Dortmund | 45.4% | 52.6% | 53.7% | 53.2%* | 74.5%* |

Both ensemble components favored Dortmund over Sevilla, Atlético over United, Bayern over Leverkusen and Dortmund over Lille. The attack/defence component pulled Chelsea narrowly ahead against Atlético, with Atlético finishing at 49.68%. The Elo component pulled Chelsea ahead against Dortmund despite the attack/defence component leaning the other way. The walk-forward selector kept Dortmund for that tie. Both components overfavored PSG against Real Madrid. Attack/defence also favored Atalanta against Real Madrid, which the walk-forward selector picked, while Elo kept Real Madrid ahead in the frozen ensemble.

## Coverage recovery

All 15 fallbacks involved clubs with zero observations. Three ties lacked data for both clubs. Porto and Benfica each appeared in three fallbacks. Sporting CP, Club Brugge and PSV each appeared in two. No fallback was caused solely by a stale observation in a covered league. The baseline already gets 13/15 correct, so evaluate Brier and log loss alongside accuracy when coverage expands.

Joining the missing clubs to existing pre-cutoff UCL match records gives a coverage ceiling of 13/15 if every matching UCL result had usable xG. This is a fixture availability count, not confirmed xG availability or an accuracy projection. The two remaining ties are Club Brugge–Benfica (2022-2023), Inter–Porto (2022-2023).

Pannadata documents Opta UCL fixture and shot data from 2013 onwards. Check fixture-level coverage, original provider provenance and usage terms before an isolated import. StatsBomb Open Data covers selected matches and is useful for validating event aggregation, with no confirmed full coverage of these missing fixtures. xGTables lists Sportmonks UCL for 2026/27, which is an option for prospective coverage. Keep provider-specific xG separate and validate overlap before combining scales.

- [Pannadata coverage](https://github.com/peteowen1/pannadata)
- [Hudl StatsBomb Open Data](https://github.com/hudl/open-data)
- [xGTables source and coverage notes](https://www.xgtables.io/data/)

## Prospective tracking

The separate SQLite ledger stores Model A, the frozen ensemble and the recent-form configuration selected in the final two historical folds. Capture takes two reviewed scheduled knockout match IDs with reverse home/away orientation. Run before the first leg, ideally using the same capture date across all round ties. The cutoff excludes the full UTC capture date. Fixture IDs, recorded kickoffs, probabilities, configuration and input hashes are saved. Duplicate records and edits through the ledger are rejected. Evaluation waits for both final legs and reviewed extra-time or shootout data when needed. A changed fixture ID is reported as unresolved and needs review. The ledger is local evidence and relies on the host clock and fixture feed.

```sh
PYTHONPATH=backend .venv/bin/python -m app.backtesting.prospective capture FIRST_MATCH_ID SECOND_MATCH_ID
PYTHONPATH=backend .venv/bin/python -m app.backtesting.prospective evaluate
```

This is a manual capture workflow. The live database has no named scheduled knockout pairs as of November 18, so the live ledger contains zero forecasts. The historical replay parity check and a separate capture/settlement test exercised the tracker. No historical match was inserted into the prospective ledger.

## Three priorities

1. Run the frozen shadow comparison for the next published knockout draw. Judge Brier and log loss on paired ties and track coverage alongside accuracy.
2. Verify match-level historical UCL xG first, then seek domestic coverage for the remaining missing clubs. Audit fixture identity, provider scale and pre-cutoff availability before changing the fallback gate.
3. Prioritize the low-K Elo and attack/defence components as fixed comparisons in the next research cycle. The K sensitivity and the Elo-only log loss justify checking those components separately before adding more recent-form parameters.
