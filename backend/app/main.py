import logging
import threading
from pathlib import Path
from urllib.error import URLError

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.data import DataUnavailable, league_data
from app.api.schemas import League, TeamDetail
from app.core.leagues import LeagueId, LeagueView
from app.core.season import current_season
from app.db.session import ROOT, get_engine
from app.services.season import refresh_season

logger = logging.getLogger(__name__)


def create_app(engine=None, season: str | None = None) -> FastAPI:
    app = FastAPI(title="PitchRank", description="Current-season European club strength ratings")
    database = engine if engine is not None else get_engine()
    selected_season = season or current_season()
    refresh_lock = threading.Lock()

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
        # Local manual update only; reject cross-site form submissions. The development Vite
        # proxy preserves Host, and production serves the frontend on the same origin.
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
