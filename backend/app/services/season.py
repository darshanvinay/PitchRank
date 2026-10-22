import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.core.leagues import competition
from app.core.season import SeasonConfig, season_config
from app.db.models import Match, SeasonHistory, SeasonRating, SquadValue, Team
from app.db.session import ROOT
from app.elo.season import replay_season
from app.ingestion.historical import download_season, import_csv
from app.ingestion.squads import import_squads
from app.ingestion.teams import verified_roster
from app.services.ratings import input_hash, played


def fingerprint(matches: list[Match], values: list[SquadValue], config: SeasonConfig) -> str:
    data = {
        "matches": input_hash(matches),
        "config": config.model_dump(),
        "squads": sorted((v.team_id, v.value_eur, str(v.as_of), v.source_url) for v in values),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def calculate_season(
    bind: Engine | Connection, season: str, config: SeasonConfig | None = None, league: str = "epl"
) -> dict:
    info = competition(league)
    config = config or season_config()
    with Session(bind) as session, session.begin():
        matches = session.scalars(
            select(Match).where(
                Match.season == season, Match.league == league, Match.status == "finished"
            )
        ).all()
        squads = session.scalars(
            select(SquadValue).where(SquadValue.season == season, SquadValue.league == league)
        ).all()
        roster = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
        roster |= {v.team_id for v in squads}
        if len(roster) != info.club_count:
            raise ValueError(
                f"Expected {info.club_count} {info.name} clubs for {season}, found {len(roster)}"
            )
        names = set(
            session.scalars(
                select(Team.canonical_name).where(Team.id.in_(roster), Team.league == league)
            )
        )
        verified = verified_roster(league, season)
        if len(names) != len(roster) or (verified is not None and names != verified):
            raise ValueError("Match and valuation clubs do not match the selected league roster")
        lookup = {v.team_id: v.value_eur for v in squads}
        result, initial = replay_season(played(matches), {t: lookup.get(t) for t in roster}, config)
        signature = fingerprint(matches, squads, config)
        session.execute(
            delete(SeasonHistory).where(
                SeasonHistory.match_id.in_(
                    select(Match.id).where(Match.season == season, Match.league == league)
                )
            )
        )
        session.execute(
            delete(SeasonRating).where(SeasonRating.season == season, SeasonRating.league == league)
        )
        for team in roster:
            session.add(
                SeasonRating(
                    league=league,
                    team_id=team,
                    season=season,
                    initial_rating=initial[team],
                    rating=result.ratings[team],
                    input_hash=signature,
                )
            )
        for entry in result.entries:
            u = entry.update
            for team, before, after, delta in (
                (entry.match.home_team_id, u.home_before, u.home_after, u.home_change),
                (entry.match.away_team_id, u.away_before, u.away_after, u.away_change),
            ):
                session.add(
                    SeasonHistory(
                        match_id=entry.match.id,
                        team_id=team,
                        rating_before=before,
                        rating_after=after,
                        rating_change=delta,
                        sequence=entry.sequence,
                    )
                )
        return {
            "season": season,
            "teams": len(roster),
            "matches": len(matches),
            "squad_values": len(squads),
            "history_rows": len(result.entries) * 2,
        }


def refresh_season(
    engine: Engine,
    season: str,
    results: Path | None = None,
    squads: Path | None = None,
    league: str = "epl",
) -> dict:
    # Download before locking. A provider failure leaves the usable snapshot intact.
    info = competition(league)
    path = results or download_season(season, ROOT / "data" / "raw", league)
    if squads is not None and not squads.exists():
        raise FileNotFoundError(f"Squad values file not found: {squads}")
    squads = squads or ROOT / "data" / "squads" / (
        f"{season}.csv" if league == "epl" else f"{league}-{season}.csv"
    )
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            summary = import_csv(
                connection,
                path,
                season,
                location=str(path.resolve())
                if results
                else (
                    f"https://www.football-data.co.uk/mmz4281/{season[2:4]}{season[7:9]}/{info.division}.csv"
                ),
                league=league,
            )
            if squads.exists():
                import_squads(connection, squads, season, league)
            calculation = calculate_season(connection, season, league=league)
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {**calculation, "import": asdict(summary)}
