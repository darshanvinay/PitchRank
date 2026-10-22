import hashlib
import json
from dataclasses import dataclass

from sqlalchemy import delete, select, text, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.elo import EloConfig
from app.db.models import Match, ModelVersion, RatingHistory, Team
from app.elo.replay import PlayedMatch, replay


@dataclass(frozen=True)
class RebuildSummary:
    model_version_id: int
    config_hash: str
    matches: int
    history_rows: int
    rebuilt: bool
    latest_season: str


def input_hash(matches: list[Match]) -> str:
    values = sorted(
        (
            m.id,
            m.season,
            str(m.match_date),
            str(m.kickoff_at),
            m.home_team_id,
            m.away_team_id,
            m.home_goals,
            m.away_goals,
            m.status,
        )
        for m in matches
    )
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def played(matches: list[Match]) -> list[PlayedMatch]:
    return [
        PlayedMatch(
            m.id,
            m.season,
            m.match_date,
            m.kickoff_at,
            m.home_team_id,
            m.away_team_id,
            m.home_goals,
            m.away_goals,
        )
        for m in matches
        if m.status == "finished"
    ]


def rebuild_ratings(engine: Engine, config: EloConfig, force: bool = False) -> RebuildSummary:
    with Session(engine) as session:
        # Acquire SQLite's writer lock BEFORE reading matches. A concurrent importer cannot
        # change the replay input while a rebuild is in progress; errors roll back old history.
        session.execute(text("BEGIN IMMEDIATE"))
        try:
            matches = session.scalars(
                select(Match).where(Match.league == "epl").order_by(Match.id)
            ).all()
            completed = played(matches)
            if not completed:
                raise ValueError("No finished matches available; import historical results first")
            fingerprint = input_hash(matches)
            model = session.scalar(
                select(ModelVersion).where(ModelVersion.config_hash == config.config_hash)
            )
            if model is None:
                model = ModelVersion(config_hash=config.config_hash, parameters=config.identity)
                session.add(model)
                session.flush()
            latest = max(m.season for m in completed)
            if not force and not model.needs_rebuild and model.input_hash == fingerprint:
                return RebuildSummary(
                    model.id, model.config_hash, len(completed), len(completed) * 2, False, latest
                )
            result = replay(completed, config)
            session.execute(delete(RatingHistory).where(RatingHistory.model_version_id == model.id))
            for entry in result.entries:
                for team, before, after, delta in (
                    (
                        entry.match.home_team_id,
                        entry.update.home_before,
                        entry.update.home_after,
                        entry.update.home_change,
                    ),
                    (
                        entry.match.away_team_id,
                        entry.update.away_before,
                        entry.update.away_after,
                        entry.update.away_change,
                    ),
                ):
                    session.add(
                        RatingHistory(
                            match_id=entry.match.id,
                            team_id=team,
                            model_version_id=model.id,
                            rating_before=before,
                            rating_after=after,
                            rating_change=delta,
                            sequence=entry.sequence,
                        )
                    )
            session.execute(update(Match).values(processed=False))
            session.execute(
                update(Match)
                .where(Match.status == "finished", Match.league == "epl")
                .values(processed=True)
            )
            model.needs_rebuild = False
            model.input_hash = fingerprint
            session.commit()
            return RebuildSummary(
                model.id, model.config_hash, len(completed), len(result.entries) * 2, True, latest
            )
        except Exception:
            session.rollback()
            raise


def rankings(engine: Engine, config: EloConfig) -> dict:
    with Session(engine) as session:
        # One read snapshot: imports/rebuilds cannot mix an old model with new history.
        session.execute(text("BEGIN"))
        model = session.scalar(
            select(ModelVersion).where(ModelVersion.config_hash == config.config_hash)
        )
        matches = session.scalars(
            select(Match).where(Match.league == "epl").order_by(Match.id)
        ).all()
        if model is None or model.needs_rebuild or model.input_hash != input_hash(matches):
            raise ValueError("Ratings are missing or stale; run 'pitchrank elo rebuild' first")
        finished = [m for m in matches if m.status == "finished"]
        if not finished:
            raise ValueError("No finished matches available")
        season = max(m.season for m in finished)
        active = {
            team
            for m in finished
            if m.season == season
            for team in (m.home_team_id, m.away_team_id)
        }
        history = session.scalars(
            select(RatingHistory)
            .where(RatingHistory.model_version_id == model.id)
            .order_by(RatingHistory.sequence)
        ).all()
        latest = {}
        for row in history:
            latest[row.team_id] = row.rating_after
        teams = session.scalars(select(Team).where(Team.id.in_(active))).all()
        rows = sorted(
            ({"team_id": t.id, "team": t.display_name, "elo": latest[t.id]} for t in teams),
            key=lambda r: (-r["elo"], r["team"]),
        )
        return {
            "model_version_id": model.id,
            "config_hash": model.config_hash,
            "season": season,
            "as_of": str(max(m.match_date for m in finished)),
            "note": "Historical Elo snapshot; not the official league table or live rankings.",
            "rankings": [dict(rank=i, **row) for i, row in enumerate(rows, 1)],
        }
