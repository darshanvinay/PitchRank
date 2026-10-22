from datetime import date
from pathlib import Path

import numpy as np
import pytest
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from app.core.season import SeasonConfig
from app.db.models import Base, Match, SeasonHistory, SeasonRating, SquadValue
from app.db.session import get_engine
from app.elo.replay import PlayedMatch
from app.elo.season import replay_season, starting_rating
from app.services.season import calculate_season, refresh_season


def test_market_prior_is_logarithmic_capped_and_scale_independent():
    config = SeasonConfig()
    assert starting_rating(500, 500, config) == 1500
    assert starting_rating(1000, 500, config) == pytest.approx(1541.5888308)
    assert starting_rating(1e12, 500, config) == 1600
    assert starting_rating(1, 500, config) == 1400
    assert starting_rating(1e9, 5e8, config) == starting_rating(1000, 500, config)
    assert starting_rating(None, 500, config) == starting_rating(500, None, config) == 1500
    assert starting_rating(1000, 500, SeasonConfig(squad_log_scale=0)) == 1500
    with pytest.raises(ValueError):
        starting_rating(-1, 500, config)


def test_season_replay_uses_squad_prior_then_only_match_evidence():
    match = PlayedMatch(1, "2026-2027", date(2026, 8, 21), None, 1, 2, 1, 0)
    result, initial = replay_season(
        [match], {1: 100_000_000, 2: 1_000_000_000, 3: None}, SeasonConfig()
    )
    assert result.ratings[3] == initial[3] == 1500  # no automatic points for membership
    assert result.entries[0].update.home_before == initial[1]
    assert result.entries[0].update.home_change > 0
    assert sum(result.ratings.values()) == pytest.approx(sum(initial.values()))
    reverse = PlayedMatch(1, "2026-2027", date(2026, 8, 21), None, 2, 1, 1, 0)
    favorite, _ = replay_season([reverse], {1: 100_000_000, 2: 1_000_000_000}, SeasonConfig())
    assert result.entries[0].update.home_change > favorite.entries[0].update.home_change


def test_replay_records_every_result_and_handles_draws():
    first = PlayedMatch(2, "2026-2027", date(2026, 8, 21), None, 1, 2, 0, 0)
    second = PlayedMatch(1, "2026-2027", date(2026, 8, 28), None, 2, 1, 0, 2)
    result, _ = replay_season([second, first], {1: None, 2: None}, SeasonConfig())
    assert [row.match.id for row in result.entries] == [2, 1]
    assert result.entries[0].update.home_change < 0
    assert result.entries[1].update.away_before == result.entries[0].update.home_after
    assert all(row.update.home_change == -row.update.away_change for row in result.entries)


@pytest.fixture
def dataset(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'season.sqlite3'}")
    Base.metadata.create_all(engine)
    results = tmp_path / "results.csv"
    results.write_text(
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H\n"
    )
    squads = Path(__file__).resolve().parents[2] / "data/squads/2026-2027.csv"
    yield engine, results, squads
    engine.dispose()


def snapshot(engine):
    with Session(engine) as session:
        ratings = list(
            session.execute(
                select(
                    SeasonRating.team_id, SeasonRating.rating, SeasonRating.initial_rating
                ).order_by(SeasonRating.team_id)
            )
        )
        history = list(
            session.execute(
                select(
                    SeasonHistory.team_id, SeasonHistory.rating_after, SeasonHistory.rating_change
                ).order_by(SeasonHistory.team_id)
            )
        )
        return ratings, history


def test_refresh_replaces_current_snapshot_without_duplicates(dataset):
    engine, results, squads = dataset
    first = refresh_season(engine, "2026-2027", results, squads)
    before = snapshot(engine)
    second = refresh_season(engine, "2026-2027", results, squads)
    assert first["teams"] == 20 and first["history_rows"] == 2
    assert second["import"]["unchanged"] == 1
    assert snapshot(engine) == before
    results.write_text(results.read_text().replace("3,0,H", "1,1,D"))
    refresh_season(engine, "2026-2027", results, squads)
    assert snapshot(engine) != before


def test_failed_refresh_rolls_back_matches_values_and_ratings(dataset):
    engine, results, squads = dataset
    refresh_season(engine, "2026-2027", results, squads)
    before = snapshot(engine)
    results.write_text(results.read_text().replace("3,0,H", "1,1,D"))

    def fail(*_):
        raise RuntimeError("simulated storage failure")

    event.listen(SeasonHistory, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            refresh_season(engine, "2026-2027", results, squads)
    finally:
        event.remove(SeasonHistory, "before_insert", fail)
    assert snapshot(engine) == before
    with Session(engine) as session:
        assert session.scalar(select(Match)).home_goals == 3
        assert len(session.scalars(select(SquadValue)).all()) == 20


def test_neutral_fallback_when_squad_value_is_missing(dataset):
    engine, results, squads = dataset
    refresh_season(engine, "2026-2027", results, squads)
    with Session(engine) as session, session.begin():
        arsenal = session.scalar(select(Match)).home_team_id
        session.delete(session.scalar(select(SquadValue).where(SquadValue.team_id == arsenal)))
    summary = calculate_season(engine, "2026-2027")
    assert summary["squad_values"] == 19
    with Session(engine) as session:
        row = session.scalar(select(SeasonRating).where(SeasonRating.team_id == arsenal))
        assert row.initial_rating == 1500


def test_shared_reference_is_independent_of_league_membership():
    config = SeasonConfig()
    _, england = replay_season([], {1: 1_300_000_000, 2: 600_000_000}, config)
    _, spain = replay_season([], {3: 1_300_000_000, 4: 60_000_000}, config)
    assert england[1] == spain[3]
    assert england[1] == pytest.approx(1500 + 60 * np.log(1_300_000_000 / 556_425_000))
    # Importing other leagues or changing their valuations cannot change this club's prior.
    _, expanded = replay_season([], {1: 1_300_000_000, 5: 1_000_000}, config)
    assert expanded[1] == england[1]
    _, missing = replay_season([], {1: None}, config)
    assert missing[1] == 1500


def test_shared_reference_is_configurable_and_validated():
    with pytest.raises(ValueError):
        SeasonConfig(squad_reference_eur=0)
    _, initial = replay_season([], {1: 500_000_000}, SeasonConfig(squad_reference_eur=500_000_000))
    assert initial[1] == 1500
