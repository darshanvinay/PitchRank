"""Read-only, cutoff-safe reconstruction using the existing shared Elo replay."""

import hashlib
import json
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, Team
from app.elo.season import replay_season
from app.services.ratings import played
from app.services.season import fingerprint


def historical_elo_snapshot(
    engine,
    cutoff_date: date,
    config: SeasonConfig | None = None,
    start_date: date = date(2010, 7, 1),
):
    if type(cutoff_date) is not date or cutoff_date <= start_date:
        raise ValueError("Cutoff must be a date after reconstruction start")
    config = config or SeasonConfig()
    with Session(engine) as session:
        matches = session.scalars(
            select(Match).where(
                Match.league.in_([*LEAGUES, "ucl"]),
                Match.status == "finished",
                Match.match_date >= start_date,
                Match.match_date < cutoff_date,
            )
        ).all()
    members = {t for m in matches for t in (m.home_team_id, m.away_team_id)}
    # No current squad values, future season membership, promotion lists or future matches.
    result, _ = replay_season(
        played(matches),
        dict.fromkeys(members),
        config,
        offseason_regression=config.elo.season_regression,
    )
    return {
        "cutoff": cutoff_date.isoformat(),
        "cutoff_exclusive": True,
        "start": start_date.isoformat(),
        "matches": len(matches),
        "latest_match": max((m.match_date for m in matches), default=None),
        "parameters": config.model_dump(),
        "input_hash": fingerprint(matches, [], config),
        "config_hash": hashlib.sha256(
            json.dumps(config.model_dump(), sort_keys=True).encode()
        ).hexdigest(),
        "ratings": result.ratings,
    }


def get_team_elo_at_date(
    team_id: int, cutoff_date: date, *, engine=None, config: SeasonConfig | None = None
) -> float:
    from app.db.session import get_engine

    engine = engine if engine is not None else get_engine()
    with Session(engine) as session:
        if session.get(Team, team_id) is None:
            raise ValueError("Unknown club ID")
    config = config or SeasonConfig()
    snapshot = historical_elo_snapshot(engine, cutoff_date, config)
    return snapshot["ratings"].get(team_id, config.elo.initial_rating)
