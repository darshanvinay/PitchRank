import hashlib
import json
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

ENGINE_REVISION = "elo-v1"


class EloConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    initial_rating: float = 1500.0
    promoted_default: float = 1400.0
    k_factor: float = Field(default=20.0, gt=0, le=100)
    home_advantage: float = Field(default=65.0, ge=0, le=300)
    rating_scale: float = Field(default=400.0, gt=0)
    goal_multiplier_scale: float = Field(default=1.0, ge=0, le=5)
    season_regression: float = Field(default=0.25, ge=0, le=1)

    @property
    def identity(self) -> dict:
        return {"engine_revision": ENGINE_REVISION, "config": self.model_dump()}

    @property
    def config_hash(self) -> str:
        raw = json.dumps(self.identity, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(raw.encode()).hexdigest()


def load_config(path: Path | None = None) -> EloConfig:
    return EloConfig() if path is None else EloConfig.model_validate_json(path.read_text())
