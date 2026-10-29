from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_knockout import dataset as knockout_dataset

from app.backtesting.europe_experiment import (
    EVALUATION,
    TRAIN,
    VALIDATION,
    adjusted_rows,
    calibrated_probability,
    european_features,
    select_parameters,
)
from app.backtesting.knockout import backtest_round_of_16
from app.db.models import Match

dataset = knockout_dataset


def test_offset_is_identity_at_zero_and_symmetric():
    assert calibrated_probability(0.123456789, 0.2, 0) == 0.123456789
    assert calibrated_probability(0.4, 0, 8) == 0.4
    assert calibrated_probability(0.4, 0.1, 4) > 0.4
    assert calibrated_probability(0.6, -0.1, 4) == pytest.approx(
        1 - calibrated_probability(0.4, 0.1, 4)
    )
    for p, d, b in [(0, 0, 1), (1, 0, 1), (0.5, float("nan"), 1)]:
        with pytest.raises(ValueError):
            calibrated_probability(p, d, b)


def test_residuals_cutoff_decay_and_future_results_do_not_change_predictions(dataset):
    with Session(dataset) as session, session.begin():
        session.add(
            Match(
                league="ucl",
                season="2020-2021",
                match_date=date(2020, 10, 1),
                home_team_id=7,
                away_team_id=8,
                home_goals=0,
                away_goals=2,
                status="finished",
                source="test",
                stage="league",
            )
        )
    cutoff = date(2021, 2, 16)
    before = european_features(dataset, cutoff)
    baseline = backtest_round_of_16(dataset)
    features = {baseline["season"]: before}
    predictions = adjusted_rows([baseline], features, 4)
    assert before["ucl_matches"] == 1
    assert before["features"]["None"][7] < 0
    assert before["features"]["None"][7] == -before["features"]["None"][8]
    assert abs(before["features"]["0.5"][7]) < abs(before["features"]["4"][7])
    assert before["features"]["None"][1] == 0  # No European evidence, no club-name bonus.
    assert abs(before["features"]["None"][7]) < 1 / 11  # Shrinkage, not accumulated wins.
    identity = adjusted_rows([baseline], features, 0)
    assert [r["p_a"] for r in identity] == [r["p_a"] for r in baseline["predictions"]]
    with Session(dataset) as session, session.begin():
        future = session.scalar(select(Match).where(Match.match_date == date(2021, 3, 9)))
        future.home_goals = 12
        session.add(
            Match(
                league="ucl",
                season="2020-2021",
                match_date=cutoff,
                home_team_id=1,
                away_team_id=3,
                home_goals=20,
                away_goals=0,
                status="finished",
                source="test",
                stage="league",
            )
        )
    after = european_features(dataset, cutoff)
    assert before == after
    # A future score can change a label, never a residual feature or forecast.
    changed = adjusted_rows([baseline], {baseline["season"]: after}, 4)
    assert changed == predictions
    with pytest.raises(ValueError):
        european_features(dataset, cutoff, half_lives=(0,))
    with pytest.raises(ValueError):
        european_features(dataset, cutoff, prior_matches=0)


def test_selection_uses_earlier_labels_only_and_is_deterministic():
    assert max(TRAIN) < min(VALIDATION) < max(VALIDATION) < min(EVALUATION)
    row = dict(team_a_id=1, team_b_id=2, p_a=0.5, actual_winner=1, predicted_winner=1)
    training = [{"season": "train", "predictions": [row]}]
    validation = [{"season": "validation", "predictions": [row]}]
    features = {
        s: {"features": {str(h): {1: 0.1, 2: -0.1} for h in (None, 0.5, 1, 2, 4)}}
        for s in ("train", "validation", "future")
    }
    selected, _ = select_parameters(training, validation, features)
    features["future"]["features"]["None"] = {1: -999, 2: 999}
    assert select_parameters(training, validation, features)[0] == selected
    assert selected["B"]["coefficient"] == 8
    assert selected["C"]["coefficient"] == 8
