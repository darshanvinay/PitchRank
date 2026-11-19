"""Refresh the live SQLite database from the host that serves PitchRank."""

import argparse
import fcntl
import hashlib
import json
import logging
from datetime import date, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.request import Request, urlopen

from sqlalchemy import func, inspect, select
from sqlalchemy.orm import Session

from app.core.season import current_season
from app.db.models import Match
from app.db.session import get_engine
from app.ingestion.historical import provider_ssl_context
from app.ingestion.understat import import_rows
from app.services.season import refresh_season

LOG = logging.getLogger(__name__)
SLUGS = {
    "EPL": "EPL",
    "La liga": "La_Liga",
    "Bundesliga": "Bundesliga",
    "Serie A": "Serie_A",
    "Ligue 1": "Ligue_1",
}


def sync_xg(engine, season):
    if not inspect(engine).has_table("match_xg"):
        LOG.warning("xG table unavailable. Apply the existing Alembic migrations.")
        return
    for league, slug in SLUGS.items():
        url = f"https://understat.com/getLeagueData/{slug}/{season[:4]}"
        try:
            request = Request(
                url,
                headers={
                    "User-Agent": "PitchRank/1.0",
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json",
                    "Referer": f"https://understat.com/league/{slug}/{season[:4]}",
                },
            )
            with urlopen(request, timeout=15, context=provider_ssl_context()) as response:
                payload = response.read(10_000_001)
            if len(payload) > 10_000_000:
                raise ValueError("Oversized Understat response")
            rows = [
                {
                    "league": league,
                    "season": season[:4],
                    "understat_id": row["id"],
                    "match_date": row["datetime"],
                    "home_team": row["h"]["title"],
                    "away_team": row["a"]["title"],
                    "home_score": int(row["goals"]["h"]),
                    "away_score": int(row["goals"]["a"]),
                    "home_xg": row["xG"]["h"],
                    "away_xg": row["xG"]["a"],
                }
                for row in json.loads(payload)["dates"]
                if row["isResult"] is True
            ]
            if not rows:
                raise ValueError("No completed xG observations")
            result = import_rows(engine, rows, hashlib.sha256(payload).hexdigest(), url, apply=True)
            LOG.info(
                "xG %s: inserted=%s updated=%s rejected=%s",
                league,
                result["inserted"],
                result["updated"],
                len(result["rejected"]),
            )
        except Exception:
            LOG.warning(
                "xG unavailable for %s. Match and Elo updates committed.", league, exc_info=True
            )


def run(engine, season):
    database = Path(engine.url.database).resolve()
    with database.with_suffix(".refresh.lock").open("a") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            LOG.info("Skipping overlapping daily refresh")
            return
        with TemporaryDirectory(prefix="pitchrank-feeds-") as directory:
            result = refresh_season(
                engine, season, league="europe", current_only=True, download_dir=Path(directory)
            )
        LOG.info("Committed match and Elo refresh: %s", json.dumps(result))
        with Session(engine) as session:
            dates = session.execute(
                select(Match.league, func.max(Match.match_date))
                .where(Match.season == season, Match.status == "finished")
                .group_by(Match.league)
            ).all()
        for league, latest in dates:
            LOG.info("%s results through %s", league, latest)
            # International breaks naturally cause gaps. This is an alert, never an import failure.
            if latest < date.today() - timedelta(days=28 if league == "ucl" else 21):
                LOG.warning(
                    "%s latest completed result is older than its freshness threshold", league
                )
        sync_xg(engine, season)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=current_season())
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    try:
        run(get_engine(), args.season)
    except Exception:
        LOG.exception("Daily match refresh failed. Check the last committed sync before retrying.")
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
