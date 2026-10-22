from dataclasses import dataclass

import numpy as np
import pandas as pd

from app.elo.replay import PlayedMatch, replay
from app.ingestion.historical import season_start
from app.predictions.model import OUTCOMES, PredictionConfig, probabilities


@dataclass(frozen=True)
class ChronologicalSplit:
    train: tuple[str, ...]
    validation: tuple[str, ...]
    test: tuple[str, ...]

    def validate(self, matches: list[PlayedMatch]) -> None:
        periods = [self.train, self.validation, self.test]
        if any(not period for period in periods):
            raise ValueError("Training, validation, and test periods must each contain seasons")
        flattened = [season for period in periods for season in period]
        for season in flattened:
            season_start(season)
        if flattened != sorted(set(flattened)):
            raise ValueError("Split seasons must be unique and strictly chronological")
        available = {match.season for match in matches}
        if set(flattened) != available:
            raise ValueError("Split must assign every selected season exactly once")
        dates = [[m.match_date for m in matches if m.season in period] for period in periods]
        if any(not dates_in_period for dates_in_period in dates):
            raise ValueError("Each split needs completed matches")
        if not max(dates[0]) < min(dates[1]) or not max(dates[1]) < min(dates[2]):
            raise ValueError("Split dates overlap; chronological boundaries must be disjoint")


def outcome(match: PlayedMatch) -> str:
    return (
        "H"
        if match.home_goals > match.away_goals
        else ("A" if match.home_goals < match.away_goals else "D")
    )


def walk_forward(matches: list[PlayedMatch], config: PredictionConfig) -> pd.DataFrame:
    records = []

    def predict(match: PlayedMatch, home: float, away: float) -> None:
        values = probabilities(home, away, config)
        records.append(
            {
                "match_id": match.id,
                "season": match.season,
                "match_date": match.match_date.isoformat(),
                "kickoff_at": match.kickoff_at.isoformat() if match.kickoff_at else None,
                "home_team_id": match.home_team_id,
                "away_team_id": match.away_team_id,
                "home_rating": home,
                "away_rating": away,
                "p_home": float(values[0]),
                "p_draw": float(values[1]),
                "p_away": float(values[2]),
            }
        )

    replay(matches, config.elo, before_match=predict)
    if not records:
        raise ValueError("No completed matches available for walk-forward replay")
    # Outcomes enter the evaluation table only after every probability is recorded.
    actual = {match.id: outcome(match) for match in matches}
    return pd.DataFrame(records).assign(actual=lambda frame: frame.match_id.map(actual))


def training_frequencies(matches: list[PlayedMatch]) -> np.ndarray:
    if not matches:
        raise ValueError("Training frequencies need historical matches")
    counts = np.array([sum(outcome(m) == label for m in matches) for label in OUTCOMES])
    # Fixed Laplace smoothing prevents log(0) for absent outcomes in small training samples.
    return (counts + 1) / (len(matches) + 3)


def frequency_predictions(reference: pd.DataFrame, frequencies: np.ndarray) -> pd.DataFrame:
    frame = reference.copy()
    frame[["p_home", "p_draw", "p_away"]] = np.tile(frequencies, (len(frame), 1))
    return frame
