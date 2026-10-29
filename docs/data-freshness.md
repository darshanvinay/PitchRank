# Data freshness repair — 28 October 2026

## Diagnosis before changes

The database held 89 La Liga matches through 21 October; a fresh request to the existing
Football-Data `https://www.football-data.co.uk/mmz4281/2627/SP1.csv` feed returned 99 completed
matches through 26 October. All five current CSVs had newer results (provider Last-Modified:
26 October). This was not a season selection error: the app and provider both used 2026/27.

Refresh was manual; selecting Premier League and refreshing did not download La Liga. There is
no background updater. Current-season refresh already downloaded the current CSV rather than
reusing the historic cache, and already upserted scores and replayed the connected Elo pool.
Historical cached seasons remain intentionally reusable. No evidence showed a provider omission
in the freshly fetched current-season feeds.

Two metadata bugs obscured the lag: `results_through` used the latest match across every league
and UCL instead of the selected domestic league; `refreshed_at` was a global rating calculation
time, not a successful import time. Browser responses also lacked an explicit no-store policy.

A live browser refresh exposed a further download failure: this macOS python.org installation's
OpenSSL CA file was absent. Without an SSL_CERT_FILE override, HTTPS failed with
`CERTIFICATE_VERIFY_FAILED: unable to get local issuer certificate`. The terminal's explicit
`/etc/ssl/cert.pem` override succeeded. Both download adapters now automatically use that trusted
system bundle on macOS only when Python's default bundle is missing and neither SSL_CERT_FILE
nor SSL_CERT_DIR is explicitly configured. Certificate/hostname verification stays enabled.
A browser refresh without environment overrides was subsequently successful.

## Changes

- `backend/app/ingestion/historical.py`: force provider revalidation; verified TLS context;
  skip unplayed/postponed/cancelled/abandoned rows, reject partial or future completed scores;
  stable domestic identity `(competition, season, home, away)` across date corrections; reject
  ambiguous duplicate pairings; keep the existing database uniqueness constraint and match IDs;
  detect missing previously completed matches in a full provider snapshot before committing;
  report inserted/updated/unchanged/skipped counts. UCL retains date-based identities because
  pairings can recur in the same tournament season. No migration or table was added.
- `backend/app/ingestion/champions.py`: reuse trusted TLS context and complete-snapshot checks.
- `backend/app/services/season.py`: validate downloaded complete snapshots, retain atomic
  transaction and existing chronological replay, report every competition/season import instead
  of only the last domestic import. Local `--file` inputs may still contain incremental deltas.
- `backend/app/api/data.py`, `api/schemas.py`: domestic latest completed date and league-specific
  `last_synced_at` from committed ImportRun records. Global Elo `refreshed_at` is retained for
  profile recalculation/invalidation. Another league's replay cannot advance this sync timestamp.
- `backend/app/main.py`: no-store API response headers.
- `backend/app/ingestion/cli.py`: refresh defaults to all five leagues plus UCL (`europe`), explicit
  single-league option retained; status adds latest result/sync timestamps and league/season filters.
- `frontend/src/App.tsx`, `types.ts`, `style.css`: show Latest match and Last updated on desktop,
  tablet and phone; render sync time in browser locale/timezone; bypass API caches and revalidate
  on window focus so a terminal refresh appears on returning to the app.
- `backend/tests/test_freshness.py`: essential ingestion, chronology, correction, missing-feed,
  sync isolation/rollback, HTTP cache and TLS fallback regression tests.
- `README.md` and this document: operational commands and verification.

The database was backed up with SQLite backup to `/tmp/pitchrank-before-freshness.sqlite3` before
changes. No existing match/database was reset or deleted. Only derived rating snapshots/history
are atomically rebuilt using the existing pipeline. Elo formulas and parameters are unchanged.
The raw UCL source sidecar's retrieval timestamp also advances on a real refresh.

## Refresh

From `/Users/darshan/Documents/PitchRank/PitchRank`:

```sh
.venv/bin/pitchrank refresh --season 2026-2027
# Explicit equivalent: --league europe (all five domestic leagues plus UCL).
.venv/bin/pitchrank refresh --league laliga --season 2026-2027
.venv/bin/pitchrank status --league laliga --season 2026-2027
```

Refresh always downloads the selected current-season provider feeds. The free provider supplies
season CSVs, so download the complete snapshot and incrementally insert/correct SQLite rows;
this avoids pretending the provider offers a per-match delta API. Replay all affected connected
history chronologically, including corrections/late-arriving earlier matches. A failed import
or replay rolls back results, successful-import records and ratings together. Missing previous
results cause a reviewable failure rather than silently erasing scores or accepting a truncated
feed as a successful synchronization. A repeat import is idempotent, while retaining its audit.

The existing in-app Refresh button updates its selected domestic league plus UCL; the European
Rankings button updates all leagues. Refresh remains manual, not scheduled. Viewing or focusing
a page reloads stored API data; it does not itself download football results. Provider publication
lag cannot be resolved by inventing missing results or substituting another dataset.

## Verified outcome

| League | Before | After | New results | Latest completed domestic match |
| --- | ---: | ---: | ---: | --- |
| Premier League | 70 | 80 | 10 | 25 October 2026 |
| La Liga | 89 | 99 | 10 | 26 October 2026 |
| Serie A | 70 | 80 | 10 | 25 October 2026 |
| Bundesliga | 54 | 63 | 9 | 25 October 2026 |
| Ligue 1 | 63 | 72 | 9 | 26 October 2026 |

UCL remains 54 current-season completed matches. The historical+current connected pool now
contains 4,330 matches and 8,660 match/team history rows. All five fresh CSVs were compared
row-for-row against stored canonical team/date/score tuples: zero missing, extra or duplicate
completed results. Full history chronology and per-club before/after continuity were verified.
Repeat La Liga synchronization reported 0 inserted, 0 updated and 99 unchanged results.

To inspect the latest La Liga fixtures directly without changing anything:

```sh
sqlite3 -header -column data/pitchrank.sqlite3 "
SELECT m.match_date, h.display_name AS home, m.home_goals, m.away_goals,
       a.display_name AS away
FROM matches m
JOIN teams h ON h.id=m.home_team_id
JOIN teams a ON a.id=m.away_team_id
WHERE m.league='laliga' AND m.season='2026-2027' AND m.status='finished'
ORDER BY m.match_date DESC, m.kickoff_at DESC LIMIT 10;"
```

This includes Sevilla–Osasuna 2–0 (26 October) and Barcelona–Real Madrid 1–2 (25 October).
Open the existing La Liga team profiles to see those results and corresponding recalculated Elo
changes. `GET /api/league?league=laliga` now returns matches=99,
results_through=2026-10-26 and last_synced_at, independently of other leagues' replay time.
CLI status stores UTC audit time; the browser converts the timestamp to the local timezone.

## Verification and design

150 backend tests and 5 frontend navigation tests passed; build, ESLint, Ruff, Alembic schema drift
and whitespace checks passed. The existing AnyIO deprecation warning remains. New tests cover:
late older results, correction/date identity, repeat imports, incomplete/future/postponed rows,
truncated full snapshots, chronological Elo continuity, failed-replay rollback, per-league
freshness, no-store headers and respecting explicit TLS trust settings. Live CLI and browser
refreshes both succeeded without a certificate environment override.

TasteSkill 2.1.5 and its app-screen instructions, web-design-guidelines (fresh Vercel guideline
source), and the installed Clean design instructions were read. Preserve existing neutral dark
palette, Geist typography, spacing and leaderboard components. The only new UI is a quiet,
plain-text two-line freshness stamp with a semantic `time` element; it remains visible at 390px.
Taste inspection: 0 FAIL at 1440/768/390. Existing compact metadata and the inspector's
no-data-hue warning are retained: this is an established dense table with blue rating bars,
not a redesigned chart. All six final screenshots were inspected.

ROUND 1
Seen in one second: La Liga's latest match date and actual last data update are distinct.
Idea (one sentence): Keep PitchRank's football ledger and make its evidence age explicit.
Live thing: the existing Refresh button fetches real results and advances the sync timestamp.
Layout words by section: shell=unchanged / freshness=two text lines / rankings=unchanged table.
Scores: design 7.0 · usability 7.5 · creativity 6.0 · content 8.0 → overall 7.1.
Caps applied: established app-screen identity; no redesign or marketing imagery required.
Top three problems (most visible first), each with screenshot and resolution:
1. Phone freshness previously hidden: mobile-fold now gives it an explicit second header row.
2. Global date incorrectly suggested domestic freshness: desktop-fold now uses domestic matches.
3. Calculation time looked like import time: all fold images now display committed import time.
Remaining limitation: metadata remains compact to preserve the established interface.
