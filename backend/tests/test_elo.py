import math
from datetime import date, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session

from app.core.elo import EloConfig, load_config
from app.db.models import Base, Match, ModelVersion, RatingHistory, Team
from app.db.session import get_engine
from app.elo.engine import expected_score, goal_multiplier, update_ratings
from app.elo.replay import PlayedMatch, replay
from app.ingestion.historical import import_csv
from app.services.ratings import rankings, rebuild_ratings


def fixture_match(
    id=1, day="2023-08-01", season="2023-2024", home=1, away=2, hg=1, ag=0, kickoff=None
):
    return PlayedMatch(id, season, date.fromisoformat(day), kickoff, home, away, hg, ag)


def test_expected_score_formula_and_home_advantage():
    config = EloConfig()
    assert expected_score(1500, 1500, config) == pytest.approx(1 / (1 + 10 ** (-65 / 400)))
    assert expected_score(1500, 1500, EloConfig(home_advantage=0)) == 0.5
    assert expected_score(1500, 1500, config) > 0.5
    assert expected_score(1700, 1400, config) > expected_score(1400, 1700, config)


@pytest.mark.parametrize("goals,actual", [((2, 0), 1), ((1, 1), 0.5), ((0, 2), 0)])
def test_win_draw_loss_updates_are_zero_sum(goals, actual):
    config = EloConfig()
    result = update_ratings(1600, 1400, *goals, config)
    expected_delta = (
        config.k_factor
        * max(1, math.log1p(abs(goals[0] - goals[1])))
        * (actual - expected_score(1600, 1400, config))
    )
    assert result.home_change == pytest.approx(expected_delta)
    assert result.away_change == -result.home_change
    assert result.home_after + result.away_after == pytest.approx(3000)
    assert result.actual_home == actual


def test_draw_updates_non_equal_expectation_and_margin_scales():
    config = EloConfig()
    draw = update_ratings(1500, 1500, 0, 0, config)
    assert draw.home_change < 0 and draw.multiplier == 1
    assert (
        update_ratings(1500, 1500, 1, 0, config).home_change
        < update_ratings(1500, 1500, 4, 0, config).home_change
    )
    assert goal_multiplier(9, 0, EloConfig(goal_multiplier_scale=0)) == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -float("inf")])
def test_nonfinite_ratings_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        expected_score(value, 1500, EloConfig())


@pytest.mark.parametrize("goals", [(-1, 0), (0, None), (0.5, 0), (True, 0)])
def test_invalid_goals_rejected(goals):
    with pytest.raises(ValueError, match="Goals"):
        update_ratings(1500, 1500, *goals, EloConfig())


def test_expected_score_handles_extreme_ratings():
    assert expected_score(1e9, -1e9, EloConfig()) == 1
    assert expected_score(-1e9, 1e9, EloConfig()) == 0


@pytest.mark.parametrize(
    "values",
    [
        {"k_factor": 0},
        {"home_advantage": -1},
        {"season_regression": 1.1},
        {"initial_rating": float("nan")},
        {"rating_scale": 0},
        {"typo": 42},
    ],
)
def test_bad_config_rejected(values):
    with pytest.raises(ValidationError):
        EloConfig(**values)


def test_config_load_hash_is_stable_and_versioned(tmp_path):
    path = tmp_path / "config.json"
    path.write_text('{"home_advantage": 70, "k_factor": 25}')
    config = load_config(path)
    assert config == EloConfig(k_factor=25, home_advantage=70)
    assert config.config_hash == EloConfig(home_advantage=70, k_factor=25).config_hash
    assert config.config_hash != EloConfig().config_hash
    assert "engine_revision" in config.identity
    with pytest.raises(ValidationError):
        config.k_factor = 30


def test_replay_chronology_is_independent_of_input_order():
    first = fixture_match(id=99)
    second = fixture_match(id=1, day="2023-08-08", home=2, away=1)
    result = replay([second, first], EloConfig())
    assert [e.match.id for e in result.entries] == [99, 1]
    assert result.entries[1].update.away_before == result.entries[0].update.home_after
    assert result == replay([first, second], EloConfig())


def test_kickoff_orders_same_day_matches_and_ties_are_stable():
    first = fixture_match(id=99, kickoff=datetime(2023, 8, 1, 12))
    second = fixture_match(id=1, home=3, away=4, kickoff=datetime(2023, 8, 1, 15))
    third = fixture_match(id=2, home=5, away=6, kickoff=second.kickoff_at)
    result = replay([third, second, first], EloConfig())
    assert [e.match.id for e in result.entries] == [99, 1, 2]
    assert result == replay([first, second, third], EloConfig())


def test_ambiguous_day_rejects_club_playing_twice():
    first = fixture_match()
    second = fixture_match(id=2, home=2, away=3, kickoff=datetime(2023, 8, 1, 15))
    with pytest.raises(ValueError, match="ambiguous kickoff"):
        replay([second, first], EloConfig())


def test_missing_time_groups_entire_day_and_uses_stable_team_order():
    first = fixture_match(id=8, home=3, away=4, kickoff=datetime(2023, 8, 1, 12))
    second = fixture_match(id=9)
    result = replay([first, second], EloConfig())
    assert [e.match.id for e in result.entries] == [9, 8]
    assert all(e.update.home_before == 1500 for e in result.entries)


def test_duplicate_matches_and_self_matches_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        replay([fixture_match(), fixture_match()], EloConfig())
    with pytest.raises(ValueError, match="itself"):
        replay([fixture_match(home=1, away=1)], EloConfig())


def test_season_regression_and_promoted_club_average():
    first = fixture_match()
    next_season = fixture_match(id=2, day="2024-08-01", season="2024-2025", home=1, away=3)
    config = EloConfig()
    result = replay([next_season, first], config)
    previous, current = (entry.update for entry in result.entries)
    assert current.home_before == pytest.approx(1500 + (previous.home_after - 1500) * 0.75)
    assert current.away_before == previous.away_after  # departing club 2's final rating


def test_promotion_uses_mean_of_all_departing_clubs():
    matches = [
        fixture_match(),
        fixture_match(id=2, home=3, away=4),
        fixture_match(id=3, day="2024-08-01", season="2024-2025", home=1, away=5),
    ]
    result = replay(matches, EloConfig())
    prior = result.entries[:2]
    expected = (
        prior[0].update.away_after + prior[1].update.home_after + prior[1].update.away_after
    ) / 3
    assert result.entries[2].update.away_before == pytest.approx(expected)


def test_returning_club_does_not_keep_stale_elo():
    matches = [
        fixture_match(),
        fixture_match(id=2, day="2024-08-01", season="2024-2025", home=1, away=3),
        fixture_match(id=3, day="2025-08-01", season="2025-2026", home=1, away=2),
    ]
    result = replay(matches, EloConfig())
    assert result.entries[2].update.away_before == result.entries[1].update.away_after


def test_season_gap_uses_default_for_new_clubs_and_regresses_retained_clubs():
    first = fixture_match()
    later = fixture_match(id=2, day="2026-08-01", season="2026-2027", home=1, away=3)
    config = EloConfig()
    result = replay([first, later], config)
    assert result.entries[1].update.home_before == pytest.approx(
        1500 + (result.entries[0].update.home_after - 1500) * 0.75**3
    )
    assert result.entries[1].update.away_before == 1400


def test_out_of_order_seasons_rejected():
    matches = [
        fixture_match(season="2024-2025"),
        fixture_match(id=2, day="2023-08-02", season="2023-2024"),
    ]
    with pytest.raises(ValueError, match="Season dates"):
        replay(matches, EloConfig())


@pytest.fixture
def database(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'elo.sqlite3'}")
    Base.metadata.create_all(engine)
    path = tmp_path / "results.csv"
    path.write_text(
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,11/08/2023,20:00,Burnley,Man City,0,3,A\n"
        "E0,19/08/2023,15:00,Man City,Newcastle,1,0,H\n"
    )
    import_csv(engine, path, "2023-2024")
    yield engine, path
    engine.dispose()


def stored_history(engine, version_id):
    with Session(engine) as session:
        return [
            tuple(row)
            for row in session.execute(
                select(
                    RatingHistory.match_id,
                    RatingHistory.team_id,
                    RatingHistory.rating_before,
                    RatingHistory.rating_after,
                    RatingHistory.rating_change,
                    RatingHistory.sequence,
                )
                .where(RatingHistory.model_version_id == version_id)
                .order_by(RatingHistory.sequence, RatingHistory.team_id)
            )
        ]


def test_rebuild_is_idempotent_and_force_is_reproducible(database):
    engine, _ = database
    first = rebuild_ratings(engine, EloConfig())
    history = stored_history(engine, first.model_version_id)
    assert first.rebuilt and first.matches == 2 and first.history_rows == 4
    again = rebuild_ratings(engine, EloConfig())
    assert not again.rebuilt and again.model_version_id == first.model_version_id
    forced = rebuild_ratings(engine, EloConfig(), force=True)
    assert forced.rebuilt and stored_history(engine, forced.model_version_id) == history
    with Session(engine) as session:
        assert all(m.processed for m in session.scalars(select(Match)))
        assert session.scalar(select(func.count()).select_from(RatingHistory)) == 4
    for match_id in {row[0] for row in history}:
        assert sum(row[4] for row in history if row[0] == match_id) == 0


def test_parameter_versions_keep_separate_histories(database):
    engine, _ = database
    first = rebuild_ratings(engine, EloConfig())
    original = stored_history(engine, first.model_version_id)
    second = rebuild_ratings(engine, EloConfig(k_factor=30))
    assert first.model_version_id != second.model_version_id
    assert stored_history(engine, first.model_version_id) == original
    assert stored_history(engine, second.model_version_id) != original
    assert not rebuild_ratings(engine, EloConfig()).rebuilt


def test_corrected_result_rebuilds_downstream_history_and_blocks_stale_rankings(database):
    engine, path = database
    first = rebuild_ratings(engine, EloConfig())
    before = stored_history(engine, first.model_version_id)
    path.write_text(path.read_text().replace("0,3,A", "1,1,D"))
    import_csv(engine, path, "2023-2024")
    with pytest.raises(ValueError, match="stale"):
        rankings(engine, EloConfig())
    corrected = rebuild_ratings(engine, EloConfig())
    after = stored_history(engine, corrected.model_version_id)
    assert before != after and len(after) == 4
    assert any(
        old[2] != new[2] for old, new in zip(before, after, strict=True) if old[5] == 2
    )  # shared club's downstream pre-match rating changed
    assert rankings(engine, EloConfig())["season"] == "2023-2024"


def test_fingerprint_detects_direct_result_changes(database):
    engine, _ = database
    first = rebuild_ratings(engine, EloConfig())
    with Session(engine) as session, session.begin():
        session.scalar(select(Match).order_by(Match.id)).home_goals = 5
    with pytest.raises(ValueError, match="stale"):
        rankings(engine, EloConfig())
    assert rebuild_ratings(engine, EloConfig()).rebuilt
    assert len(stored_history(engine, first.model_version_id)) == 4


def test_mid_rebuild_failure_preserves_previous_history_and_model_state(database):
    engine, _ = database
    first = rebuild_ratings(engine, EloConfig())
    original = stored_history(engine, first.model_version_id)

    def fail(*_):
        raise RuntimeError("simulated rating write failure")

    event.listen(RatingHistory, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            rebuild_ratings(engine, EloConfig(), force=True)
        with pytest.raises(RuntimeError, match="simulated"):
            rebuild_ratings(engine, EloConfig(k_factor=30))
    finally:
        event.remove(RatingHistory, "before_insert", fail)
    assert stored_history(engine, first.model_version_id) == original
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ModelVersion)) == 1
        assert not session.scalar(select(ModelVersion)).needs_rebuild
    assert not rebuild_ratings(engine, EloConfig()).rebuilt


def test_unfinished_matches_are_never_processed(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        for i, status in enumerate(["scheduled", "postponed", "cancelled", "abandoned"]):
            session.add(
                Match(
                    source="test",
                    season="2023-2024",
                    match_date=date(2023, 9, i + 1),
                    home_team_id=1,
                    away_team_id=2,
                    status=status,
                )
            )
    result = rebuild_ratings(engine, EloConfig())
    assert result.matches == 2
    with Session(engine) as session:
        assert not any(
            m.processed for m in session.scalars(select(Match).where(Match.status != "finished"))
        )


def test_rankings_have_real_computed_values_and_snapshot_date(database):
    engine, _ = database
    with pytest.raises(ValueError, match="missing or stale"):
        rankings(engine, EloConfig())
    rebuild_ratings(engine, EloConfig())
    result = rankings(engine, EloConfig())
    assert result["as_of"] == "2023-08-19"
    assert [row["rank"] for row in result["rankings"]] == [1, 2, 3]
    assert result["rankings"][0]["team"] == "Man City"
    assert sum(row["elo"] for row in result["rankings"]) == pytest.approx(4500)


def test_empty_database_does_not_create_model(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'empty.sqlite3'}")
    Base.metadata.create_all(engine)
    with pytest.raises(ValueError, match="No finished matches"):
        rebuild_ratings(engine, EloConfig())
    with Session(engine) as session:
        assert session.scalar(select(func.count()).select_from(ModelVersion)) == 0
    engine.dispose()


def test_rankings_only_include_latest_completed_season(database):
    engine, _ = database
    with Session(engine) as session, session.begin():
        ids = {t.display_name: t.id for t in session.scalars(select(Team))}
        session.add(
            Match(
                source="test",
                season="2024-2025",
                match_date=date(2024, 8, 1),
                home_team_id=ids["Man City"],
                away_team_id=ids["Arsenal"],
                home_goals=0,
                away_goals=0,
                status="finished",
            )
        )
    rebuild_ratings(engine, EloConfig())
    assert {row["team"] for row in rankings(engine, EloConfig())["rankings"]} == {
        "Man City",
        "Arsenal",
    }
