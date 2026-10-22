"""Davidson paired-comparison probabilities, separate from Elo rating updates."""

import math

import numpy as np
from pydantic import BaseModel, ConfigDict, Field

from app.core.elo import EloConfig

PREDICTION_REVISION = "davidson-v1"
OUTCOMES = ("H", "D", "A")


class PredictionConfig(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)
    elo: EloConfig = Field(default_factory=EloConfig)
    draw_strength: float = Field(default=0.7, ge=0.05, le=2.0)


def probabilities(home: float, away: float, config: PredictionConfig) -> np.ndarray:
    if not all(math.isfinite(value) for value in (home, away)):
        raise ValueError("Ratings must be finite")
    difference = (home - away + config.elo.home_advantage) / config.elo.rating_scale * math.log(10)
    if not math.isfinite(difference):
        raise ValueError("Rating difference is too large")
    logits = np.array([difference / 2, math.log(config.draw_strength), -difference / 2])
    weights = np.exp(logits - np.max(logits))
    return weights / weights.sum()
