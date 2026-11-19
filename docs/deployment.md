# Public deployment

Deploy Render from the repository root using `render.yaml`. It defines one Standard Python web
service with a 5 GB persistent disk mounted at `/var/data`. Use Python 3.13.13, build with
`python -m pip install -e ./backend`, and start with `bash deploy/start-render.sh`. The script
restores the seed if needed, applies Alembic migrations against the mounted disk, and runs
`uvicorn app.main:app --host 0.0.0.0 --port "$PORT" --workers 1`. Set the health check to
`/health`. The editable install keeps the code's paths to checked-in squad data, club mappings,
frozen models and bundled projection snapshots relative to the repository.

## Initial database transfer

Create a consistent backup from the repository root. SQLite's online backup includes committed
data even if the source is using WAL. Use a new private path outside the checkout.

```sh
umask 077
sqlite3 -readonly data/pitchrank.sqlite3 ".backup /tmp/pitchrank-render-seed.sqlite3"
sqlite3 -readonly /tmp/pitchrank-render-seed.sqlite3 "PRAGMA quick_check;"
shasum -a 256 /tmp/pitchrank-render-seed.sqlite3
```

Upload the backup to private object storage and create an expiring HTTPS download URL. Enter the
URL and SHA-256 digest as Render environment variables. On first boot the service verifies both
the digest and SQLite integrity before installing the seed. Keep the private backup for recovery.
The live file is never overwritten during deploys. Once seeded, remove the two seed environment
variables and keep regular SQLite online backups off the service. Restore onto a stopped service
or a separate disk and verify it before switching traffic.

| Where | Variable | Value |
| --- | --- | --- |
| Render | `PITCHRANK_CORS_ORIGINS` | Exact HTTPS Vercel/custom origin, comma-separated if needed, with no path |
| Render | `PITCHRANK_SEED_URL` | Private signed download URL for first boot |
| Render | `PITCHRANK_SEED_SHA256` | Digest for first boot |
| Render | `DATABASE_URL` | `sqlite:////var/data/pitchrank.sqlite3` |
| Render | `PITCHRANK_PROJECTION_DIR` | `/var/data/projections` |
| Render | `PITCHRANK_SEASON` | `2026-2027` |
| Render | `PITCHRANK_PUBLIC` | `1` |
| Render | `PITCHRANK_DAILY_REFRESH` | `0` initially. Set to `1` once daily provider use is authorized. |
| Render | `PYTHON_VERSION` | `3.13.13` |
| Vercel | `VITE_API_URL` | Actual HTTPS Render origin, with no path (public build-time setting) |

Render supplies `PORT`. Keep model overrides at their current defaults.

## Vercel

Set Root Directory to `frontend`, Framework Preset to Vite, Node.js to 24.x, Install Command to
`npm ci`, Build Command to `npm run build`, and Output Directory to `dist`. The checked-in
`frontend/vercel.json` handles deep links. Set `VITE_API_URL` for Production before building.
If previews need API access, use a stable preview origin and explicitly add it on Render.
The local Vite proxy and same-origin FastAPI setup still work with `VITE_API_URL` unset.

## Updates and release checks

Confirm public display and automated-download rights for the data, xG, and crest sources before
launch. The existing Football-Data free feed limits automated downloads to twice per week for its
permitted personal and academic uses, so the blueprint ships with daily imports disabled.
See [Football-Data's fair use policy](https://football-data.co.uk/contact.php).

When enabled, the single Render web process launches the existing updater at startup and then daily at
10:15 UTC. It runs on the same persistent disk as the API. The updater locks against overlapping
runs, commits match and Elo changes together, attempts xG separately, then publishes a dated
projection atomically. The API can serve the bundled snapshot until a persistent one is available.
Render logs capture provider and simulation issues. To trigger an update from the running service's
Render Shell after provider approval, run `python -m app.ingestion.daily --season 2026-2027`. The public Refresh Data
button reloads the latest published data and the public import endpoint returns HTTP 403.

Before sharing the public URL, verify that `/health` and all five league API views return 200,
open a club profile and both Champions League bracket views from Vercel, and check Render logs
after the first update. Record the match counts and check that the database and projection files
survive a restart. Render Cron Jobs cannot mount the web service's disk. Keep one Render instance
while using SQLite. See [Render persistent disks](https://render.com/docs/disks).
