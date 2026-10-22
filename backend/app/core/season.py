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
    squad_cap: float = Field(default=100.0, ge=0, le=200)


def current_season() -> str:
    day = datetime.now(ZoneInfo("America/Toronto"))
    start = day.year if day.month >= 7 else day.year - 1
    return os.getenv("PITCHRANK_SEASON", f"{start}-{start + 1}")


def season_config() -> SeasonConfig:
    return SeasonConfig(
        squad_log_scale=float(os.getenv("SQUAD_LOG_SCALE", "60")),
        squad_reference_eur=float(os.getenv("SQUAD_REFERENCE_EUR", "556425000")),
        squad_cap=float(os.getenv("SQUAD_RATING_CAP", "100")),
    )
