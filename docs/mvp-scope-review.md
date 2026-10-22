# Scope review and reuse

This MVP replaces the original long roadmap. The active application has three steps: collect
current-season data, calculate Elo, and serve the connected website.

## Reused

- SQLite, SQLAlchemy, Alembic, canonical club IDs, and reviewed provider aliases.
- Pandas CSV validation, duplicate prevention, correction handling, and source observations.
- The existing pure expected-score formula, home advantage, draw treatment, goal-margin multiplier,
  and zero-sum match updates in `app/elo/engine.py`.
- The chronological grouping policy and transaction/rollback approach.
- All earlier research code, reports, migrations, and tests remain available.

## Simplified

- SciPy and Matplotlib are optional `analysis` dependencies, not application dependencies.
- The website has three endpoints: league, one team, and manual refresh.
- The current-season calculation stores one replaceable snapshot per club/season and its match
  history. It does not add research model versions, a model selector, or a prediction algorithm.
- Existing audit/version tables remain in place because deleting them would break old functionality
  and require destructive migrations without helping a user of the MVP.
- `pitchrank refresh` combines results import, squad import, and calculation in one transaction.
- There is no scheduled worker, queue, cache service, authentication platform, prediction screen,
  optimization dashboard, or extra deployment infrastructure.

## Necessary additions

`SquadValue` stores sourced EUR valuations by season. `SeasonRating` stores the initial/current
rating and input fingerprint. `SeasonHistory` stores each current-season match update. These direct
records avoid mixing squad-seeded current-season ratings with the original multi-season research
histories. The market prior is new because the original pure Elo engine did not include squad value.
The existing match-update mathematics is reused unchanged.

The new current-season replay uses only that season's results and supplied valuation snapshot.
No regression, relegation averaging, cross-season carryover, or fitting is needed in the MVP.
