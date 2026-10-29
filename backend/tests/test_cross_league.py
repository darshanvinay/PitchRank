from datetime import date

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session
from test_knockout import dataset as knockout_dataset

from app.backtesting.cross_league import (
    KEYS,
    TEST,
    TRAIN,
    VALIDATION,
    Variant,
    experimental_entries,
    league_offsets,
    replay_variant,
)
from app.db.models import Match
from app.services.historical import historical_elo_snapshot

base_dataset = knockout_dataset


def fixture(mid, season, day, home, away, hg, ag, league="epl"):
    return Match(
        id=mid,
        season=season,
        match_date=day,
        home_team_id=home,
        away_team_id=away,
        home_goals=hg,
        away_goals=ag,
        league=league,
        stage="domestic" if league != "ucl" else "league",
        kickoff_at=None,
        neutral=False,
        status="finished",
        source="test",
    )


def test_offsets_regularize_decay_and_use_strictly_past_cross_results():
    x = [int(k == "epl") - int(k == "laliga") for k in KEYS]
    observations = [(date(2019, 1, 1), x, 0, 1)] * 10
    cutoff = date(2020, 1, 1)
    fit = league_offsets(observations, cutoff, 75, 2)
    assert fit["epl"] > 0 > fit["laliga"]
    assert sum(fit.values()) == pytest.approx(0)
    assert abs(league_offsets(observations, cutoff, 25, 2)["epl"]) < fit["epl"]
    assert abs(league_offsets(observations, date(2025, 1, 1), 75, 2)["epl"]) < fit["epl"]
    future = observations + [(cutoff, x, 0, 0)] * 100
    assert league_offsets(future, cutoff, 75, 2) == fit
    assert league_offsets(observations, cutoff, 0, 2) == dict.fromkeys(KEYS, 0)


def test_margin_cap_is_bounded_zero_sum_and_never_changes_expectations():
    matches = [fixture(1, "2010-2011", date(2010, 9, 1), 1, 2, 15, 0)]
    base = experimental_entries(matches, Variant())[0]
    capped = experimental_entries(matches, Variant("D", margin_cap=1.25))[0]
    assert base[1:3] == capped[1:3]
    assert abs(capped[3]) < abs(base[3])
    assert capped[3] + capped[4] == pytest.approx(0)
    import math

    assert capped[3] / base[3] == pytest.approx(1.25 / math.log(16))


def test_newcomer_prior_preserves_early_ucl_evidence_and_never_uses_future_membership():
    matches = [
        fixture(1, "2010-2011", date(2011, 5, 1), 1, 2, 6, 0),
        fixture(2, "2011-2012", date(2011, 8, 1), 3, 1, 2, 0, "ucl"),
        fixture(3, "2011-2012", date(2011, 8, 3), 3, 1, 1, 0),
    ]
    base = experimental_entries(matches, Variant())
    calibrated = experimental_entries(matches, Variant("C", newcomer_blend=0.5))
    assert calibrated[1] == base[1]  # Domestic membership not yet observed for club 3.
    prior = base[0][2] + base[0][4]  # Bottom-quarter club's last observed previous-season rating.
    assert calibrated[2][1] == pytest.approx(base[2][1] + 0.5 * (prior - 1500))
    assert calibrated[2][1] > 1500 + 0.5 * (prior - 1500)  # UCL win's positive update survives.
    assert experimental_entries(matches[:2], Variant("C", newcomer_blend=0.5)) == calibrated[:2]


def test_baseline_parity_and_no_future_match_or_league_leakage(base_dataset):
    with Session(base_dataset) as session:
        matches = session.scalars(select(Match)).all()
    cutoff = date(2021, 2, 16)
    for v in (
        Variant(),
        Variant("B", offset_sd=75),
        Variant("C", newcomer_blend=0.5),
        Variant("D", margin_cap=1.25),
        Variant("E", offset_sd=75, newcomer_blend=0.5, margin_cap=1.25),
    ):
        before = replay_variant(matches, v, {2020: cutoff})["snapshots"][cutoff]
        changed = [fixture(1000, "2021-2022", date(2021, 9, 1), 18, 19, 20, 0, "laliga")]
        for m in matches:
            if m.match_date >= cutoff:
                m.home_goals += 9
        after = replay_variant(matches + changed, v, {2020: cutoff})["snapshots"][cutoff]
        assert after == before
    clean = [m for m in matches if m.match_date < cutoff]
    baseline = replay_variant(clean, Variant(), {2020: cutoff})["snapshots"][cutoff]
    assert baseline["ratings"] == historical_elo_snapshot(base_dataset, cutoff)["ratings"]
    assert max(TRAIN) < min(VALIDATION) and max(VALIDATION) < min(TEST)
    assert baseline["pool_deviation"] == pytest.approx(baseline["adjustment_mass"])
    for kwargs in ({"offset_sd": -1}, {"half_life": 0}, {"margin_cap": 0.5}):
        with pytest.raises(ValueError):
            Variant(**kwargs)
