# La Liga extension verification — 22 October 2026

## Automated checks

- Full backend suite: **122 passed** (original 109 plus 13 multi-league cases).
- Focused API and league rerun: **18 passed**.
- Frontend navigation tests: **4 passed**, using Node's built-in test runner; no new testing framework.
- `ruff check backend` and `ruff format --check backend`: pass.
- `alembic -c backend/alembic.ini upgrade head` applied the additive migration; `alembic ... check`: no new operations detected.
- `npm run lint`, `npm test`, `npm run build`: pass.
- One pre-existing upstream Starlette/AnyIO deprecation warning remains.

Focused coverage: additive migration retains existing IDs/data; wrong division/club/outcome rejected without mutation; Madrid kickoff conversion; idempotent imports; verified roster and positive sourced valuations; exact shared-engine update calculation; zero-sum updates and league-median priors; independent replacement of ratings/history; isolated staleness; wrong-league team API 404; refresh dispatch and rollback; unsupported leagues 422; legacy EPL model not invalidated by Spanish imports; deep links and filters preserve league identity. Tests use temporary databases and synthetic two-match fixtures, not live providers.

## Real-data checks

The existing SQLite database was backed up before migration. A serialized Premier League API snapshot (all clubs, results and histories) was saved separately. After migration, Spanish import/replay, and a successful **live website La Liga refresh**, the entire EPL snapshot still matches exactly, including ratings and calculation timestamps. EPL retains 70 matches, 20 clubs and 20 values, through 19 October.

La Liga has 89 completed matches, 20 clubs, 20 documented squad values and 178 history updates through 21 October. Every stored match's date, home/away official identity and score was compared with the downloaded SP1 CSV through the explicit alias mapping. Every club's played/W/D/L/GF/GA was independently recomputed from the CSV and compared with the API. Histories have played+1 points including the initial prior. Goals for/against and wins/losses reconcile. The 20 feed names and 20 valuation names exactly match the official roster snapshot. A contact sheet of all downloaded club crests was visually checked for correct mapping.

The valuation limitation is visible both on team profiles (publication reference, month-only underlying date) and on Method. See `docs/laliga-data.md` for sources and precision rules.

## Browser checks

Using the existing in-app browser:

- EPL default URL renders the preserved 70-match leaderboard.
- Sidebar selects La Liga and updates URL, breadcrumb, 20-club table, match total and source link.
- Barcelona profile shows Spanish opponents, nine matches, Elo history and deltas.
- Clicking Real Betis in Barcelona's results opens the correct Spanish club and retains `league=laliga`.
- Refresh while on a La Liga team disables the controls during the request, then announces successful La Liga recalculation and reloads that team's history.
- Switching leagues while on a team returns to the selected league's leaderboard; browser Back restores the prior Spanish team scope.
- Method and return links preserve La Liga, with Spanish results/valuation source links and the date-precision limitation.
- Search query is reflected in the URL alongside `league=laliga`; clearing it restores all 20 clubs.
- Reloading the La Liga deep link retains the selected league. Dark theme persists.

## Skills, visual inspection and review

See `docs/design-skills-audit.md` for installation paths, responsibilities, prior-use evidence and the corrected AwesomeDesign status. Reused Taste's existing direction `achromatic-ledger`, seed 1559896174; no redraw or identity changes. Applied its app-screen rules, Vercel's freshly fetched Web Interface Guidelines and the installed AwesomeDesign `clean` consistency/accessibility guidance. No sample data, decorative new panels, new color palette or new fonts.

TasteSkill's real-browser inspector ran at **1440, 768 and 390px**. Screenshot artifacts are local ignored verification output:

- `.taste-skill/laliga-round1/`: leaderboard, **0 FAIL**, 2 warnings (compact metadata and low colored-data area).
- `.taste-skill/epl-multileague-final/`: preserved EPL leaderboard, **0 FAIL**, same two warnings.
- `.taste-skill/laliga-team-final/`: longest club name, first pass **0 FAIL**, one edge warning.
- `.taste-skill/laliga-team-fixed/`: after fixing mobile statistic grid minimum widths and allowing labels to wrap, **0 FAIL, 0 WARN**.

Screenshots were actually opened and reviewed. The league selector matches the existing surface, border, radius, type and focus tokens. Mobile has a usable full-width workspace row. All 20 club crests remain identifiable. The long Espanyol title fits; the squad total now stays inside its panel. Table overflow remains inside the existing scroll frame, with the identity column pinned. Blue chart, neutral chrome and existing spacing are retained.

App-screen critique: the rated table answers club-strength comparison first; team history explains the accumulated movement; real crest identities and signed Elo deltas provide the product's signature. Shared edges, readable numeric alignment, coherent theme and honest source notes are retained. Design 7.5/10, usability 8/10, content 8/10. Intentional compromises: dense table headers/form codes/metadata stay 11–12px; all numeric columns require contained horizontal scrolling on phones; the existing overview/filters put the first full data row below Taste's preferred top-60%-of-phone target. A wholesale rearrangement to meet that last preference would conflict with the requested preservation of the current layout.

Current code review locations:

- `frontend/src/App.tsx:241` — labelled, named, keyboard-operable native competition select, URL-backed value and explicit dark colors.
- `frontend/src/App.tsx:189` — selected-league fetch cancellation; stale league data is not rendered under another league name.
- `frontend/src/navigation.ts:20` — team/results/Method/back URLs preserve scope; tested.
- `frontend/src/style.css:1495` — responsive workspace and 44px mobile controls; visible focus and reduced motion inherited from existing rules.
- `frontend/src/style.css:1540` — mobile statistic columns shrink safely, labels wrap, long squad totals fit.

No new accessibility blocker found in the changed controls. This is a code and browser review, not a claim of formal WCAG certification.
