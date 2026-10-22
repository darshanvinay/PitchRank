# Five-league extension — 22 October 2026

## Minimal implementation

Extended the existing league registry, roster files, ingestion mappings and selector. Added `club_count` to the existing Competition configuration (20 by default, 18 for Bundesliga/Ligue 1); the existing roster/replay/API completeness checks use it. No engine mathematics, parameters, shared reference, dependencies, database schema/tables, API endpoints or page components were added or changed. The current fixed €556.425m squad-value reference continues across every league, with the existing cross-league comparison limitation documented in `shared-elo-scale.md`.

Files changed:

- `backend/app/core/leagues.py`: three competition entries, accepted league IDs, club counts and provenance notes.
- `backend/app/ingestion/teams.py`: reuse sourced roster seeding for every non-EPL league; validate configured count.
- `backend/app/services/season.py`, `backend/app/api/data.py`: configured roster/rating count instead of a hardcoded 20.
- `backend/app/main.py`: application description covers European clubs; same three endpoints.
- `frontend/src/navigation.ts`, `frontend/src/App.tsx`: five URL-backed options; existing links/pages/refresh reuse the selected ID. New monthly valuation snapshots use the same publication-date label/disclosure as La Liga.
- `frontend/index.html`: accurate five-league page description.
- `data/rosters/{seriea,bundesliga,ligue1}-2026-2027.json`: verified roster snapshots and explicit provider-name mappings.
- `data/squads/{seriea,bundesliga,ligue1}-2026-2027.csv`: sourced positive EUR totals, publication reference dates and URLs.
- `data/club-assets.json` and 56 files in `frontend/public/crests/`: existing CDN approach; all crest mappings visually checked.
- `backend/tests/test_leagues.py`, `frontend/tests/navigation.test.mjs`: focused extension tests.
- `README.md` and this verification/source record.

No stylesheet changes or redesign. Existing canonical IDs, matches, valuations, ratings and histories remain intact. Existing EPL historical/research paths stay EPL-only.

## Verified sources and import totals

| League | Clubs | Completed matches | Results through | Squad values | Valuation publication/reference date |
| --- | ---: | ---: | --- | ---: | --- |
| Premier League (preserved) | 20 | 70 | 2026-10-19 | 20 | 2026-09-01 (existing snapshot) |
| La Liga (preserved) | 20 | 89 | 2026-10-21 | 20 | 2026-09-06 |
| Serie A | 20 | 70 | 2026-10-19 | 20 | 2026-09-07 |
| Bundesliga | 18 | 54 | 2026-10-18 | 18 | 2026-09-04 |
| Ligue 1 | 18 | 63 | 2026-10-18 | 18 | 2026-09-04 |

Results use the same Football-Data provider and Pandas pipeline: https://www.football-data.co.uk/mmz4281/2627/I1.csv, https://www.football-data.co.uk/mmz4281/2627/D1.csv and https://www.football-data.co.uk/mmz4281/2627/F1.csv. Successful live refreshes retain source URL and payload SHA-256 in the existing import audit.

Official roster checks:

- Serie A: https://www.legaseriea.it/serie-a — the 2026/27 club section matches all 20 feed clubs, including Venezia, Frosinone and Monza. The league's statistics route was intermittently unavailable; the official competition home lists the full roster.
- Bundesliga: https://www.bundesliga.com/en/bundesliga/clubs — explicitly 2026–2027, 18 clubs including Schalke, Elversberg and Paderborn.
- Ligue 1: https://ligue1.com/fr/articles/l1_article_5293-les-dates-de-reprise-des-clubs-de-l1-2627 — official 2026/27 list of all 18 clubs, including Le Mans and Troyes. The generic clubs route was unavailable, so this complete official season-specific list was used.

Squad totals use the same documented Football Whispers secondary source citing Transfermarkt, fixed to the September publication snapshot:

- Serie A: https://footballwhispers.com/blog/serie-a-squad-values-every-club-ranked/
- Bundesliga: https://footballwhispers.com/blog/bundesliga-squad-values-every-club-ranked/
- Ligue 1: https://footballwhispers.com/blog/ligue-1-squad-values-every-club-ranked/

**No missing clubs, match feeds, crests or squad valuations.** The source does not provide an exact underlying valuation day. The CSV `as_of` date is explicitly the source publication/reference date, not invented daily precision. This is disclosed in league metadata, Method and team profiles. Fixed documented values are reused on refresh; they are not silently replaced with live Transfermarkt totals. No league-wide headline value is used as a statistic or model input.

## Checks

The 187 newly imported match identities, dates, opponents and scores were compared with the three raw provider feeds. All 56 clubs' played, W/D/L, goals for/against, goal difference and histories were independently reconciled to those rows. Feed club sets, roster mappings and valuation-file club sets match exactly. Histories contain one initial point plus one update per appearance. Per-match Elo deltas remain zero-sum.

The existing database was backed up before extension. Complete serialized API snapshots for EPL and La Liga matched exactly after importing the new leagues, including calculation timestamps and all histories/results. Live refreshes were then exercised for each new league and the old snapshots checked again.

Automated results: **131 backend tests passed**, **5 frontend navigation tests passed**; Ruff lint/format, ESLint, TypeScript/Vite build and Alembic schema check pass. Alembic reports no new migration operations. The existing upstream Starlette/AnyIO deprecation warning remains. New focused cases cover all five club counts and API team/history isolation; selected-league refresh/correction/idempotence without altering the other four; exact alias mapping, positive sourced values, continental kickoff conversion, wrong-league club rejection/rollback and rejection of unverified seasons. Navigation tests cover team/Method/back/filter URLs for all five and reject unsupported IDs.

## Design skills actually read and applied

- TasteSkill: `/Users/darshan/.codex/plugins/cache/taste-skill/taste-skill/2.1.4/skills/taste-skill/SKILL.md` and its `references/app-screens.md` guidance. Retained existing direction `achromatic-ledger`, seed 1559896174; no new draw because this is an extension of the existing interface. The screen still asks which clubs are strongest in the selected competition; real crests, Elo marks and match histories remain the signature elements. No sample data.
- web-design-guidelines: `/Users/darshan/.agents/skills/web-design-guidelines/SKILL.md`, plus fresh https://raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md. Reviewed labelled native selector, named controls, focus, URL state, dark native option colors, loading/disabled/error feedback, semantic navigation, contained responsive table scrolling and touch targets. Existing accessibility patterns are reused.
- AwesomeDesign collection: `/Users/darshan/.agents/skills/clean/SKILL.md`, installed from `bergside/awesome-design-skills`. Applied semantic tokens, explicit states, consistency, keyboard access and 44px mobile control guidance. Its illustrative alternate fonts/palette were not substituted for the user's existing Geist/dark identity.

TasteSkill real-browser inspections at **1440, 768 and 390px**: `.taste-skill/five-seriea/`, `five-bundesliga/`, `five-ligue1/` each report **0 FAIL**, with the existing compact-metadata and low-data-hue warnings retained intentionally. Screenshots at all three widths were opened and reviewed. There is no page-wide horizontal overflow; the table retains its existing contained scroll. Headers, crests and club/rating rows align with the existing layout. Long club names wrap within their identity column. The original overview-first phone layout and 11–12px table metadata are unchanged compromises, not new accessibility claims.

Browser checks cover five selector choices, new-league club totals, team profiles/history/results, league-preserving navigation and search/sort URLs, and successful live selected-league refreshes with correct status announcements. Existing EPL and La Liga remain selectable and unchanged.

Additional team-screen inspection: `.taste-skill/five-team/` tests Borussia Mönchengladbach (the longest new club name) at all three widths: **0 FAIL**, one compact-text warning. All screenshots were opened; the title, crest, statistic grid, chart axes and squad total fit without CSS changes. App-screen critique: the strength table remains primary, country/competition context is visible, numeric columns align, and the selected league's real crests and Elo movement supply the product identity. Design 7.5/10, usability 8/10, content 8/10; the previously documented compact-metadata/phone table-scroll compromises remain.

Taste source lint reports **0 FAIL** and existing warnings for scope labels and Method's 01/02/03 step markers. These existing explanatory patterns were retained to preserve the interface. Web Interface Guidelines review of changed files: `frontend/src/App.tsx:255` uses native, labelled, keyboard-operable options generated from the existing competition list; `frontend/src/navigation.ts` keeps selection in every route/filter URL. No new changed-control accessibility blocker found; this is not a formal WCAG certification.
