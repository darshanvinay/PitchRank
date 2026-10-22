from datetime import date
from pathlib import Path
from urllib.parse import urlparse

import numpy as np
import pandas as pd
from sqlalchemy import select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.db.models import SquadValue
from app.ingestion.historical import ImportValidationError, season_start
from app.ingestion.teams import resolve_team, seed_teams, verified_roster


def import_squads(engine: Engine, path: Path, season: str, league: str = "epl") -> int:
    season_start(season)
    verified_roster(league, season)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    required = {"team", "value_eur", "as_of", "source_url"}
    if not required.issubset(frame.columns) or frame.empty:
        raise ImportValidationError(
            "Squad CSV needs team,value_eur,as_of,source_url and at least one row"
        )
    with Session(engine) as session, session.begin():
        seed_teams(session, league)
        seen = set()
        for index, row in frame.iterrows():
            try:
                team_id = resolve_team(session, row.team, "football-data.co.uk", league)
                value = float(row.value_eur)
                day = date.fromisoformat(row.as_of)
                url = urlparse(row.source_url)
                if not np.isfinite(value) or value <= 0:
                    raise ValueError("Squad value must be positive and finite")
                if day > date.today():
                    raise ValueError("Valuation date is in the future")
                if url.scheme not in ("http", "https") or not url.netloc:
                    raise ValueError("A documented source URL is required")
                if team_id in seen:
                    raise ValueError("Duplicate club in squad values")
                seen.add(team_id)
                item = session.scalar(
                    select(SquadValue).where(
                        SquadValue.team_id == team_id,
                        SquadValue.season == season,
                        SquadValue.league == league,
                    )
                )
                if item is None:
                    item = SquadValue(team_id=team_id, season=season, league=league)
                    session.add(item)
                item.value_eur, item.as_of, item.source_url = value, day, row.source_url
            except ValueError as exc:
                raise ImportValidationError(f"Squad CSV row {index + 2}: {exc}") from exc
        return len(seen)
