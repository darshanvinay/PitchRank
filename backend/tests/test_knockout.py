from datetime import date
from types import SimpleNamespace

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import (
    TieFixture,
    actual_winner,
    advancement_metrics,
    advancement_probability,
    backtest_round_of_16,
    extra_time_distribution,
    extra_time_winner,
    regulation_winner,
    score_distribution,
)
from app.db.models import Base, Match, Team
from app.db.session import get_engine
from app.predictions.model import PredictionConfig, probabilities


def test_old_away_goals_including_extra_time_and_abolition():
    assert regulation_winner((0, 0), (1, 1), True) == "A"
    assert regulation_winner((0, 0), (1, 1), False) is None
    assert regulation_winner((1, 2), (0, 1), True) == "B"
    assert regulation_winner((3, 0), (1, 0), True) == "A"
    assert extra_time_winner(1, 1, True) == "A"
    assert extra_time_winner(1, 1, False) is None
    assert extra_time_winner(0, 0, True) is None
    assert extra_time_winner(2, 1, True) == "B"


def test_actual_advancement_uses_separate_extra_time_and_penalty_scores():
    first = SimpleNamespace(home_goals=0, away_goals=0)
    second = SimpleNamespace(
        home_goals=0,
        away_goals=0,
        ucl_detail={
            "extra_time_home": 1,
            "extra_time_away": 1,
            "penalties_home": 4,
            "penalties_away": 3,
        },
    )
    assert actual_winner(first, second, False) == "B"
    second.ucl_detail.update(penalties_home=None, penalties_away=None)
    assert actual_winner(first, second, True) == "A"
    with pytest.raises(ValueError, match="shootout"):
        actual_winner(first, second, False)
    second.ucl_detail = {}
    with pytest.raises(ValueError, match="extra-time"):
        actual_winner(first, second, False)


def test_probability_adapter_preserves_existing_model_and_conserves_mass():
    config = PredictionConfig()
    conditional = [{(1, 0): 0.5, (2, 0): 0.5}, {(0, 0): 0.5, (1, 1): 0.5}, {(0, 1): 1.0}]
    pmf = score_distribution(1600, 1500, conditional, config)
    expected = probabilities(1600, 1500, config)
    assert sum(p for (h, a), p in pmf.items() if h > a) == pytest.approx(expected[0])
    assert sum(p for (h, a), p in pmf.items() if h == a) == pytest.approx(expected[1])
    et = extra_time_distribution(pmf)
    assert sum(et.values()) == pytest.approx(1)
    assert sum(h * p for (h, a), p in et.items()) == pytest.approx(
        sum(h * p for (h, a), p in pmf.items()) / 3
    )
    neutral = score_distribution(1500, 1500, conditional, config, True)
    assert sum(p for (h, a), p in neutral.items() if h > a) == pytest.approx(
        sum(p for (h, a), p in neutral.items() if h < a)
    )
    symmetric = [{(1, 0): 1.0}, {(0, 0): 1.0}, {(0, 1): 1.0}]
    p = advancement_probability(
        TieFixture(1, 2, True, True), {1: 1500, 2: 1500}, symmetric, config, False
    )
    assert p == pytest.approx(0.5)


def test_binary_metrics_have_explicit_brier_convention():
    records = [
        dict(team_a_id=1, p_a=0.8, actual_winner=1, predicted_winner=1),
        dict(team_a_id=1, p_a=0.6, actual_winner=2, predicted_winner=1),
    ]
    measured = advancement_metrics(records)
    assert measured["ties"] == 2 and measured["correct"] == 1 and measured["accuracy"] == 0.5
    assert measured["brier_score"] == pytest.approx((0.2**2 + 0.6**2) / 2)
    import math

    assert measured["log_loss"] == pytest.approx(-(math.log(0.8) + math.log(0.4)) / 2)


@pytest.fixture
def dataset(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'knockout.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        for i in range(1, 17):
            session.add(
                Team(id=i, canonical_name=f"Club {i}", display_name=f"Club {i}", league="epl")
            )
        session.flush()
        for i in range(8):
            a, b = 2 * i + 1, 2 * i + 2
            session.add(
                Match(
                    league="epl",
                    season="2020-2021",
                    match_date=date(2020, 9, 1),
                    home_team_id=a,
                    away_team_id=b,
                    home_goals=2,
                    away_goals=0,
                    status="finished",
                    source="test",
                    stage="domestic",
                )
            )
            for leg, day, h, aw, hg, ag in [
                (1, date(2021, 2, 16), a, b, 2, 0),
                (2, date(2021, 3, 9), b, a, 0, 1),
            ]:
                session.add(
                    Match(
                        league="ucl",
                        season="2020-2021",
                        match_date=day,
                        home_team_id=h,
                        away_team_id=aw,
                        home_goals=hg,
                        away_goals=ag,
                        status="finished",
                        source="test",
                        stage="knockout",
                        ucl_detail={"round": "round_of_16", "tie_id": str(i), "leg": leg},
                    )
                )
        for day, h, aw, hg, ag in [(date(2021, 1, 1), 1, 3, 0, 0), (date(2021, 1, 2), 4, 6, 0, 1)]:
            session.add(
                Match(
                    league="epl",
                    season="2020-2021",
                    match_date=day,
                    home_team_id=h,
                    away_team_id=aw,
                    home_goals=hg,
                    away_goals=ag,
                    status="finished",
                    source="test",
                    stage="domestic",
                )
            )
    yield engine
    engine.dispose()


def test_future_scores_change_labels_but_not_any_predictions_or_calibration(dataset):
    first = backtest_round_of_16(dataset)
    assert first["metrics"]["ties"] == 8
    assert first["cutoff"] == "2021-02-16" and first["latest_input_match"] < "2021-02-16"
    assert first["snapshot_matches"] == first["score_calibration_matches"] == 10
    with Session(dataset) as session, session.begin():
        match = session.scalar(
            select(Match).where(Match.league == "ucl", Match.match_date == date(2021, 3, 9))
        )
        match.home_goals = 9
        session.add(
            Match(
                league="epl",
                season="2020-2021",
                match_date=date(2021, 2, 17),
                home_team_id=1,
                away_team_id=3,
                home_goals=0,
                away_goals=20,
                status="finished",
                source="test",
                stage="domestic",
            )
        )
    second = backtest_round_of_16(dataset)
    for key in ["input_hash", "config_hash", "score_calibration_matches", "snapshot_matches"]:
        assert first[key] == second[key]
    for before, after in zip(first["predictions"], second["predictions"], strict=True):
        assert {k: v for k, v in before.items() if k != "actual_winner"} == {
            k: v for k, v in after.items() if k != "actual_winner"
        }
    assert first["metrics"] != second["metrics"]


def test_incomplete_ties_and_duplicate_evaluation_rejected(dataset):
    from app.backtesting.knockout import backtest_seasons

    with pytest.raises(ValueError, match="Duplicate"):
        backtest_seasons(dataset, ["2020-2021", "2020-2021"])
    with Session(dataset) as session, session.begin():
        session.delete(session.scalar(select(Match).where(Match.league == "ucl")))
    with pytest.raises(ValueError, match="16 matches"):
        backtest_round_of_16(dataset)
