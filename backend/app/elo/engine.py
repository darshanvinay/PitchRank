"""Pure, zero-sum Elo updates. Expected score is NOT a win probability."""

import math
from dataclasses import dataclass

from app.core.elo import EloConfig


@dataclass(frozen=True)
class RatingUpdate:
    home_before: float
    away_before: float
    home_after: float
    away_after: float
    home_change: float
    away_change: float
    expected_home: float
    actual_home: float
    multiplier: float


def expected_score(home: float, away: float, config: EloConfig) -> float:
    if not all(math.isfinite(value) for value in (home, away)):
        raise ValueError("Ratings must be finite")
    exponent = (home - away + config.home_advantage) / config.rating_scale * math.log(10)
    # Stable logistic: exp() only receives nonpositive arguments.
    if exponent >= 0:
        return 1 / (1 + math.exp(-exponent))
    value = math.exp(exponent)
    return value / (1 + value)


def goal_multiplier(home_goals: int, away_goals: int, config: EloConfig) -> float:
    for goals in (home_goals, away_goals):
        if type(goals) is not int or goals < 0:
            raise ValueError("Goals must be non-negative integers")
    return max(1.0, config.goal_multiplier_scale * math.log1p(abs(home_goals - away_goals)))


def update_ratings(
    home: float, away: float, home_goals: int, away_goals: int, config: EloConfig
) -> RatingUpdate:
    multiplier = goal_multiplier(home_goals, away_goals, config)
    expected = expected_score(home, away, config)
    actual = 1.0 if home_goals > away_goals else (0.0 if home_goals < away_goals else 0.5)
    change = config.k_factor * multiplier * (actual - expected)
    return RatingUpdate(
        home, away, home + change, away - change, change, -change, expected, actual, multiplier
    )
