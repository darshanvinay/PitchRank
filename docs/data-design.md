# Phase 1 data design

## Schema

Teams have stable internal IDs, canonical names, display names, and an optional crest reference.
Aliases are unique per source and normalized by whitespace and case. The seed mapping covers all
51 clubs to appear in the EPL since 1992. No fuzzy matching is used. Add reviewed aliases to the
central mapping, then re-import; unknown names stop the import with a row-numbered error.

Matches reference team IDs, retain season and local match date, optional UTC kickoff, scores,
status, source and optional external ID, processing state, and creation/update timestamps.
Foreign keys are enabled on every application SQLite connection. Database checks reject self-matches,
negative scores and finished matches without both scores. Match chronology and team/season queries
are indexed. The rating engine was added in Phase 2; see `elo-methodology.md`.

Import runs retain source location, SHA-256 of the exact input bytes, timestamp, and counts.
Immutable match observations preserve original row payloads linked to the import and match. Every
successful re-import is audited even when no match changes. Failed imports roll back entirely and
print an error; failed-run auditing is not yet persisted.

Model versions retain configuration hashes and parameters. Rating history references both model
version and match, with one row per team/match/version. Phase 2 now populates these tables through transactional replay. Model versions also retain an input fingerprint.
New results or corrections mark all existing model versions as requiring rebuild, and reset match
processing flags. Old histories remain available for audit; the Phase 2 rankings service refuses to serve a
model marked `needs_rebuild` as current.

## Import policy

Pandas loads strings without implicit missing-value or numeric coercion. Required columns are Date,
HomeTeam, AwayTeam, FTHG, FTAG, FTR. Division must be E0 if present; a missing Div column is allowed
for explicitly supplied EPL files. Blank trailing rows are skipped. Incomplete result rows fail;
this importer accepts completed results only. Scores must be nonnegative integers and agree with FTR.
Dates accept DD/MM/YYYY, DD/MM/YY, or ISO YYYY-MM-DD. Season labels use YYYY-YYYY and consecutive years.
The allowed July-to-following-August window accommodates the COVID-delayed 2019-2020 season.

Optional Time is interpreted in Europe/London and converted to UTC. Missing time remains NULL;
we never invent midnight kickoff times. Future replay must group ambiguous same-day matches and
predict the whole group before applying its results to prevent leakage.

The canonical match key is season + local match date + home team ID + away team ID, independent of
provider ID. Identical duplicates in a file collapse; conflicting duplicates reject the whole file.
Repeated imports preserve match IDs. Same-source corrections update the canonical score and preserve
both old/new observations. A conflicting score from a different source fails for explicit review;
no arbitrary provider precedence is assumed. Agreeing cross-provider observations attach to the
same match without changing the original result owner.

Transactions include alias seeding, all validation, all match/observation writes, invalidation,
and the success audit. A failure cannot leave a partial season. Each season import is atomic;
a multi-season command sequence is not one combined transaction.

## Boundaries and limitations

A moved fixture date cannot be safely identified from the historical CSV identity alone: it needs
live external ID reconciliation in Phase 5. Historical CSV corrections that change dates or teams
therefore require review; the importer does not guess whether a new row replaces another match.
Football-data.org mappings are prepared from explicit provider names, but live integration, external
ID aliasing, retry/rate-limit behavior, and provider availability are not implemented or tested yet.

Raw CSVs preserve source bytes and successful runs preserve hashes. Identical duplicate rows within
one file collapse into one observation. Kickoff times and aliases depend on provider data quality.
Production writes must use migrations; tests use metadata creation except migration-specific tests.
