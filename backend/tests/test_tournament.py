import itertools
import math
import random
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select
from sqlalchemy.orm import Session
from test_knockout import dataset as knockout_dataset

from app.backtesting.tournament import (
    Node,
    backtest_tournaments,
    final_probability,
    forecast_tournament,
    solve_bracket,
    validate_tree,
)
from app.db.models import Match
from app.main import create_app
from app.predictions.model import PredictionConfig

base_dataset = knockout_dataset


@pytest.fixture
def tournament_dataset(base_dataset):
    with Session(base_dataset) as s, s.begin():
        for round_name, pairs, month in [
            ("quarterfinal", [(1, 3), (5, 7), (9, 11), (13, 15)], 4),
            ("semifinal", [(1, 5), (9, 13)], 5),
        ]:
            for i, (a, b) in enumerate(pairs):
                for leg in (1, 2):
                    s.add(
                        Match(
                            league="ucl",
                            season="2020-2021",
                            match_date=date(2021, month, leg * 7),
                            home_team_id=a if leg == 1 else b,
                            away_team_id=b if leg == 1 else a,
                            home_goals=2 if leg == 1 else 0,
                            away_goals=0 if leg == 1 else 1,
                            status="finished",
                            source="test",
                            stage="knockout",
                            ucl_detail={
                                "round": round_name,
                                "tie_id": f"{round_name}-{i}",
                                "leg": leg,
                            },
                        )
                    )
        s.add(
            Match(
                league="ucl",
                season="2020-2021",
                match_date=date(2021, 5, 29),
                home_team_id=1,
                away_team_id=9,
                home_goals=0,
                away_goals=0,
                status="finished",
                source="test",
                stage="finals",
                neutral=True,
                ucl_detail={
                    "round": "final",
                    "tie_id": "final",
                    "extra_time_home": 0,
                    "extra_time_away": 0,
                    "penalties_home": 4,
                    "penalties_away": 3,
                },
            )
        )
    return base_dataset


def tree():
    nodes = list(range(1, 17))
    for r in ("round_of_16", "quarterfinal", "semifinal", "final"):
        nodes = [Node(f"{r}-{i}", r, nodes[i], nodes[i + 1]) for i in range(0, len(nodes), 2)]
    return nodes[0]


def test_dp_matches_exhaustive_complete_bracket_optimum():
    root = tree()
    rng = random.Random(17)
    probabilities = {}

    def probability(node, a, b):
        key = node.id, a, b
        if key not in probabilities:
            probabilities[key] = rng.uniform(0.1, 0.9)
        return probabilities[key]

    global_result = solve_bracket(root, probability)
    greedy = solve_bracket(root, probability, "greedy")

    def enumerate_one(node, choices):
        if isinstance(node, int):
            return node, 1.0
        a, pa = enumerate_one(node.left, choices)
        b, pb = enumerate_one(node.right, choices)
        p = probability(node, a, b)
        return (a, pa * pb * p) if next(choices) == 0 else (b, pa * pb * (1 - p))

    best = max(enumerate_one(root, iter(bits))[1] for bits in itertools.product((0, 1), repeat=15))
    assert global_result["joint_probability"] == pytest.approx(best)
    assert global_result["log_joint_probability"] > greedy["log_joint_probability"]
    assert len(global_result["matches"]) == 15
    assert math.prod(m["selected_probability"] for m in global_result["matches"]) == pytest.approx(
        best
    )
    with pytest.raises(ValueError):
        validate_tree(Node("bad", "final", root.left, root.left))
    with pytest.raises(ValueError):
        solve_bracket(root, lambda *_: 2)


def test_single_neutral_final_symmetry_and_favorite():
    scores = [{(1, 0): 1}, {(0, 0): 1}, {(0, 1): 1}]
    config = PredictionConfig()
    assert final_probability(1, 2, {1: 1500, 2: 1500}, scores, config) == pytest.approx(0.5)
    p = final_probability(1, 2, {1: 1700, 2: 1500}, scores, config)
    assert p > 0.5
    assert final_probability(2, 1, {1: 1700, 2: 1500}, scores, config) == pytest.approx(1 - p)


def test_progression_reproducibility_and_methodology(tournament_dataset):
    result = forecast_tournament(tournament_dataset, scenario="observed_draw", evaluate=True)
    assert result == forecast_tournament(
        tournament_dataset, scenario="observed_draw", evaluate=True
    )
    assert result["conditional"] and not result["unconditional_historical_forecast"]
    for forecast in result["forecasts"].values():
        previous = set(range(1, 17))
        for stage, count in [
            ("round_of_16", 8),
            ("quarterfinal", 4),
            ("semifinal", 2),
            ("final", 1),
        ]:
            rows = [m for m in forecast["matches"] if m["round"] == stage]
            assert len(rows) == count
            assert {t for m in rows for t in (m["team_a_id"], m["team_b_id"])} == previous
            previous = {m["winner_id"] for m in rows}
        assert previous == {forecast["champion_id"]}
        assert forecast["matches"][-1]["single_match"]
    evaluation = result["evaluation"]
    assert evaluation["actual_winners"]["final"] == 1  # Shootout, not a drawn final.
    assert evaluation["own_predicted_winners"]["greedy"]["total"] == 15
    assert evaluation["actual_participants"]["metrics"]["total"] == 15
    assert (
        evaluation["own_predicted_winners"]["greedy"]["correct_finalists"]
        == evaluation["own_predicted_winners"]["greedy"]["rounds"]["semifinal"]["correct"]
    )
    with pytest.raises(ValueError, match="conditional"):
        forecast_tournament(tournament_dataset, evaluate=True)
    with pytest.raises(ValueError):
        backtest_tournaments(tournament_dataset, ["2020-2021", "2020-2021"])


def test_future_results_cannot_change_predictions_and_scenario_ignores_later_draws(
    tournament_dataset,
):
    before = forecast_tournament(tournament_dataset, scenario="observed_draw")
    fixed = forecast_tournament(tournament_dataset)
    with Session(tournament_dataset) as s, s.begin():
        future = s.scalar(select(Match).where(Match.match_date == date(2021, 5, 29)))
        future.home_goals = 20
    assert before == forecast_tournament(tournament_dataset, scenario="observed_draw")
    with Session(tournament_dataset) as s, s.begin():
        s.execute(delete(Match).where(Match.match_date >= date(2021, 4, 1)))
    assert fixed == forecast_tournament(tournament_dataset)
    with pytest.raises(ValueError):
        forecast_tournament(tournament_dataset, scenario="observed_draw")


def test_bracket_api_and_invalid_inputs(tournament_dataset):
    with TestClient(create_app(tournament_dataset)) as client:
        response = client.get("/api/ucl/bracket")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert len(response.json()["forecasts"]["global"]["matches"]) == 15
        assert client.get("/api/ucl/bracket?season=2019-2020").status_code == 422
        assert client.get("/api/ucl/bracket?scenario=unknown").status_code == 422
