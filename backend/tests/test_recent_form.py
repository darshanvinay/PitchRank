from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_tournament import base_dataset as dataset_fixture
from test_tournament import tournament_dataset as bracket_fixture

from app.backtesting.recent_form import (
    TEST,
    TRAIN,
    VALIDATION,
    blend_rows,
    bracket_comparison,
    calibration,
    compare_errors,
    reconstruct,
    select_weight,
    window_start,
)
from app.db.models import Match
from app.services.historical import historical_elo_snapshot

base_dataset = dataset_fixture
tournament_dataset = bracket_fixture


def records(probs):
    return [
        dict(
            season="2020-2021",
            tie_id=str(i),
            team_a_id=1,
            team_b_id=2,
            p_a=p,
            p_b=1 - p,
            predicted_winner=1 if p >= 0.5 else 2,
            actual_winner=w,
        )
        for i, (p, w) in enumerate(zip(probs, (1, 2, 2, 1), strict=True))
    ]


def test_recent_replay_baseline_parity_and_future_score_isolation(base_dataset):
    with Session(base_dataset) as session:
        matches = session.scalars(select(Match)).all()
    cutoff = date(2021, 2, 16)
    a = reconstruct(matches, cutoff)
    b = reconstruct(matches, cutoff, 1, 30)
    assert a["ratings"] == historical_elo_snapshot(base_dataset, cutoff)["ratings"]
    assert b["start"] == "2020-02-16" and b["latest"] < "2021-02-16"
    assert b["ratings"] != a["ratings"]
    for m in matches:
        if m.match_date >= cutoff:
            m.home_goals += 10
    assert reconstruct(matches, cutoff) == a
    assert reconstruct(matches, cutoff, 1, 30) == b
    matches.append(
        Match(
            id=999,
            status="finished",
            season="2020-2021",
            match_date=cutoff,
            home_team_id=17,
            away_team_id=18,
            home_goals=50,
            away_goals=0,
            stage="league",
            neutral=False,
        )
    )
    assert reconstruct(matches, cutoff, 1, 30) == b
    matches.append(
        Match(
            id=500,
            status="finished",
            season="2018-2019",
            match_date=date(2019, 1, 1),
            home_team_id=1,
            away_team_id=2,
            home_goals=7,
            away_goals=0,
            stage="domestic",
            kickoff_at=None,
            neutral=False,
        )
    )
    assert reconstruct(matches, cutoff, 1, 30) == b
    assert reconstruct(matches, cutoff)["ratings"] != a["ratings"]


def test_window_boundaries_and_no_selection_split_overlap():
    assert window_start(date(2020, 2, 29), 1) == date(2019, 2, 28)
    assert window_start(date(2025, 2, 12), 3) == date(2022, 2, 12)
    with pytest.raises(ValueError):
        window_start(date(2020, 1, 1), 0)
    assert TRAIN[0] == "2013-2014"
    assert max(TRAIN) < min(VALIDATION) and max(VALIDATION) < min(TEST)


def test_complementarity_and_probability_ensemble_identities():
    a = records((0.8, 0.6, 0.4, 0.3))
    b = records((0.4, 0.2, 0.1, 0.7))
    error = compare_errors(a, b)
    assert (error["both_correct"], error["both_wrong"]) == (1, 0)
    assert (error["B_rescues_A"], error["B_spoils_A"], error["disagreements"]) == (2, 1, 3)
    assert error["oracle_union_correct"] == 4
    assert blend_rows(a, b, 0) == a and blend_rows(a, b, 1) == b
    assert [r["p_a"] for r in blend_rows(a, b, 0.5)] == pytest.approx([0.6, 0.4, 0.25, 0.5])
    assert sum(r["n"] for r in calibration(a)) == 4
    with pytest.raises(ValueError):
        blend_rows(a, b, 1.1)
    with pytest.raises(ValueError):
        blend_rows(a, list(reversed(b)), 0.5)
    # Selection receives validation rows only. The test records are not an input.
    selected, grid = select_weight(a, b)
    assert len(grid) == 11
    assert selected["metrics"]["log_loss"] == min(r["metrics"]["log_loss"] for r in grid)


def test_bracket_blends_same_matchup_probabilities_and_keeps_scoring_separate(tournament_dataset):
    with Session(tournament_dataset) as session:
        matches = session.scalars(select(Match)).all()
    cutoff = date(2021, 2, 16)
    models = [
        {
            "seasons": [
                {
                    "season": "2020-2021",
                    "ratings": reconstruct(matches, cutoff, years, k)["ratings"],
                }
            ]
        }
        for years, k in ((None, 20), (1, 30))
    ]
    a = bracket_comparison(matches, models, 0, "2020-2021")
    b = bracket_comparison(matches, models, 1, "2020-2021")
    mix = bracket_comparison(matches, models, 0.5, "2020-2021")
    assert mix["conditional_future_draws"]
    for method in ("greedy", "global"):
        assert mix["evaluation"]["own_predicted_winners"][method]["total"] == 15
        for x, y, z in zip(
            a["forecasts"][method]["matches"][:8],
            b["forecasts"][method]["matches"][:8],
            mix["forecasts"][method]["matches"][:8],
            strict=True,
        ):
            assert z["p_a"] == pytest.approx((x["p_a"] + y["p_a"]) / 2)
    assert len(mix["evaluation"]["actual_participants"]["predictions"]) == 15
    assert mix["higher_elo_own"]["A"]["total"] == 15
    assert mix["higher_elo_own"]["B"]["total"] == 15
