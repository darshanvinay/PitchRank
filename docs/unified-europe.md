# Unified European Elo — verified 22 October 2026

One SQLite database, one existing Elo engine, one chronological replay. Domestic tables and
European Rankings now read identical stored club ratings. No new dependency, service, rating
engine, model version or database table was added. The additive migration adds `stage` and
`neutral` to Match. Existing research/backtesting code remains available.

## Data coverage

| Competition | 2024/25 | 2025/26 | 2026/27 completed |
| --- | ---: | ---: | ---: |
| Premier League | 380 | 380 | 70 |
| La Liga | 380 | 380 | 89 |
| Serie A | 380 | 380 | 70 |
| Bundesliga | 306 | 306 | 54 |
| Ligue 1 | 306 | 306 | 63 |
| Champions League | 189 | 189 | 54 |

Total: **4,282 matches**, **151 clubs in one connected component**, **8,564 match/team history rows**.
All 96 current domestic clubs retain their previous domestic W/D/L/goals/matches and squad values.
Champions League main-draw coverage runs through 21 October 2026; qualifiers are excluded.
Domestic source: [Football-Data](https://www.football-data.co.uk/data.php).
UCL import: [Fixture Download](https://fixturedownload.com/results/champions-league-2026),
using `/feed/json/champions-league-{year}`. Raw feed hashes and normalized CSVs are retained in
ignored `data/raw`; the importer records observations, checksums and source URLs in SQLite.

Club mappings explicitly map provider aliases to existing domestic IDs; other UCL opponents
have one canonical `other` identity. Unknown aliases fail ingestion rather than fuzzy matching.
Historical rosters are derived from the domestic source feeds, not assumed current rosters.
The latest UCL round was checked against [UEFA's official results](https://www.uefa.com/uefachampionsleague/news/02a8-2174c9e9019d-f909a77bd77a-1000--2026-27-champions-league-all-the-league-phase/).
Historical results were cross-checked using Openfootball's 2024/25 and 2025/26 Champions League
files and UEFA match reports for extra-time exceptions; this is not a claim that every historical
fixture was independently checked against a primary match report.

## Calculation and limitations

`change = K × importance × goal_multiplier × (actual_score − expected_score)`.
K=20, home advantage=65, Elo scale=400 and goal multiplier=max(1, ln(abs(goal difference)+1))
are unchanged. Initial squad adjustment=clamp(60 × ln(value / €556.425m), −100, +100).
Each club receives its initial prior once. Subsequent seasons carry its rating forward unchanged
before the next match; no seasonal squad bonus or trophy bonus is applied.

Importance defaults: domestic 1.00, UCL league phase 1.25, knockouts 1.50, semifinals/final 1.75.
These are assumptions, not optimized weights. Configure `ELO_DOMESTIC_IMPORTANCE`,
`ELO_UCL_LEAGUE_IMPORTANCE`, `ELO_UCL_KNOCKOUT_IMPORTANCE`, `ELO_UCL_FINALS_IMPORTANCE`.
Replay starts at `ELO_HISTORY_START=2024-2025`. Dates and UTC kickoffs determine replay order;
simultaneous fixtures use the same pre-batch ratings. Each match conserves total Elo.

Use regulation-time results: penalty winners do not change a draw into a win. Finals are neutral.
Three provider scores included extra time; reviewed 90-minute overrides and UEFA source links
live in `data/ucl-regulation-scores.json`, with regression tests for each.

**Valuation limitation:** only documented September 2026 values exist for the 96 current clubs.
The earliest available stored value seeds each club once, including retrospective seeding of
2024 warm-up matches. This introduces look-ahead information and is appropriate only as a
retrospective current-strength estimate, not a historical prediction backtest. Missing historical
and outside-league values use a neutral 1500 prior; no values were invented. Outside-five clubs
contribute their UCL matches, but their domestic competitions are not imported. Ratings are
connected estimates, with incomplete evidence for those opponents, not proven league coefficients.

## API, website and refresh

Existing `/api/league?league=europe` returns a dynamic Top 25 from the 96 current clubs.
The same route with a domestic league returns its original club count and domestic statistics.
History, form and last-match changes include both competitions. Existing team links retain their
club's domestic league. External opponents render as text, not broken profile links.

European Rankings reuses the leaderboard, search, sort, form, crests and native select controls.
Its league filter narrows the global Top 25, rather than inventing a different 25 per league.
Team charts retain their current-season scope; prior-season match histories remain stored.

Bootstrap/update all coverage:

```sh
alembic -c backend/alembic.ini upgrade head
pitchrank refresh --league europe --season 2026-2027
```

The European Refresh button performs the same all-league refresh. A domestic refresh fetches
that domestic league and current UCL results, then rebuilds the connected ratings atomically.
It preserves other domestic match/statistical data; ratings elsewhere may legitimately change
through the connected match graph. Historic cached feeds are reused. Provider failures leave
the previous good database snapshot intact. Repeating the full refresh inserted/updated zero
matches and retained the same 4,282-match pool.

## Verification

- All five domestic API views load with 20/20/20/18/18 clubs; Top 25 equals the highest ratings
  from their union, with no external or relegated clubs in the display.
- All 151 participants form one connected component; 8,564 history rows are chronological,
  each club's next rating-before equals its preceding rating-after, including season boundaries.
- No duplicate competition/season/date/home/away fixture keys.
- Focused tests cover importance weights, zero-sum updates, neutral venues, season carry,
  chronology, stages, scheduled fixtures, duplicates, extra-time corrections, shared identities,
  external opponents and domestic/European API consistency.
- Browser checks: league filtering, European-to-PSG profile navigation, PSG's domestic/UCL
  history, Barcelona cross-league profile link, and existing five-league routes.
- 141 backend tests and 5 frontend navigation tests pass (one existing AnyIO deprecation warning).
- Build, ESLint, Ruff and Alembic drift checks pass.

## Skills and visual verification

Actual instructions read and applied:
- TasteSkill: `/Users/darshan/.codex/plugins/cache/taste-skill/taste-skill/2.1.4/skills/taste-skill/SKILL.md`
  plus `references/app-screens.md`; preserve achromatic-ledger direction (seed 1559896174),
  real club data, flat surfaces, existing Geist and dark palette; no redraw.
- Web guidelines: `/Users/darshan/.agents/skills/web-design-guidelines/SKILL.md`, with its
  current Vercel guideline source; named native controls, URL filter state, semantic tables,
  keyboard navigation and mobile wrapping.
- AwesomeDesign collection's installed Clean instructions:
  `/Users/darshan/.agents/skills/clean/SKILL.md`; apply consistency and accessibility guidance,
  preserve existing typography/colors per user instruction. No standalone AwesomeDesign SKILL.md
  is available; this does not claim a separate absent skill was loaded.

Taste inspection at 1440, 768 and 390 reports 0 FAIL. Existing compact metadata remains
11–12px; this is retained for consistency, while primary names/values remain larger. The
no-data-hue warning mistakes inline rating bars for a chart; bars already use the existing blue
accent. Mobile keeps the existing horizontally scrollable table within its own frame.

ROUND 2
Seen in one second: European club strength, with Bayern leading the actual Top 25.
Idea (one sentence): PitchRank's existing football ledger connects five leagues through UCL results.
Live thing: search, filter, sort and open real club histories.
Layout words by section: shell=existing / summary=divided metrics / rankings=shared table.
Scores: design 7.0 · usability 7.5 · creativity 6.0 · content 8.0 → overall 7.1.
Caps applied: existing identity retained; app-screen rules apply, no marketing photography/motion.
Top three problems (most visible first), each with the screenshot it shows in and the fix:
1. Desktop duplicated “Top 25 25”; changed heading to European leaderboard with a count.
2. Mobile compact filter truncates “All five leagues”; retained native full-option menu and
   accessible name, with table scrolling consistent with existing domestic layout.
3. Profile caption implied seasonal reset; replaced with explicit carry-forward statement.
Remaining limitation: mobile requires horizontal table scrolling to compare every column;
retaining the established table is intentional under the no-redesign requirement.

## Before and after

These differences combine two historical seasons, UCL results, importance and carry-forward;
they are not an isolated experiment measuring the effect of importance weights alone.

| Club | Previous model | Unified | Difference |
| --- | ---: | ---: | ---: |
| Paris Saint-Germain | 1569.1 | 1794.3 | +225.2 |
| FC Barcelona | 1625.1 | 1772.8 | +147.6 |
| Man City | 1613.3 | 1720.7 | +107.4 |
| Bayern Munich | 1572.8 | 1810.5 | +237.7 |
| Real Madrid | 1582.4 | 1718.8 | +136.3 |

## Resulting Top 25

| Rank | Club | Domestic league | Unified Elo |
| ---: | --- | --- | ---: |
| 1 | Bayern Munich | Bundesliga | 1810.5 |
| 2 | Arsenal | Premier League | 1799.4 |
| 3 | Paris Saint-Germain | Ligue 1 | 1794.3 |
| 4 | FC Barcelona | La Liga | 1772.8 |
| 5 | Man City | Premier League | 1720.7 |
| 6 | Real Madrid | La Liga | 1718.8 |
| 7 | Inter | Serie A | 1678.3 |
| 8 | Liverpool | Premier League | 1646.1 |
| 9 | Borussia Dortmund | Bundesliga | 1638.7 |
| 10 | Roma | Serie A | 1629.6 |
| 11 | Aston Villa | Premier League | 1622.8 |
| 12 | Atlético de Madrid | La Liga | 1617.0 |
| 13 | Brighton | Premier League | 1616.9 |
| 14 | Como | Serie A | 1611.7 |
| 15 | Bayer Leverkusen | Bundesliga | 1599.0 |
| 16 | Real Betis | La Liga | 1583.4 |
| 17 | Man United | Premier League | 1579.8 |
| 18 | Milan | Serie A | 1579.5 |
| 19 | Juventus | Serie A | 1576.4 |
| 20 | Chelsea | Premier League | 1570.5 |
| 21 | Brentford | Premier League | 1567.4 |
| 22 | Bournemouth | Premier League | 1566.6 |
| 23 | VfB Stuttgart | Bundesliga | 1562.2 |
| 24 | Napoli | Serie A | 1560.8 |
| 25 | Lazio | Serie A | 1558.9 |
