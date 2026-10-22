# La Liga 2026/27 data and reuse

## Existing functionality reused

The Pandas CSV parser, alias resolver, SQLite transaction handling, immutable source observations, capped logarithmic squad prior, chronological Elo replay, season fingerprints, FastAPI endpoints and every leaderboard/team/chart/results component are reused. The Elo mathematics and defaults are unchanged: 1500 baseline, 65 home advantage, K=20, scale=400, logarithmic goal-margin multiplier; squad adjustment 60×ln(value/shared reference), capped at ±100.
The reference is now fixed at €556.425m across all leagues; see `docs/shared-elo-scale.md`.

The extension adds one league field (default `epl`) to teams, matches, import runs, squad values and current season ratings. Histories inherit competition from their match. Team IDs remain globally unique, so existing season/team and match identity uniqueness constraints remain valid. The additive migration preserves IDs, existing rows and rating fingerprints. Queries and replace operations scope by league/season; refresh is one atomic transaction. Legacy research remains EPL-only so Spanish matches cannot enter its historical replay. No duplicated engine, extra service or league application was added.

## Verified roster and results

- Official roster: https://www.laliga.com/en-GB/laliga-easports/clubs (explicitly titled 2026/27), checked 22 October 2026.
- Results: https://www.football-data.co.uk/mmz4281/2627/SP1.csv, 89 completed matches, 15 August–21 October 2026 when checked.
- `data/rosters/laliga-2026-2027.json` retains the sourced official names and reviewed exact provider aliases. This is a verified source snapshot, not an assumed list. The feed's home/away club set matches the official 20 exactly. Unverified La Liga seasons are rejected.
- Import enforces SP1, score/outcome consistency, canonical clubs, season bounds and duplicate identity. Local kickoff times use Europe/Madrid (Europe/London remains unchanged for EPL).
- No fuzzy matching: e.g. `La Coruna` → RC Deportivo, `Santander` → R. Racing Club and `Espanol` → RCD Espanyol de Barcelona are explicit mappings. Membership is checked again before replay.

## Squad valuation rule and limitation

Source: https://footballwhispers.com/blog/la-liga-squad-values-every-club-ranked/, published 6 September 2026, citing Transfermarkt September 2026. Direct Transfermarkt access returned HTTP 403. This is the same documented secondary-source approach as the existing Premier League data; no invented values or live values mixed into the fixed snapshot.

`data/squads/laliga-2026-2027.csv` retains 20 positive EUR totals and their source URL. **The source only dates the underlying valuations to September 2026.** `as_of=2026-09-06` is its publication/reference date, not a claim that every squad was valued on that exact day. This precision limitation is exposed in the API and Method page. EPL's existing 1 September snapshot is preserved; asserting that exact day for La Liga would invent unsupported precision. Both leagues use a fixed, sourced September snapshot, the same validation and the same capped shared-reference prior. Missing values retain the existing clearly identified neutral fallback.

Crests use the same Transfermarkt asset CDN as EPL. URLs are recorded in `data/club-assets.json`; club marks belong to their owners.

## Usage

```sh
.venv/bin/alembic -c backend/alembic.ini upgrade head
SSL_CERT_FILE=/etc/ssl/cert.pem .venv/bin/pitchrank refresh --league laliga --season 2026-2027
.venv/bin/pitchrank refresh --league epl --season 2026-2027
```

Existing commands and URLs default to EPL. Manual refresh downloads only the selected E0/SP1 feed. Squad values remain fixed unless their documented CSV is deliberately updated. API: `/api/league?league=laliga`, `/api/teams/{id}?league=laliga`, POST `/api/refresh?league=laliga`. Only `epl` and `laliga` are accepted. No automatic scheduler or new prediction/model features.
