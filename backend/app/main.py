import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager, suppress
from datetime import date
from pathlib import Path
from typing import Literal
from urllib.error import URLError

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

from app.api.data import DataUnavailable, league_data
from app.api.schemas import League, TeamDetail
from app.api.ucl_history import history_matches, history_seasons
from app.core.leagues import LeagueId, LeagueView
from app.core.season import current_season
from app.db.session import ROOT, get_engine
from app.services.season import refresh_season

logger = logging.getLogger(__name__)


def create_app(engine=None, season: str | None = None) -> FastAPI:
    database = engine if engine is not None else get_engine()
    selected_season = season or current_season()
    refresh_lock = threading.Lock()
    origins = [
        origin.strip().rstrip("/")
        for origin in os.getenv("PITCHRANK_CORS_ORIGINS", "").split(",")
        if origin.strip()
    ]
    public = os.getenv("PITCHRANK_PUBLIC") == "1"

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if os.getenv("PITCHRANK_DAILY_REFRESH") != "1":
            yield
            return

        from app.ingestion.schedule import run_daily

        refresh_task = asyncio.create_task(run_daily(selected_season))
        try:
            yield
        finally:
            refresh_task.cancel()
            with suppress(asyncio.CancelledError):
                await refresh_task

    app = FastAPI(
        title="PitchRank",
        description="Current-season European club strength ratings",
        lifespan=lifespan,
    )

    if origins:
        app.add_middleware(
            CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=[]
        )

    @app.get("/health")
    def health():
        with database.connect() as connection:
            populated = connection.execute(
                text("SELECT 1 FROM season_ratings WHERE season = :season LIMIT 1"),
                {"season": selected_season},
            ).scalar()
        if not populated:
            raise HTTPException(503, "Season ratings are unavailable.")
        return {"status": "ok"}

    @app.middleware("http")
    async def fresh_api(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    @app.exception_handler(DataUnavailable)
    async def unavailable(_: Request, exc: DataUnavailable):
        return JSONResponse(status_code=503, content={"detail": str(exc)})

    @app.exception_handler(SQLAlchemyError)
    async def database_error(_: Request, exc: SQLAlchemyError):
        logger.exception("Database operation failed", exc_info=exc)
        return JSONResponse(
            status_code=503,
            content={"detail": "The database is unavailable. Check migrations and try again."},
        )

    @app.get("/api/league", response_model=League)
    def league(league: LeagueView = "epl"):
        return league_data(database, selected_season, league)[0]

    @app.get("/api/teams/{team_id}/xg")
    def team_xg(team_id: int):
        from sqlalchemy import case, or_, select
        from sqlalchemy.orm import Session

        from app.db.models import Match, MatchXG, Team

        with Session(database) as session:
            if session.get(Team, team_id) is None:
                raise HTTPException(404, "Club not found.")
            rows = session.execute(
                select(Match, MatchXG, Team.display_name)
                .join(MatchXG, Match.id == MatchXG.match_id)
                .join(
                    Team,
                    Team.id
                    == case(
                        (Match.home_team_id == team_id, Match.away_team_id),
                        else_=Match.home_team_id,
                    ),
                )
                .where(
                    Match.status == "finished",
                    MatchXG.source == "understat",
                    or_(Match.home_team_id == team_id, Match.away_team_id == team_id),
                )
                .order_by(Match.match_date.desc(), Match.id.desc())
                .limit(40)
            ).all()
            return [
                {
                    "id": match.id,
                    "date": str(match.match_date),
                    "opponent": opponent,
                    "xg": xg.home_xg if match.home_team_id == team_id else xg.away_xg,
                    "xga": xg.away_xg if match.home_team_id == team_id else xg.home_xg,
                }
                for match, xg, opponent in rows
            ]

    @app.get("/api/teams/{team_id}/historical-elo")
    def historical_elo(team_id: int, cutoff: date):
        from app.services.historical import get_team_elo_at_date

        try:
            return {
                "team_id": team_id,
                "cutoff": str(cutoff),
                "cutoff_exclusive": True,
                "rating": get_team_elo_at_date(team_id, cutoff, engine=database),
            }
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/ucl/seasons")
    def ucl_seasons():
        return history_seasons(database, public=public)

    @app.get("/api/ucl/projection")
    def ucl_projection():
        import json

        from app.backtesting.season_projection import BUNDLED_DIRECTORY, DIRECTORY, SEASON

        paths = [
            path
            for folder in (BUNDLED_DIRECTORY, DIRECTORY)
            for path in (folder / SEASON).glob("*.json")
        ]
        if not paths:
            raise HTTPException(503, "No season projection has been published yet.")
        data = json.loads(max(paths, key=lambda path: path.name).read_text())
        inputs = data.pop("inputs")
        data["completed"] = sum(row[2] is not None for row in inputs["fixtures"])
        data["xg_clubs"] = sum(inputs["eligible"])
        return data

    @app.get("/api/ucl/bracket")
    def ucl_bracket(
        season: str = "2020-2021",
        scenario: Literal["r16_order", "observed_draw"] = "r16_order",
    ):
        from app.backtesting.tournament import forecast_tournament

        try:
            return forecast_tournament(database, season, scenario)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc

    @app.get("/api/ucl/matches")
    def ucl_matches(
        season: str | None = None,
        stage: Literal[
            "group", "league", "playoff", "round_of_16", "quarterfinal", "semifinal", "final"
        ]
        | None = None,
        team_id: int | None = None,
    ):
        from app.ingestion.historical import season_start

        try:
            year = season_start(season) if season else None
            if year is None and team_id is None:
                raise ValueError("Provide a season or a team_id for historical results")
            if year is not None and not 2005 <= year <= 2025:
                raise ValueError(
                    "History supports 2005/06–2025/26; unavailable seasons are listed explicitly"
                )
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        return history_matches(database, season, stage, team_id, public=public)

    @app.get("/api/teams/{team_id}", response_model=TeamDetail)
    def team(team_id: int, league: LeagueId = "epl"):
        data, results, history = league_data(database, selected_season, league)
        club = next((t for t in data["clubs"] if t["id"] == team_id), None)
        if club is None:
            raise HTTPException(404, "This club is not in the selected league season.")
        return {
            "season": selected_season,
            "club": club,
            "history": history[team_id],
            "results": [r for r in results if team_id in (r["home_id"], r["away_id"])],
        }

    @app.post("/api/refresh", response_model=League)
    def refresh(request: Request, league: LeagueView = "epl"):
        if public:
            raise HTTPException(403, "Imports are managed by the server.")
        # The development Vite proxy preserves Host for local imports.
        origin = request.headers.get("origin")
        if origin and origin.rstrip("/") != str(request.base_url).rstrip("/"):
            raise HTTPException(403, "Refresh must come from this application's origin.")
        if not refresh_lock.acquire(blocking=False):
            raise HTTPException(409, "A refresh is already running. Please wait.")
        try:
            refresh_season(database, selected_season, league=league)
            return league_data(database, selected_season, league)[0]
        except (ValueError, OSError, URLError) as exc:
            logger.warning("Manual refresh failed: %s", exc)
            raise HTTPException(
                502, "Results could not be updated. Your stored data is unchanged; try again later."
            ) from exc
        finally:
            refresh_lock.release()

    dist = ROOT / "frontend" / "dist"
    if dist.exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")
        app.mount("/crests", StaticFiles(directory=dist / "crests"), name="crests")

        @app.get("/{path:path}", include_in_schema=False)
        def frontend(path: str):
            if path.startswith("api/"):
                raise HTTPException(404, "Unknown API endpoint")
            return FileResponse(Path(dist) / "index.html")

    return app


app = create_app()
