# MVP verification — October 22, 2026

The current scope is complete in three steps. The application runs locally at
`http://127.0.0.1:8000/`; the built frontend is served by FastAPI from the same origin.

## Step 1 — Data collection

Reused the existing canonical club identities, SQLite session setup, Alembic migrations, and validated
Pandas match importer. Added a direct squad-value table and importer with source URL and valuation date.

Verified **70 real completed matches**, **20 current-season EPL clubs**, and **20 sourced squad values**
for 2026-2027. Results run through **October 19, 2026**. Values are the **September 1, 2026** snapshot
published by Football Whispers, explicitly citing Transfermarkt. Direct Transfermarkt access returned
403, so this secondary source is documented rather than represented as a direct provider integration.

Squad data is retained in `data/squads/2026-2027.csv`. Original results are retained in ignored
`data/raw/E0-2026-2027.csv`, with successful import hashes and locations in SQLite. Club crests and
source URLs are retained in `frontend/public/crests/` and `data/club-assets.json`.

**32 ingestion tests passed** before proceeding to Step 2: the existing 22 ingestion/database cases
plus 10 focused squad/current-season import cases. They cover validation, explicit aliases, duplicate
prevention, corrections, provenance, and rollback. Invalid or unknown market values are rejected.

## Step 2 — Elo calculation

Reused the existing pure expected-score and zero-sum update functions. Added one current-season replay
with market-adjusted starting ratings, rather than extending the research model registry.

```
initial = 1500 + clamp(60 * ln(value / league median), -100, +100)
expected_home = 1 / (1 + 10 ** ((away - home - 65) / 400))
actual = 1 (home win), 0.5 (draw), or 0 (home loss)
multiplier = max(1, ln(abs(home_goals - away_goals) + 1))
delta = 20 * multiplier * (actual - expected_home)
```

Only completed matches from the selected season are replayed. Draws have a nonzero multiplier.
Underdog wins earn larger rewards than expected wins. W/D/L, goals, and opponent strength enter once
through the actual score, goal margin, and expected score. Playing a match is not an automatic bonus.
Missing valuations are null in the API and shown as unavailable; those clubs start at neutral 1500.

The calculation stores **20 season ratings and 140 history rows**. Repeated refresh replaces that
snapshot without duplicates. A storage failure rolls back imported match corrections, values, and
ratings together. Older research histories and the single existing research model record remain
preserved; this MVP does not create additional research versions.

**Six focused Elo/current-season tests passed** before proceeding to Step 3. They cover logarithmic
and capped priors, currency scale invariance, neutral fallbacks, sequential updates, underdog rewards,
zero-sum totals, repeat refresh, corrected results, and full transaction rollback.

## Step 3 — Connected website

The API has three application endpoints:

- `GET /api/league`: all 20 clubs, Elo ratings, season statistics, market values, and data metadata.
- `GET /api/teams/{id}`: one club, complete rating history, and season results with Elo changes.
- `POST /api/refresh`: manual download/import/recalculation with a single refresh lock.

The React + TypeScript + Tailwind frontend provides the leaderboard, search, URL-backed sorting,
club profiles, Recharts history, a readable history table, match results, methodology/source details,
responsive navigation, light/dark mode, loading/error/empty states, and manual refresh feedback.
The graph bundle loads only when a team page needs it.

## Checks actually performed

- Full preserved/new backend suite: **109 tests passed** (88 earlier cases plus 21 MVP cases).
- Ruff lint and formatting: **passed; 40 Python files formatted**.
- Alembic migration upgrade and schema comparison: **passed; no pending metadata changes**.
- SQLite integrity and foreign-key checks: **passed**.
- Dependency consistency: **no broken requirements**.
- TypeScript and Vite production build: **passed**.
- ESLint: **passed**.
- All 20 real team-detail API responses, final history ratings, result counts, and local crest assets:
  **passed**.
- League totals reconcile: 140 team appearances for 70 matches, goals for equal goals against,
  total wins equal total losses, and each club's W+D+L equals appearances.
- Browser interactions: club search, squad-value sorting, team navigation, expandable history values,
  light/dark toggle, and a successful real-provider manual refresh **verified**.
- API tests cover stale-data rejection, unknown clubs, provider-failure preservation, and same-origin
  refresh restrictions. No prediction API is exposed.

The full test suite reports one upstream Starlette/AnyIO deprecation warning from the test client.
No failing test was skipped. GitHub Actions has not run remotely; tests were run locally on Python
3.13. The initial frontend build failed because a stylesheet write used the wrong directory; that
was corrected and production builds/lint then passed. A temporary formatter's registry request also
failed in the restricted environment; the already installed formatter was used locally afterward.

## Design verification

Applied the installed Taste Skill app-screen workflow and Web Design Guidelines. The selected
achromatic-ledger direction uses a custom pitch-inspired mark, real club crests, neutral chrome,
blue rating marks/history, and restrained signed-change colors. No separate Awesome Design MD skill
was installed; the available design-style collection remains available.

Taste Skill checks covered the leaderboard at **1440, 768, and 390px**, and the team page at
**1440 and 390px**. Screenshots and measurements are in ignored `.taste-skill/leaderboard-final/`
and `.taste-skill/team-final/`. Both final inspections report **0 FAIL**. Fonts are self-hosted
Geist and were detected correctly. Remaining non-blocking warnings concern compact metadata/form
labels, the intentionally small share of colored data marks, and one mobile squad-value label
12px from the phone edge; no requested statistic is clipped or omitted.

Small text flagged in the first pass was raised to at least 11px, with the core table data at
13–14px. Metadata, form codes, and axis labels remain 11–12px. The inspector's low-data-hue warning
on the leaderboard is intentional: thin blue rating marks are used rather than large color panels.
The substantial blue history series appears on the team page.

Recharts appends an aria-hidden measurement span at `top: -20000px; left: 0`, outside the visible
chart. Taste Skill initially reported that span as an edge collision. Setting its visibility to
hidden preserves text measurement dimensions and excludes it from visible-content analysis. The
actual chart ticks were already within the page margins; no axis data was removed or moved offscreen.

Web Design Guidelines review covered semantic links/buttons/tables, named inputs/selects, decorative
icon hiding, visible focus, skip navigation, status announcements, date/number localization, reduced
motion, explicit crest dimensions, dark native controls, and URL-backed filters. The dense statistics
table scrolls inside its frame on mobile with the club column pinned; the whole page does not scroll
horizontally. The history graph has a textual label and an expandable table of values.

Visual critique, app-screen criteria: the club objects and rated table lead the screen; shared edges
and restrained color keep the data readable. The mobile view preserves all requested statistics
through contained table scrolling. Scores: design 7.5, usability 8, creativity 6.5, content 8;
overall 7.5. Remaining compromise: viewing all numeric columns on a narrow phone requires horizontal
scrolling. Marketing-page photography/motion requirements do not apply to this working app screen.

## Reproduce

See the root README for installation and one-server startup. Main verification commands:

```sh
source .venv/bin/activate
pytest -q backend/tests/test_squads.py backend/tests/test_season.py backend/tests/test_api.py
ruff check backend
ruff format --check backend
alembic -c backend/alembic.ini check
cd frontend
npm run lint
npm run build
```

The research suite additionally needs the optional `analysis` dependency group. The app never
imports its optimization, prediction-probability, or backtesting modules. The three-step MVP replaces
the original phase roadmap; no additional phases or infrastructure are required to use it.
