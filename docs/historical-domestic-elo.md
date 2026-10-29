# Historical domestic results and cutoff Elo

## Reused architecture

Existing SQLite teams, aliases, matches and import observations; Football-Data downloader,
Pandas CSV validation/upserts; existing PlayedMatch/replay_season and update_ratings mathematics.
No new database tables, migrations, dependencies, frontend changes, prediction model or simulator.

Changes:
- `data/domestic-history.json`: reviewed provider names/canonical IDs, season rosters, expected
  match counts and the explicit 2019/20 Ligue 1 curtailed-season exception.
- `ingestion/teams.py`: extend existing seeding/roster lookup from that registry while retaining
  all earlier aliases; conflicting aliases fail rather than fuzzy-matching.
- `ingestion/domestic_history.py`: full-season validation and per-season audited imports, with
  counts, unresolved names and errors; uses existing importer, no duplicate match pipeline.
- `elo/season.py`: optional offseason regression in the existing replay, default zero so live
  app behavior stays unchanged. `services/historical.py`: read-only date-limited reconstruction.
- `ingestion/cli.py`: domestic-history and historical-elo commands.
- `main.py`: historical rating endpoint. Tests/fixture, README, coverage report and ignore rule.

## Real data coverage

Source: https://www.football-data.co.uk/data.php, divisions E0/SP1/I1/D1/F1.
All 80 completed-season CSVs for 2010/11–2025/26 were accessible. Imported 28,893 historical
results: 24,629 new match rows, 0 score corrections; the rest already existed. Zero unmatched
names. Detailed per-season counts, statuses and audit run IDs are in `domestic-history-coverage.json`.

| League ID | Seasons | Completed matches |
| --- | ---: | ---: |
| epl | 16 | 6,080 |
| laliga | 16 | 6,080 |
| seriea | 16 | 6,080 |
| bundesliga | 16 | 4,896 |
| ligue1 | 16 | 5,757 |

Premier League, La Liga and Serie A each have 380 matches per season; Bundesliga has 306.
Ligue 1 has 380 through 2022/23 except 2019/20, then 306 from 2023/24. Its 2019/20 feed contains
279 completed results out of 380 planned; the curtailed season is explicitly flagged. The FFF
annual report confirms the interruption and 279 matches:
https://media.fff.fr/uploads/document/ebe701d2b3b355e77b00d3badd780254.pdf.
No results were invented for cancelled games. No requested season file was missing.

Provider terms currently limit use to private individuals and exclude commercial/data-training
uses involving automated bots/scrapers/AI. Free accessibility is not an unrestricted license;
review permission before commercial distribution or training uses. No paid source was added.

Validation checks actual league/season rosters, complete home/away pair uniqueness, expected
counts, per-club schedule counts (except the curtailed season), full-time results, dates and
source conflicts. Existing importer retains row provenance/checksums and stable IDs across
corrections. Missing/malformed seasons fail independently with a report and no invented data.
Raw provider files are retained in ignored `data/raw/domestic-history/`.

## Two date defects corrected

The former domestic date bound ended on August 1 and rejected five Serie A results dated
August 2, 2020. The 2019/20 boundary now accommodates the actual COVID-delayed finish.

The older UCL reader interpreted yearless August knockout dates as the starting year of the
season. For example, Leipzig–PSG on August 18, 2020 was incorrectly dated August 18, 2019,
causing a collision with domestic fixtures. Knockout headings now use the season's ending year
unless an explicit year is supplied. The importer reconciles only an exact retained source
line/home/away/season observation before correcting its date, preserving IDs and scores.
Eleven August fixture dates were corrected; associated tie ordering/metadata was refreshed.
Tests cover the corrected semifinal date and repeat correction without duplicate matches.

## Historical reconstruction

```python
from datetime import date
from app.services.historical import get_team_elo_at_date
rating = get_team_elo_at_date(team_id, date(2021, 2, 16))
```

SQL selects only finished domestic/UCL matches with
`2010-07-01 <= match_date < cutoff_date` BEFORE constructing participants or replaying anything.
Same-day matches are excluded conservatively; date cutoffs are not kickoff timestamps. Future
match outcomes, future participation lists and current squad values are never read as priors.
All clubs start at the configured neutral 1500, including newly encountered/outside-five clubs.
No promotion initialization based on end-of-season membership is used.

The existing Elo update, home advantage, goal-margin multiplier and competition weights remain
unchanged. Champions League matches share canonical IDs with domestic matches, transferring
rating information between leagues. Neutral venues follow stored metadata.

Historical default offseason regression is 0.25, from existing EloConfig. At each club's FIRST
observed match of a new season, regress its deviation from 1500 by `(1-regression)^elapsed_years`.
This uses that club's own observed season transitions; other leagues starting a new campaign
do not prematurely regress a club still playing 2019/20 UCL games. At a cutoff before a club's
first new-season appearance, its old rating is carried. Zero regression gives full carry-forward;
all departed/inactive clubs retain ratings for possible return. The current live replay still
defaults to zero regression and its current priors/window.

Parameters are supplied through the existing immutable SeasonConfig/EloConfig objects. The
snapshot includes input/config hashes and parameters for reproducibility. It is reconstructed
on demand, without writing over live SeasonRating/SeasonHistory. Corrections to earlier results
are naturally incorporated on the next reconstruction; changes after the cutoff cannot affect it.
No historical snapshot cache can retain stale ratings.

```sh
cd /Users/darshan/Documents/PitchRank/PitchRank
.venv/bin/pitchrank domestic-history
# Optional: --league laliga --from-season 2010-2011 --to-season 2025-2026
# Reuse already downloaded files: --directory data/raw/domestic-history
.venv/bin/pitchrank historical-elo --cutoff 2021-02-16
.venv/bin/pitchrank historical-elo --cutoff 2021-02-16 --team-id 93
# Optional --config path/to/parameters.json
```

Example parameter JSON:

```json
{"elo":{"k_factor":20,"home_advantage":65,"season_regression":0.25},"ucl_league_importance":1.25,"ucl_knockout_importance":1.5,"ucl_finals_importance":1.75}
```

`GET /api/teams/{id}/historical-elo?cutoff=2021-02-16` returns the same default historical rating.
Backend callers can reconstruct the entire pool once and reuse its ratings for a bracket.
Tune parameters on training/validation years only, freeze them before evaluating test cutoffs.
The explicit `start_date` argument controls historical warm-up; live squad-prior parameters and
live history_start are unused in this neutral-prior historical reconstruction.

## 2020/21 Round-of-16 verification

A snapshot strictly before 16 February 2021 used 20,489 matches, most recent 15 February,
and covered all 16 knockout clubs. These are reconstructed Elo ratings, not probabilities:

| Club | Elo before 16 February 2021 |
| --- | ---: |
| Bayern Munich | 1806.8 |
| Man City | 1777.4 |
| Paris Saint-Germain | 1729.5 |
| FC Barcelona | 1726.2 |
| Atlético de Madrid | 1716.3 |
| Juventus | 1702.6 |
| Real Madrid | 1683.9 |
| Liverpool | 1673.2 |
| RB Leipzig | 1671.3 |
| Atalanta | 1670.2 |
| Sevilla FC | 1655.9 |
| Chelsea | 1642.2 |
| Lazio | 1634.6 |
| Borussia Dortmund | 1611.3 |
| Borussia Mönchengladbach | 1599.3 |
| Porto | 1596.9 |

## Preservation, tests and limitations

Backup: `/tmp/pitchrank-before-domestic-history.sqlite3`. Actual SQL comparisons confirmed all
448 current-season matches and every live season rating/history row remained unchanged.
All five domestic views and European Top 25 still load. No Elo match formula changed.

Tests cover full-season import/reimport, missing rows, unmatched names, chronological carry,
regression, neutral venues, COVID season overlaps/date repair, strict cutoff exclusion, API
response, and changing a FUTURE score without changing any past snapshot field or input hash.
The real Bundesliga fixture is limited to result columns; no test downloads or odds dependencies.

Limitations: no 2010/11 UCL data is available in the existing archive; outside-five clubs have
UCL evidence only; no Europa League or lower divisions are included. Early ratings need warm-up,
and neutral 1500 priors do not claim known historical squad strength. Historical neutral-venue
metadata is incomplete (some relocated matches may still receive nominal home advantage).
Archived results may include later corrections: cutoff isolation prevents future-match leakage,
but there are no contemporaneous publication-time versions proving every stored correction was
known then. This is a foundation for historical testing, not yet a validated knockout predictor.
