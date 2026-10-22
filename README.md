# PitchRank

Current-season strength ratings for the Premier League, La Liga, Serie A, Bundesliga and Ligue 1, grounded in match results and squad market value.
A small FastAPI application, one SQLite database, and a React + TypeScript + Tailwind frontend.

The sidebar switches between five leagues (20 clubs in EPL, La Liga and Serie A; 18 in Bundesliga
and Ligue 1), showing their Elo ratings, W/D/L, goals, goal difference, squad values, and recent
form. Every club has a rating-history chart and match-by-match Elo changes. Light and dark mode,
search, sorting, and manual refresh work without an API account.

## Run the app

Requires Python 3.12+ and Node.js 22.12+. From this repository root:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e './backend[dev]'
alembic -c backend/alembic.ini upgrade head
pitchrank refresh --season 2026-2027
pitchrank refresh --league laliga --season 2026-2027
pitchrank refresh --league seriea --season 2026-2027
pitchrank refresh --league bundesliga --season 2026-2027
pitchrank refresh --league ligue1 --season 2026-2027
cd frontend
npm ci
npm run build
cd ..
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open [PitchRank locally](http://127.0.0.1:8000). FastAPI serves the built website, its assets, and the
API from the same origin. API documentation is at [localhost:8000/docs](http://127.0.0.1:8000/docs).
No frontend dev server is needed after a build.

If Python on macOS cannot locate its TLS certificates, point it at a trusted CA bundle:

```sh
SSL_CERT_FILE=/etc/ssl/cert.pem pitchrank refresh --season 2026-2027
SSL_CERT_FILE=/etc/ssl/cert.pem uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Certificate verification stays enabled. Use your platform's trusted bundle if that path is absent.

For frontend development, run the backend and, in a second terminal, `cd frontend && npm run dev`.
Vite proxies `/api` to the local backend. The production build supports direct team-page URLs.

## Only three steps

1. **Data collection.** Reuse the existing validated Pandas importer for current-season EPL and La Liga results.
   Import documented squad valuations into SQLite, recording source URL and valuation date.
2. **Elo calculation.** Seed ratings with a capped logarithmic market-value adjustment, then replay
   completed matches chronologically with the existing pure Elo match-update functions.
3. **Website.** Read the stored season snapshot through FastAPI and show the leaderboard and team
   pages in React. Refresh manually when you want new results.

## How the rating works

```
starting Elo = 1500 + clamp(60 × ln(squad value / shared reference), −100, +100)
expected home score = 1 / (1 + 10^((away Elo − home Elo − 65) / 400))
actual home score = 1 for a win, 0.5 for a draw, 0 for a loss
multiplier = max(1, ln(abs(home goals − away goals) + 1))
change = 20 × multiplier × (actual score − expected score)
home Elo += change
away Elo -= change
```

The shared reference is fixed at €556.425m (the existing EPL September 2026 snapshot median),
and stays unchanged across leagues and when more leagues are imported. Equal squad values receive
equal starting ratings. Cross-league comparisons remain squad-value anchored until cross-league
results are included; domestic results alone cannot calibrate relative league strength.

The prior gives equal relative spending differences equal influence, capped at 100 Elo in either
direction. Missing squad values use a clearly labelled neutral 1500 starting rating. Results after
that supply the evidence: an underdog win earns more than an expected win, and bigger winning margins
increase the update. Draws have a nonzero multiplier. Each match's two changes sum to zero.

W/D/L are represented by the actual result; goals for/against by goal margin; opponent strength by
the expected result. They are not awarded extra points again. Matches played measure evidence, not
an automatic bonus. Displayed figures are rounded; calculation and storage use full precision.
The app is a current strength estimate, not the official points table or a prediction service.

## Real data and sources

The preserved Premier League snapshot contains **70 completed 2026–27 matches**, **20 clubs**, and **20 squad
values**. Results run through **October 19, 2026**; valuation snapshot: **September 1, 2026**.

- [Football-Data](https://www.football-data.co.uk/englandm.php): original E0 match results. Downloads
  are retained in ignored `data/raw/`; successful imports retain source location and exact SHA-256.
- [Football Whispers](https://footballwhispers.com/blog/premier-league-squad-values-ranked/): the
  documented 20-club EUR squad table, which cites Transfermarkt. Direct Transfermarkt access returned
  403, so this secondary source is explicitly identified. The transcribed data is in
  `data/squads/2026-2027.csv`; each row retains its original valuation date and source URL.
- Club crests: Transfermarkt's public asset CDN. Source URLs are listed in `data/club-assets.json`;
  downloaded images are in `frontend/public/crests/`. Club marks belong to their respective owners.

Squad values are estimates and are a fixed snapshot, not live financial data. The September 1 snapshot
postdates the season's first matches; it is used to initialize a retrospective season replay, not
claimed to be information available before every historical match. No performance backtest claim
is made for these new ratings.

La Liga adds **89 completed matches through 21 October 2026**, all 20 officially verified clubs,
and 20 documented September squad values. The valuation publication/reference date is 6 September;
the source does not specify the exact underlying valuation day. See [La Liga data provenance](docs/laliga-data.md)
for roster verification, exact aliases, source URLs and limitations. Ratings are independent;
identical model parameters apply to every league.

Serie A adds **70 matches / 20 clubs**, Bundesliga **54 matches / 18 clubs**, and Ligue 1
**63 matches / 18 clubs**, with full September squad-value coverage. See
[five-league sources and verification](docs/five-leagues.md).

## Refresh or import files

Use the website's **Refresh data** button or:

```sh
pitchrank refresh --season 2026-2027
pitchrank refresh --league laliga --season 2026-2027
pitchrank refresh --season 2026-2027 --file path/to/E0.csv --squads path/to/values.csv
```

Squad CSV columns: `team,value_eur,as_of,source_url`, with ISO `YYYY-MM-DD` dates and positive EUR
values. Reviewed team aliases resolve to canonical IDs. Unknown clubs or invalid results fail with
row information. Use the existing file in `data/squads/` for the current season. To correct market
values, edit/import a documented CSV and refresh; only the selected league’s current-season calculation is replaced.

A refresh downloads before locking, then commits results, values, and recalculated ratings together.
Failures preserve the previous usable snapshot. Repeated imports do not duplicate matches/history.
Manual refresh is local and same-origin; no scheduler or API key is required.

## Small API

- `GET /api/league`: current-season table, data dates, and source metadata.
- `GET /api/teams/{id}`: team statistics, rating history, and completed results with Elo deltas.
- `POST /api/refresh`: download results and atomically refresh the current-season calculation.

Each endpoint accepts `?league=epl` (default), `laliga`, `seriea`, `bundesliga`, or `ligue1`;
other leagues are rejected.
Team links preserve the selection, and wrong-league team requests return 404.

Set `DATABASE_URL` to change the default `data/pitchrank.sqlite3`. Set `PITCHRANK_SEASON` to select a
season explicitly (otherwise it follows the Toronto calendar's July season boundary). Optional
`SQUAD_REFERENCE_EUR`, `SQUAD_LOG_SCALE` and `SQUAD_RATING_CAP` configure the market prior; recalculate all loaded leagues after changing them.
Settings come from environment variables; `.env.example` is documentation, not an automatic loader.

## Verify

```sh
pytest -q backend/tests/test_squads.py backend/tests/test_season.py backend/tests/test_api.py backend/tests/test_leagues.py
ruff check backend
ruff format --check backend
alembic -c backend/alembic.ini check
cd frontend
npm run lint
npm test
npm run build
```

Tests use temporary databases and clearly synthetic fixtures. No live provider is needed for tests.
To also run the preserved research tests, install `python -m pip install -e './backend[dev,analysis]'`
and run `pytest -q backend/tests`. Earlier backtesting/optimization modules are retained for
compatibility but are not imported or executed by the web application.

See [scope review](docs/mvp-scope-review.md) and [MVP verification](docs/mvp-verification.md).
The original phase documents describe historical work and are preserved as records; this three-step
MVP is the current scope. No predictions, ML, simulations, or additional infrastructure are planned.

Design skills: [installation and prior-use audit](docs/design-skills-audit.md).
Extension checks: [La Liga verification](docs/laliga-verification.md).
