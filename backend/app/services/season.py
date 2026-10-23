import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.engine import Connection, Engine
from sqlalchemy.orm import Session

from app.core.leagues import LEAGUES, competition
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
        "competitions": sorted((m.id, m.league, m.stage, m.neutral) for m in matches),
        "config": config.model_dump(),
        "squads": sorted((v.team_id, v.value_eur, str(v.as_of), v.source_url) for v in values),
    }
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def calculate_season(
    bind: Engine | Connection, season: str, config: SeasonConfig | None = None, league: str = "epl"
) -> dict:
    """One connected replay, persisted through the existing season snapshots/history tables."""
    competition(league)
    config = config or season_config()
    with Session(bind) as session, session.begin():
        matches = session.scalars(
            select(Match).where(
                Match.season >= config.history_start,
                Match.season <= season,
                Match.league.in_([*LEAGUES, "ucl"]),
                Match.status == "finished",
            )
        ).all()
        squads = session.scalars(select(SquadValue).where(SquadValue.season <= season)).all()
        teams = {t.id: t for t in session.scalars(select(Team))}
        # Validate domestic membership; retain historical and UCL-only clubs in the pool.
        memberships = {}
        for key, info in LEAGUES.items():
            roster = {m.home_team_id for m in matches if m.league == key and m.season == season}
            roster |= {m.away_team_id for m in matches if m.league == key and m.season == season}
            roster |= {v.team_id for v in squads if v.league == key and v.season == season}
            if not roster:
                continue
            if len(roster) != info.club_count:
                raise ValueError(
                    f"Expected {info.club_count} {info.name} clubs for {season}, "
                    f"found {len(roster)}"
                )
            names = {teams[t].canonical_name for t in roster if teams[t].league == key}
            verified = verified_roster(key, season)
            if len(names) != len(roster) or (verified is not None and names != verified):
                raise ValueError(
                    "Match and valuation clubs do not match the selected league roster"
                )
            memberships[key] = roster
        roster = {m.home_team_id for m in matches} | {m.away_team_id for m in matches}
        roster |= set().union(*memberships.values()) if memberships else set()
        lookup = {}
        for value in sorted(squads, key=lambda v: (v.as_of, v.id)):
            lookup.setdefault(
                value.team_id, value.value_eur
            )  # One initial prior, never a seasonal bonus.
        result, initial = replay_season(played(matches), {t: lookup.get(t) for t in roster}, config)
        signature = fingerprint(matches, squads, config)
        session.execute(
            delete(SeasonHistory).where(SeasonHistory.match_id.in_([m.id for m in matches]))
        )
        session.execute(
            delete(SeasonRating).where(
                SeasonRating.season >= config.history_start, SeasonRating.season <= season
            )
        )
        running = initial.copy()
        beginnings, endings = {}, {}
        for entry in result.entries:
            match, update = entry.match, entry.update
            for team, before, after, delta in (
                (match.home_team_id, update.home_before, update.home_after, update.home_change),
                (match.away_team_id, update.away_before, update.away_after, update.away_change),
            ):
                beginnings.setdefault((match.season, team), before)
                endings[(match.season, team)] = after
                running[team] = after
                session.add(
                    SeasonHistory(
                        match_id=match.id,
                        team_id=team,
                        rating_before=before,
                        rating_after=after,
                        rating_change=delta,
                        sequence=entry.sequence,
                    )
                )
        for group in memberships.values():
            for team in group:
                beginnings.setdefault((season, team), running[team])
                endings.setdefault((season, team), running[team])
        for (year, team), rating in endings.items():
            session.add(
                SeasonRating(
                    team_id=team,
                    season=year,
                    league=teams[team].league,
                    initial_rating=beginnings[(year, team)],
                    rating=rating,
                    input_hash=signature,
                )
            )
        selected = [m for m in matches if m.league == league and m.season == season]
        return {
            "season": season,
            "teams": len(memberships.get(league, set())),
            "matches": len(selected),
            "squad_values": sum(v.league == league and v.season == season for v in squads),
            "history_rows": 2 * len(selected),
            "pool_matches": len(matches),
            "pool_teams": len(roster),
        }


def refresh_season(
    engine: Engine,
    season: str,
    results: Path | None = None,
    squads: Path | None = None,
    league: str = "epl",
) -> dict:
    from app.ingestion.champions import download_champions, import_champions
    from app.ingestion.historical import season_start

    targets = list(LEAGUES) if league == "europe" else [league]
    for key in targets:
        competition(key)
    start = season_start(season_config().history_start)
    end = season_start(season)
    if league == "europe" and (results is not None or squads is not None):
        raise ValueError("Local result/value overrides require a domestic league selection")
    years = (
        [f"{year}-{year + 1}" for year in range(start, end + 1)] if league == "europe" else [season]
    )
    jobs = []
    for year in years:
        for key in targets:
            cached = ROOT / "data/raw" / f"{competition(key).division}-{year}.csv"
            path = results or (
                cached
                if year != season and cached.exists()
                else download_season(year, ROOT / "data/raw", key)
            )
            jobs.append((key, year, path))
    ucl_jobs = []
    if results is None:
        for year in years:
            cached = ROOT / "data/raw" / f"UCL-{year}.csv"
            path = (
                cached
                if year != season and cached.exists()
                else download_champions(year, ROOT / "data/raw")
            )
            ucl_jobs.append((year, path))
    if squads is not None and not squads.exists():
        raise FileNotFoundError(f"Squad values file not found: {squads}")
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            summary = None
            for key, year, path in jobs:
                summary = import_csv(
                    connection,
                    path,
                    year,
                    league=key,
                    location=(
                        str(path.resolve())
                        if results
                        else f"https://www.football-data.co.uk/mmz4281/{year[2:4]}{year[7:9]}/{competition(key).division}.csv"
                    ),
                )
            for key in targets:
                path = squads or ROOT / "data/squads" / (
                    f"{season}.csv" if key == "epl" else f"{key}-{season}.csv"
                )
                if path.exists():
                    import_squads(connection, path, season, key)
            for year, path in ucl_jobs:
                import_champions(connection, path, year)
            calculation = calculate_season(connection, season, league=targets[0])
            connection.commit()
        except Exception:
            connection.rollback()
            raise
    return {**calculation, "import": asdict(summary)}
