# Elo methodology

## Scope

These ratings describe relative strength from imported Premier League results. They are not the
Premier League points table, calibrated match probabilities, or evidence of predictive accuracy.
The current defaults are untuned. Draw fitting, optimization, and evaluation belong to later phases.

## Mathematics

For home rating Rh, away rating Ra, home advantage H, and rating scale S:

```
E_home = 1 / (1 + 10 ** ((Ra - Rh - H) / S))
actual_home = 1 for a home win, 0.5 for a draw, 0 for a loss
multiplier = max(1, goal_multiplier_scale * ln(abs(home_goals - away_goals) + 1))
delta = K * multiplier * (actual_home - E_home)
Rh_after = Rh + delta
Ra_after = Ra - delta
```

The implementation uses a numerically stable logistic equivalent to the expected-score formula.
The goal multiplier has a floor of one, so draws still change ratings when expected score is not
0.5. A zero multiplier scale disables goal-margin amplification. Each match's two stored changes
are exact opposites. Floating-point additions may have ordinary rounding error.

`E_home` is an expected result score. It must not be labelled home-win probability; a separately
fitted three-outcome prediction model will handle draws later.

## Configuration and identity

Defaults in `backend/app/core/elo.py`:

| Parameter | Default |
| --- | ---: |
| Initial rating | 1500 |
| Promotion fallback | 1400 |
| K-factor | 20 |
| Home advantage | 65 Elo points |
| Rating scale | 400 |
| Goal multiplier scale | 1 |
| Season regression | 0.25 |

Pydantic rejects nonfinite parameters, unknown keys, invalid ranges, and mutation. Optional JSON
configurations override these defaults. A canonical JSON representation of all parameters plus the
engine revision is SHA-256 hashed to identify a model. Bump the engine revision when changing replay
or mathematical rules. Versions never share rating-history rows.

## Seasons and membership

All clubs in the first imported season start at the configured initial rating. After that:

- Retained clubs regress toward the initial rating once per elapsed off-season:
  `initial + (previous - initial) * (1 - regression) ** elapsed_years`.
- In consecutive seasons, newly appearing clubs start at the mean final rating of clubs that left
  the EPL. This mean is taken **before** regression.
- A returning club is treated as newly promoted, regardless of its stale rating in an earlier year.
- When the prior season is missing or no departing club can be identified, newcomers use the
  configurable promotion fallback. Retained clubs still regress for each elapsed off-season.
- Season regression and promotion resets are initialization rules, not match gains/losses. Only
  match updates are required to be zero-sum. The total league rating can change across seasons.

Season membership is inferred from clubs with completed matches in the imported dataset. This
works for the three complete imported seasons. Partial or selectively imported seasons can imply
incorrect membership/promotion pools; ensure complete prior-season data before interpreting ratings.
Future evaluation must establish the known season roster without reading future match outcomes.
Unfinished fixtures do not establish membership or affect Phase 2 ratings.

## Chronology

Matches replay by local match date. When all kickoffs on a date are available, replay proceeds by
UTC kickoff time. Equal kickoffs share a pre-group rating snapshot. If any kickoff on a date is
missing, the entire date shares a pre-day snapshot. Ties use home team ID then away team ID, rather
than insertion order or provider match ID. A club appearing twice in one ambiguous group is rejected
for review. Interleaved/out-of-order seasons and duplicate match IDs are also rejected.

Each history row stores sequence, pre-match rating, post-match rating, delta, match, team, and model
version. Sequence is deterministic within the database; unknown chronological order is not invented.

## Persistence and corrections

`pitchrank elo rebuild` takes a SQLite `BEGIN IMMEDIATE` writer lock before reading its inputs.
It fingerprints match identities, scores, statuses, dates, and kickoffs, then performs replay.
All history replacement, processing flags, and model validity updates commit together. Any failure
rolls back, preserving the previous model history. Model reads use one consistent read transaction.

An unchanged valid model is a no-op; `--force` replays it. Changed parameters create a separate model.
New/corrected records cause a full rebuild of the selected model, including downstream history.
This deliberately favors simple, correct replay over incremental updates at EPL dataset sizes.
Import invalidation and fingerprint checks both protect against stale results. Rebuilds do not make
stale versions with other configurations valid. Global `matches.processed` is informational only;
model validity is determined by version-specific invalidation and input fingerprints.

Non-finished, postponed, cancelled, and abandoned fixtures never produce rating history. Rankings
include only clubs in the latest season with completed results, state the last completed match date,
and reject missing/stale models. No current/live-data claim is made.
