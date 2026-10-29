# Historical Champions League ingestion — 28 October 2026

## Implemented scope

Read, validate, import and browse historical Champions League results. No predictions,
probabilities, tournament simulation or changed Elo formula. Reuse SQLite, teams, aliases,
matches, ImportRun and MatchObservation. No new database or dependency.

Files:
- `backend/app/ingestion/ucl_history.py`: football.txt reader, verified download, explicit club
  mapping seed, coverage/tie checks and atomic importer.
- `data/ucl-history-teams.json`: 136 explicitly reviewed source aliases, linked to existing
  domestic/UCL canonical identities. 35 additional historical outside-five clubs are created.
- `data/ucl-history-errata.json`: one visible UEFA-reviewed source annotation correction.
- `backend/app/db/models.py` and migration `c618b7a320ef_ucl_history_metadata.py`:
  one nullable JSON `matches.ucl_detail` column. Existing rows/IDs/constraints are retained.
- `backend/app/ingestion/cli.py`: `ucl-history` command, one season/local file or all available.
- `backend/app/api/ucl_history.py`, `backend/app/main.py`: two read-only API routes.
- `frontend/src/ChampionsHistory.tsx`, `App.tsx`, `style.css`: existing sidebar integration,
  season/stage/club filtering, 30-row pagination, match details and explicit unavailable states.
- `backend/tests/test_ucl_history.py`, four CC0 raw fixtures and fixture attribution.
- `.gitignore`: retain downloaded raw archives locally without adding them to Git.

## Source investigation and limitations

Candidate: https://github.com/openfootball/champions-league
Pinned revision: `abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef`.
License: CC0-1.0 (`LICENSE.md`, read from the repository).
Format: structured UTF-8 football.txt, not CSV or an API. A heading gives a group/round, date
lines may omit the year, and match lines may omit a repeated clock. Penalty scores precede
full after-extra-time scores, with regulation and half-time scores in parentheses.

The repository tree contains main-draw `cl.txt` files for 2011/12–2025/26 only. It has no
2005/06–2010/11 files. The API and UI list those six seasons as source_unavailable, not zero
matches or complete. Qualifiers are excluded; the repository has some qualifying files, but
there is no consistent qualifying coverage across this archive.

Additional source reviewed: RSSSF's https://www.rsssf.org/ec/ec200506.html contains older
historical results. It combines paired scores, footnotes and date exceptions in less regular
HTML/text and has different reuse terms from Openfootball's CC0. Integrating it requires a
separate reviewed adapter and licensing assessment. UEFA's archive is a primary verification
source but does not supply this application's simple, consistently licensed bulk feed. Neither
is silently substituted for missing Openfootball seasons.

Downloaded originals and checksum/revision receipts are retained in ignored
`data/raw/openfootball/`. Imports record exact SHA-256, source URL and original line numbers/text.
Local `--file` inputs record their local path; a pinned revision is only claimed when the
receipt's hash and official pinned URL match. The importer never fuzzy-matches clubs.

## Data model and score semantics

Core Match fields retain competition (`league=ucl`), season, match date, canonical home/away
IDs, 90-minute goals, finished status, existing importance stage, and neutral venue. Existing
UTC kickoff is preserved for overlapping provider matches. New archive-only matches have null
UTC kickoff because the archive does not reliably specify time zones. A source clock label,
when explicitly present, remains in metadata; repeated or missing clocks are not invented.

`ucl_detail` records round, group when supplied, leg, tie_id, tie_format, derivation explanation,
full after-extra-time score, shootout scores, source identity/line/text/URL/revision and historical
away-goals-rule applicability. Null means unavailable or not applicable; zero means a real score.
Two-legged ties share a tie ID. Their leg numbers derive explicitly from chronological reversed
home/away pairings, not a guessed matchday. Finals, and 2019/20 quarterfinals/semifinals, are
single matches with null leg numbers. The group stage and post-2024 league phase remain distinct.

Regulation results never include penalties. The parser understands
`4-1 a.e.t. (3-1, 1-0)` as 3–1 at 90 minutes, 4–1 after extra time, with the raw string retained.
An ambiguous extra-time score without its regulation split is rejected. Half-time and
extra-time totals cannot decrease, and shootout scores must identify a winner.

One reviewed erratum is necessary: Openfootball's 2024/25 PSV–Juventus row reads `3-1 (0-0)`
without marking extra time. PitchRank already stores 2–1 at 90 minutes based on UEFA's
https://www.uefa.com/newsfiles/UCL/2025/2044483_TS.pdf.
The original source line/score are preserved; an explicit erratum stores 2–1 regulation and
3–1 after extra time, with the UEFA URL/reason. The import summary reports this source note,
the API exposes it and the row shows “Reviewed source erratum”. No stored score was overwritten.
Any other score/status conflict with an existing provider rejects that season atomically.

Each import validates season title/dates, scores, stages, fixture keys, unique club counts,
per-club group/league appearances, per-stage match totals, and complete reversed knockout legs.
Expected counts: 125 for the older main draw, 119 in 2019/20, 189 from 2024/25. Count coverage
is not a claim that every individual historical score was independently checked against UEFA.

## Commands

From `/Users/darshan/Documents/PitchRank/PitchRank`:

```sh
.venv/bin/alembic -c backend/alembic.ini upgrade head
.venv/bin/pitchrank ucl-history --all
.venv/bin/pitchrank ucl-history --season 2011-2012
.venv/bin/pitchrank ucl-history --season 2011-2012 --file /path/to/cl.txt
```

The JSON summary reports inserted, enriched, unchanged, duplicate and skipped counts, unresolved
teams, errors, expected/stage totals and source errata. Malformed/incomplete/unresolved seasons
are not committed; successful seasons commit independently. Repetition adds audited source
observations but no duplicate match rows. Current 2024/25–2025/26 rows are reused by canonical
competition/season/date/home/away key, not duplicated under a different provider.

## API and UI

- `GET /api/ucl/seasons`: all requested seasons, source availability, main-draw coverage,
  imported/expected counts, stage counts, reviewed errata count, last successful import,
  source location, license and limitations.
- `GET /api/ucl/matches?season=2011-2012`: dated results, canonical clubs, score splits,
  tie/leg information and provenance, in chronological order.
- Add `stage=group|league|playoff|round_of_16|quarterfinal|semifinal|final`.
- Add `team_id=<canonical ID>`, or omit season to query that team's entire imported archive.
  Missing both season/team and invalid season/stage values return 422.

Open http://127.0.0.1:8000/champions-league/history from “Champions League History” in the
existing sidebar. Select season/stage/club, or click a club name to filter its results. Filters
and pagination are URL state; season changes clear incompatible filters. Large lists show
30 rows per page. Missing source seasons and unimported seasons have explicit empty states.
The UI uses existing dark surfaces, Geist typography, tables and focus treatments; no redesign.

## Imported coverage

1,997 distinct historical matches: 1,619 inserted, 378 existing rows enriched. Six earlier
requested seasons remain unavailable. Repeating all 15 seasons yielded 0 inserted, 0 enriched,
1,997 unchanged matches.

| Season | Expected | Stored | Status |
| --- | ---: | ---: | --- |
| 2011-2012 | 125 | 125 | Complete main draw |
| 2012-2013 | 125 | 125 | Complete main draw |
| 2013-2014 | 125 | 125 | Complete main draw |
| 2014-2015 | 125 | 125 | Complete main draw |
| 2015-2016 | 125 | 125 | Complete main draw |
| 2016-2017 | 125 | 125 | Complete main draw |
| 2017-2018 | 125 | 125 | Complete main draw |
| 2018-2019 | 125 | 125 | Complete main draw |
| 2019-2020 | 119 | 119 | Complete main draw |
| 2020-2021 | 125 | 125 | Complete main draw |
| 2021-2022 | 125 | 125 | Complete main draw |
| 2022-2023 | 125 | 125 | Complete main draw |
| 2023-2024 | 125 | 125 | Complete main draw |
| 2024-2025 | 189 | 189 | Complete main draw |
| 2025-2026 | 189 | 189 | Complete main draw |

## Preservation and verification

SQLite backup: `/tmp/pitchrank-before-ucl-history.sqlite3`.
Actual before/after SQL comparison confirmed all 4,658 non-UCL match records unchanged,
331 season rating records unchanged, 8,660 season-history rows unchanged and 2,280 offline
rating-history rows unchanged. Domestic views still return 20/20/20/18/18 clubs; Top 25 returns25.
The current replay window remains 2024/25 onward; the new earlier seasons are archival inputs,
not an unsolicited expansion of today's rating calculation.

160 backend tests and 5 frontend navigation tests pass. New cases cover all four format eras,
extra-time/shootout handling, the explicit erratum, canonical identities, duplicates, ordering,
two-leg ties, missing/malformed/unresolved data, cross-provider conflict rollback, nullable
migration safety/repeated upgrade, domestic snapshot preservation and API filters/errors.
Build, ESLint, Ruff and Alembic drift checks pass. One existing AnyIO deprecation warning remains.

TasteSkill 2.1.5/app-screen rules, web-design-guidelines and the installed Clean consistency
instructions were applied. Retain existing achromatic-ledger direction and typography; no redraw.
Browser inspection at 1440/768/390: 0 FAIL, one warning for compact 11–12px metadata retained
from the existing design. All six screenshots were read. Native selects have labels, results
use semantic table/time elements, and phone navigation/table overflow stays inside its frame.

ROUND 1
Seen in one second: Champions League archive, a selected season and its real final result.
Idea (one sentence): Reuse PitchRank's football ledger to preserve each stage and score convention.
Live thing: select a season, filter a stage, click a club and read its real history.
Layout words by section: shell=existing / filters=native controls / results=shared table styling.
Scores: design 7.0 · usability 7.5 · creativity 6.0 · content 8.0 → overall 7.1.
Caps applied: established app-screen identity, no decorative imagery or motion required.
Top three problems and resolutions:
1. Four sidebar destinations overflow tablet: navigation uses its own wrapping row.
2. Hundreds of results overwhelm browsing: 30-row URL-backed pagination.
3. Missing earlier seasons could look like zero matches: explicit source-unavailable state.
Remaining limitation: phone users scroll the table horizontally to compare all score fields;
this preserves PitchRank's existing dense-table convention.

## Foundation for a future predictor

Canonical IDs and dated regulation scores can feed the existing chronological Elo update
function. Full extra-time, penalty and paired-leg data lets a later implementation reconstruct
aggregate/advancement outcomes, distinguish historical away-goals rules and validate knockout
backtests. None of that requires a second rating engine.

This archive alone is not a leakage-free historical prediction dataset: earlier domestic
results, time-appropriate initial priors/valuations, historical tie rules and strict training/
validation/test cutoffs must be reviewed before modeling. Today's September 2026 squad prior
must not be reused as if known in 2011. No predictor or tournament simulator was implemented.
