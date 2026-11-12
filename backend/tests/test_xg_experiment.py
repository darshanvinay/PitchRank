"""Synthetic fixtures exercise xG ingestion and leakage protection, not performance metrics."""

from dataclasses import asdict, replace
from datetime import date

import numpy as np
import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session
from test_knockout import dataset as knockout_dataset

from app.backtesting.search_data import build_data
from app.backtesting.search_engine import SearchConfig, batch_replay
from app.backtesting.xg_engine import (
    XGConfig,
    batch_xg,
    feature,
    poisson_outcomes,
    sample_configs,
)
from app.db.models import Base, Match, MatchXG, Team
from app.db.session import get_engine
from app.ingestion.understat import import_rows

base_dataset = knockout_dataset


@pytest.fixture
def xg_db(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'xg.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as s, s.begin():
        s.add_all(
            [
                Team(id=1, canonical_name="Manchester City", display_name="Man City"),
                Team(id=2, canonical_name="Arsenal FC", display_name="Arsenal"),
            ]
        )
        s.flush()
        s.add(
            Match(
                id=1,
                league="epl",
                season="2020-2021",
                match_date=date(2021, 1, 1),
                home_team_id=1,
                away_team_id=2,
                home_goals=2,
                away_goals=0,
                source="test",
                status="finished",
            )
        )
    return engine


def source_row(**updates):
    return dict(
        understat_id="123",
        league="EPL",
        season="2020",
        home_team="Manchester City",
        away_team="Arsenal",
        match_date="2021-01-01 15:00:00",
        home_score=2,
        away_score=0,
        home_xg=1.2,
        away_xg=0.4,
        **updates,
    )


def test_xg_import_idempotence_dry_run_correction_and_existing_results_unchanged(xg_db):
    row = source_row()
    assert import_rows(xg_db, [row, row], "f" * 64)["inserted"] == 1
    with Session(xg_db) as s:
        assert s.scalar(select(func.count(MatchXG.match_id))) == 0
    result = import_rows(xg_db, [row, row], "f" * 64, apply=True)
    assert result["inserted"] == 1 and result["duplicate_rows"] == 1
    assert import_rows(xg_db, [row], "f" * 64, apply=True)["unchanged"] == 1
    result = import_rows(xg_db, [dict(row, home_xg=1.3)], "e" * 64, apply=True)
    assert result["updated"] == 1
    with Session(xg_db) as s:
        m = s.get(Match, 1)
        x = s.get(MatchXG, 1)
        assert (m.home_goals, m.away_goals, m.source) == (2, 0, "test")
        assert x.home_xg == 1.3 and x.archive_sha256 == "e" * 64


@pytest.mark.parametrize(
    "change",
    [
        {"home_team": "Unreviewed City"},
        {"home_score": 3},
        {"home_xg": float("nan")},
        {"away_xg": None},
        {"match_date": "2021-01-02"},
        {"match_date": "2099-01-01"},
    ],
)
def test_xg_mismatched_or_invalid_rows_are_quarantined(xg_db, change):
    result = import_rows(xg_db, [dict(source_row(), **change)], "f" * 64, apply=True)
    assert result["inserted"] == 0 and len(result["rejected"]) == 1


def test_conflicting_source_duplicates_do_not_silently_choose_one(xg_db):
    r = source_row()
    result = import_rows(xg_db, [r, dict(r, home_xg=5)], "f" * 64, apply=True)
    assert result["inserted"] == 0 and "Conflicting" in result["rejected"][0]["reason"]


def test_poisson_probabilities_symmetry_and_configuration_reproducibility():
    p = poisson_outcomes(np.array([0, 1, 2]), np.array([0, 1, 0.5]))
    assert np.allclose(p.sum(axis=1), 1)
    assert p[0].tolist() == [0, 1, 0]
    assert p[1, 0] == pytest.approx(p[1, 2])
    assert np.allclose(p[2], poisson_outcomes(0.5, 2)[::-1])
    assert sample_configs(100, 7) == sample_configs(100, 7)
    assert len({c.identity for c in sample_configs(100, 7)}) == 100
    assert XGConfig(**asdict(XGConfig())).identity == XGConfig().identity
    with pytest.raises(ValueError):
        XGConfig(blend=2)
    assert feature([], date(2020, 1, 1), 2019, XGConfig()) == 0


def test_all_xg_families_obey_cutoff_and_zero_xg_share_reproduces_A(base_dataset):
    with Session(base_dataset) as s, s.begin():
        for day in range(3, 8):
            for home in range(1, 17, 2):
                s.add(
                    Match(
                        league="epl",
                        season="2020-2021",
                        match_date=date(2021, 1, day),
                        home_team_id=home,
                        away_team_id=home + 1,
                        home_goals=2,
                        away_goals=0,
                        status="finished",
                        source="test",
                        stage="domestic",
                    )
                )
    data = build_data(base_dataset, ["2020-2021"])
    p, _, r = batch_replay(data, [SearchConfig()], date(2013, 7, 1))
    observations = {e.mid: (0.3, 2.5) for b in data.blocks for e in b.events}
    configs = [
        XGConfig(family=f, blend=1)
        for f in ("differential", "recent", "xg_elo", "attack_defence", "ensemble")
    ]
    configs.append(XGConfig(family="xg_elo", xg_share=0, blend=1))
    result = batch_xg(data, observations, configs, p[:, 0, :], r[:, 0, :])
    assert np.allclose(result[:, -1, :], p[:, 0, :], atol=1e-12)
    assert not np.allclose(result[:, 2, :], p[:, 0, :])
    future = {e.mid for b in data.blocks if b.day >= date(2021, 2, 16) for e in b.events}
    changed = {mid: (7, 0) if mid in future else value for mid, value in observations.items()}
    assert np.array_equal(result, batch_xg(data, changed, configs, p[:, 0, :], r[:, 0, :]))
    assert np.array_equal(result, batch_xg(data, observations, configs, p[:, 0, :], r[:, 0, :]))
    assert np.allclose(
        result[:, ::-1, :], batch_xg(data, observations, configs[::-1], p[:, 0, :], r[:, 0, :])
    )
    missing = batch_xg(data, {}, configs, p[:, 0, :], r[:, 0, :])
    assert np.allclose(missing, p[:, 0, None, :])
    zero_blend = batch_xg(
        data, observations, [replace(c, blend=0) for c in configs], p[:, 0, :], r[:, 0, :]
    )
    assert np.allclose(zero_blend, p[:, 0, None, :])


def test_ambiguous_fixture_ids_and_malformed_seasons_are_quarantined(xg_db):
    row = source_row()
    result = import_rows(xg_db, [row, dict(row, understat_id="456")], "f" * 64, apply=True)
    assert result["inserted"] == 0 and len(result["rejected"]) == 2
    result = import_rows(xg_db, [dict(row, season=None)], "f" * 64, apply=True)
    assert result["inserted"] == 0 and len(result["rejected"]) == 1
