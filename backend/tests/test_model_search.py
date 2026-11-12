import json
from dataclasses import asdict, replace
from datetime import date, datetime, timezone
from types import SimpleNamespace

import numpy as np
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_knockout import dataset as knockout_dataset

from app.backtesting.knockout import TieFixture, advancement_probability
from app.backtesting.model_search import fold_select, load_records, metrics, perturb
from app.backtesting.search_data import build_data, contract, tie_tensor
from app.backtesting.search_engine import (
    SearchConfig,
    anchors,
    batch_replay,
    calibrate,
    sample_config,
)
from app.db.models import Match
from app.predictions.model import PredictionConfig, probabilities

base_dataset = knockout_dataset


def test_exact_probability_tensor_matches_existing_old_new_and_neutral_rules():
    shapes = [{(1, 0): 0.6, (3, 1): 0.4}, {(0, 0): 0.7, (1, 1): 0.3}, {(0, 1): 0.4, (1, 2): 0.6}]
    for rule in (False, True):
        for nf, ns in ((False, False), (True, False), (False, True), (True, True)):
            tensor = tie_tensor(shapes, nf, ns, rule)
            for h, a in ((1500, 1500), (1700, 1400), (1300, 1850)):
                config = PredictionConfig()
                f = probabilities(
                    h,
                    a,
                    config.model_copy(
                        update={"elo": config.elo.model_copy(update={"home_advantage": 0})}
                    )
                    if nf
                    else config,
                )
                s = probabilities(
                    a,
                    h,
                    config.model_copy(
                        update={"elo": config.elo.model_copy(update={"home_advantage": 0})}
                    )
                    if ns
                    else config,
                )
                expected = advancement_probability(
                    TieFixture(1, 2, nf, ns), {1: h, 2: a}, shapes, config, rule
                )
                assert float(contract(f, s, tensor)) == pytest.approx(expected, abs=1e-12)


def test_configuration_reproducibility_validation_and_perturbations():
    assert SearchConfig(**asdict(SearchConfig())).identity == SearchConfig().identity
    assert SearchConfig(k_domestic=20.0).identity == SearchConfig().identity
    assert SearchConfig(form_weight=0, form_window=3).identity == SearchConfig().identity
    for kw in (
        {"k_domestic": 0},
        {"home": float("nan")},
        {"margin": "magic"},
        {"form_weight": 0.6},
    ):
        with pytest.raises(ValueError):
            SearchConfig(**kw)
    a = np.random.default_rng(2026)
    b = np.random.default_rng(2026)
    assert [sample_config(a).identity for _ in range(20)] == [
        sample_config(b).identity for _ in range(20)
    ]
    c = perturb(SearchConfig(), 0.1, "k_domestic")
    assert c.k_domestic == 22 and c.k_ucl == 20


def test_batched_baseline_cutoff_and_same_day_future_matches_do_not_leak(base_dataset):
    with Session(base_dataset) as session, session.begin():
        # Make the cutoff day have multiple known kickoff groups: emit forecasts only ONCE.
        for i, m in enumerate(
            session.scalars(select(Match).where(Match.match_date == date(2021, 2, 16)))
        ):
            m.kickoff_at = datetime(2021, 2, 16, 12 + i, tzinfo=timezone.utc)
    data = build_data(base_dataset, ["2020-2021"])
    configs = anchors()[:8]
    p, raw, _ = batch_replay(data, configs, date(2013, 7, 1))
    from app.backtesting.knockout import backtest_round_of_16

    canonical = backtest_round_of_16(base_dataset)["predictions"]
    expected = {r["tie_id"]: r["p_a"] for r in canonical}
    assert p[0, 0] == pytest.approx(
        [expected[t["tie_id"]] for t in data.fixtures[0]["rows"]], abs=1e-12
    )
    with Session(base_dataset) as session, session.begin():
        for m in session.scalars(select(Match).where(Match.match_date >= date(2021, 2, 16))):
            m.home_goals += 10
    changed = build_data(base_dataset, ["2020-2021"])
    again, again_raw, _ = batch_replay(changed, configs, date(2013, 7, 1))
    np.testing.assert_array_equal(p, again)
    np.testing.assert_array_equal(raw, again_raw)
    np.testing.assert_array_equal(p, batch_replay(data, configs, date(2013, 7, 1))[0])


def test_calibrators_fallback_and_only_explicit_past_samples():
    p = np.array([0.15, 0.5, 0.8])
    assert np.array_equal(calibrate(p, np.array([0.1]), np.array([0]), "platt"), p)
    x = np.linspace(0.1, 0.9, 80)
    y = (x > 0.6).astype(float)
    for kind in ("platt", "isotonic"):
        result = calibrate(p, x, y, kind)
        assert np.all(np.diff(result) >= 0) and np.all((result > 0) & (result < 1))
        assert np.array_equal(result, calibrate(p, x.copy(), y.copy(), kind))


def test_walk_forward_selection_never_uses_current_or_future_labels():
    seasons = [f"{y}-{y + 1}" for y in range(2013, 2022)]
    fixtures = [
        dict(
            season=s,
            cutoff=date(int(s[:4]) + 1, 2, 16),
            rows=[dict(actual_a=True, available=date(int(s[:4]) + 1, 3, 10)) for _ in range(8)],
        )
        for s in seasons
    ]
    data = SimpleNamespace(fixtures=fixtures)
    c1 = SearchConfig()
    c2 = replace(c1, home=0)
    records = [
        dict(id=c1.identity, config=asdict(c1), p=np.full((len(seasons), 8), 0.8).tolist()),
        dict(id=c2.identity, config=asdict(c2), p=np.full((len(seasons), 8), 0.2).tolist()),
    ]
    before = fold_select(records, data, seasons[:7], seasons[7:])
    assert before["folds"][0]["selected_id"] == c1.identity
    for f in fixtures[7:]:
        for r in f["rows"]:
            r["actual_a"] = False
    after = fold_select(records, data, seasons[:7], seasons[7:])
    assert before["folds"][0]["selected_id"] == after["folds"][0]["selected_id"]
    assert before["folds"][0]["p"] == after["folds"][0]["p"]
    assert before["folds"][0]["metrics"] != after["folds"][0]["metrics"]


def test_resumable_records_repair_only_partial_final_append(tmp_path):
    path = tmp_path / "trials.jsonl"
    path.write_text(json.dumps({"id": "one"}) + "\n" + json.dumps({"id": "two"}) + '\n{"id":')
    assert len(load_records(path)) == 2
    assert len(load_records(path)) == 2
    path.write_text('{"id":"one"}\n{"id":"one"}\n')
    with pytest.raises(ValueError):
        load_records(path)
    m = metrics([[0.8, 0.3]], [[1, 0]])
    assert m["correct"] == 2 and m["brier"] == pytest.approx((0.04 + 0.09) / 2)


def test_mature_calibrators_cannot_see_current_round_outcomes(base_dataset):
    """Exercise Platt/isotonic after >=64 resolved ties, not just their cold fallbacks."""
    with Session(base_dataset) as session, session.begin():
        for i, (h, a, hg, ag) in enumerate(((1, 3, 2, 0), (2, 4, 0, 0), (5, 7, 0, 1))):
            session.add(
                Match(
                    league="epl",
                    season="2010-2011",
                    match_date=date(2010, 9, i + 1),
                    home_team_id=h,
                    away_team_id=a,
                    home_goals=hg,
                    away_goals=ag,
                    status="finished",
                    source="synthetic test",
                    stage="domestic",
                )
            )
        for year in range(2011, 2020):
            for i in range(8):
                a, b = 2 * i + 1, 2 * i + 2
                for leg in (1, 2):
                    session.add(
                        Match(
                            league="ucl",
                            season=f"{year}-{year + 1}",
                            match_date=date(year + 1, 2 if leg == 1 else 3, 16 if leg == 1 else 9),
                            home_team_id=a if leg == 1 else b,
                            away_team_id=b if leg == 1 else a,
                            home_goals=(2 if leg == 1 else 0)
                            if i % 2 == 0
                            else (0 if leg == 1 else 1),
                            away_goals=(0 if leg == 1 else 1)
                            if i % 2 == 0
                            else (1 if leg == 1 else 0),
                            status="finished",
                            source="synthetic test",
                            stage="knockout",
                            ucl_detail={
                                "round": "round_of_16",
                                "tie_id": f"{year}-{i}",
                                "leg": leg,
                            },
                        )
                    )
    configs = [
        SearchConfig(calibration="platt"),
        SearchConfig(calibration="isotonic"),
        SearchConfig(head="regularized", calibration="platt"),
    ]
    data = build_data(base_dataset, ["2020-2021"])
    before, raw, _ = batch_replay(data, configs, date(2013, 7, 1))
    assert len(data.fixtures) == 10  # 72 prior resolved ties at the last cutoff.
    assert not np.allclose(before[-1], raw[-1])  # Calibration really ran.
    with Session(base_dataset) as session, session.begin():
        for match in session.scalars(
            select(Match).where(Match.league == "ucl", Match.season == "2020-2021")
        ):
            leg = match.ucl_detail["leg"]
            match.home_goals = 0 if leg == 1 else 2
            match.away_goals = 2 if leg == 1 else 0
    future_changed = build_data(base_dataset, ["2020-2021"])
    after, _, _ = batch_replay(future_changed, configs, date(2013, 7, 1))
    np.testing.assert_array_equal(before, after)
