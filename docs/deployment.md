# Deploy PitchRank on Render Free and Vercel Hobby

## Switch the existing Render service

1. Use the existing service and keep its Render URL. If a paid disk was already provisioned,
   take and verify a backup of any data unique to it before removing the disk in Render. Free
   services cannot attach a persistent disk. Check the existing service's instance type after
   syncing the Blueprint. [Render Free limits](https://render.com/docs/free)
2. If the service is managed by a Blueprint, commit `render.yaml` and sync the existing
   Blueprint. For a manually configured service, apply these settings in its Render dashboard.

| Render setting | Value |
| --- | --- |
| Root Directory | Repository root |
| Runtime | Python 3.13.13 |
| Instance Type | Free |
| Build Command | `python -m pip install -e ./backend && bash deploy/build-render.sh` |
| Start Command | `bash deploy/start-render.sh` |
| Health Check Path | `/health` |
| Persistent Disk | None |

3. Set `PITCHRANK_CORS_ORIGINS` to the exact existing Vercel HTTPS origin, with no path. If
   configuring manually, set `PYTHON_VERSION=3.13.13` and `PITCHRANK_SEASON=2026-2027`. Render
   supplies `PORT`. Remove any old disk-specific `DATABASE_URL` and
   `PITCHRANK_PROJECTION_DIR` settings. The start script opens the build snapshot in immutable
   read-only mode and forces public mode and daily refresh off.

## Supply the private SQLite snapshot

Create a fresh backup outside the checkout from the repository root. SQLite's online backup
includes committed data from the WAL.

```sh
umask 077
seed_dir=$(mktemp -d)
sqlite3 -readonly data/pitchrank.sqlite3 ".backup '$seed_dir/pitchrank.sqlite3'"
sqlite3 -readonly "$seed_dir/pitchrank.sqlite3" "PRAGMA quick_check;"
shasum -a 256 "$seed_dir/pitchrank.sqlite3"
gzip -c "$seed_dir/pitchrank.sqlite3" > "$seed_dir/pitchrank-seed.sqlite3.gz"
```

Host `pitchrank-seed.sqlite3.gz` at a private, signed HTTPS download URL you already control and can use within
free quotas. Add the URL as `PITCHRANK_SEED_URL` and the **uncompressed SQLite file's** digest as
`PITCHRANK_SEED_SHA256` in the Render service's environment. Keep the backup, URL and digest
out of Git and public artifacts. Renew the URL before a new build if it expired. The build
decompresses, verifies, and migrates the backup, then packages it in its private filesystem. Render cold
starts open the packaged snapshot and do not call the seed host. A fresh build requires valid
seed credentials. Avoid unattended rebuilds if the URL is short-lived.

The database includes domestic and Champions League results, Elo histories, and xG.
The API serves the checked-in dated Champions League projection snapshots. For an approved
data refresh, run the existing updater on a writable copy outside Render, validate the
results and projections, update the private seed URL and digest, then redeploy. Publish updated
projection snapshots only where the underlying data is authorized for publication. A GitHub
Actions workflow could trigger a deploy after an approved seed update using protected secrets
and a trusted branch, within included usage. Scheduled downloads and public artifact uploads
are disabled. Confirm provider permissions before public release or automation.
[Football-Data policy](https://football-data.co.uk/contact.php)

## Keep the existing Vercel project

Use Hobby, Root Directory `frontend`, Framework Preset Vite, Node.js 24.x, Install Command
`npm ci`, Build Command `npm run build`, and Output Directory `dist`. Keep `VITE_API_URL` set
to the existing Render origin. There is no frontend redeploy needed if that origin stays the
same.

After deploying, check `/health`, the five league views and European rankings, a club profile
with xG, and both Champions League bracket views. Public Refresh Data reloads the published
snapshot. Direct import requests return HTTP 403. Expect cold starts after inactivity and watch
the workspace's free usage limits. [Render Free limits](https://render.com/docs/free)
