import os
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field

from app.core.elo import EloConfig


class SeasonConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    elo: EloConfig = Field(default_factory=EloConfig)
    squad_log_scale: float = Field(default=60.0, ge=0, le=200)
    # Frozen from the documented EPL September 2026 snapshot; shared by every league.
    squad_reference_eur: float = Field(default=556_425_000.0, gt=0)
    history_start: str = "2024-2025"
    domestic_importance: float = Field(default=1.0, gt=0, le=5)
    ucl_league_importance: float = Field(default=1.25, gt=0, le=5)
    ucl_knockout_importance: float = Field(default=1.50, gt=0, le=5)
    ucl_finals_importance: float = Field(default=1.75, gt=0, le=5)
    squad_cap: float = Field(default=100.0, ge=0, le=200)


def current_season() -> str:
    day = datetime.now(ZoneInfo("America/Toronto"))
    start = day.year if day.month >= 7 else day.year - 1
    return os.getenv("PITCHRANK_SEASON", f"{start}-{start + 1}")


def season_config() -> SeasonConfig:
    return SeasonConfig(
        squad_log_scale=float(os.getenv("SQUAD_LOG_SCALE", "60")),
        squad_reference_eur=float(os.getenv("SQUAD_REFERENCE_EUR", "556425000")),
        history_start=os.getenv("ELO_HISTORY_START", "2024-2025"),
        domestic_importance=float(os.getenv("ELO_DOMESTIC_IMPORTANCE", "1.0")),
        ucl_league_importance=float(os.getenv("ELO_UCL_LEAGUE_IMPORTANCE", "1.25")),
        ucl_knockout_importance=float(os.getenv("ELO_UCL_KNOCKOUT_IMPORTANCE", "1.5")),
        ucl_finals_importance=float(os.getenv("ELO_UCL_FINALS_IMPORTANCE", "1.75")),
        squad_cap=float(os.getenv("SQUAD_RATING_CAP", "100")),
    )
