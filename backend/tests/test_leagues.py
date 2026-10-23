"""Focused multi-league integration tests, using small, explicit result fixtures."""

import copy
import json
from datetime import datetime

import numpy as np
import pandas as pd
import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from alembic import command
from app.api.data import DataUnavailable, league_data
from app.core.season import season_config
from app.db.models import Base, Match, ModelVersion, SquadValue
from app.db.session import ROOT, get_engine
from app.elo.engine import update_ratings
from app.ingestion.historical import ImportValidationError, import_csv
from app.ingestion.squads import import_squads
from app.ingestion.teams import verified_roster
from app.main import create_app
from app.services.season import calculate_season, refresh_season

SEASON = "2026-2027"
HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"


def domestic_snapshot(value):
    """Without UCL edges, domestic figures stay isolated; pool metadata is shared."""
    value = copy.deepcopy(value)
    metadata = value[0] if isinstance(value, tuple) else value
    for key in ("refreshed_at", "results_through", "pool_matches", "pool_teams", "ucl_matches"):
        metadata.pop(key, None)
    return value


@pytest.fixture
def leagues(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'leagues.sqlite3'}")
    Base.metadata.create_all(engine)
    england = tmp_path / "epl.csv"
    spain = tmp_path / "laliga.csv"
    england.write_text(HEADER + "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H\n")
    spain.write_text(
        HEADER + "SP1,21/08/2026,20:00,Barcelona,Real Madrid,2,1,H\n"
        "SP1,28/08/2026,20:00,Real Madrid,Barcelona,1,1,D\n"
    )
    refresh_season(engine, SEASON, england)
    yield engine, england, spain
    engine.dispose()


def test_unconnected_domestic_matches_preserve_other_league_figures(leagues):
    engine, england, spain = leagues
    before = league_data(engine, SEASON)
    refresh_season(engine, SEASON, spain, league="laliga")
    assert domestic_snapshot(league_data(engine, SEASON)) == domestic_snapshot(before)
    spanish = league_data(engine, SEASON, "laliga")
    assert {c["id"] for c in before[0]["clubs"]}.isdisjoint(c["id"] for c in spanish[0]["clubs"])
    assert spanish[0]["matches"] == 2 and spanish[0]["squad_coverage"] == 20
    assert {c["name"] for c in spanish[0]["clubs"]} == verified_roster("laliga", SEASON)
    england.write_text(england.read_text().replace("3,0,H", "0,1,A"))
    refresh_season(engine, SEASON, england)
    assert domestic_snapshot(league_data(engine, SEASON, "laliga")) == domestic_snapshot(spanish)
    assert league_data(engine, SEASON) != before


def test_la_liga_calculation_uses_the_same_engine_and_parameters(leagues):
    engine, _, spain = leagues
    refresh_season(engine, SEASON, spain, league="laliga")
    league, results, histories = league_data(engine, SEASON, "laliga")
    config = season_config()
    for club in league["clubs"]:
        expected = 1500 + np.clip(
            config.squad_log_scale * np.log(club["squad_value"] / config.squad_reference_eur),
            -config.squad_cap,
            config.squad_cap,
        )
        assert club["initial_rating"] == pytest.approx(expected)
        assert club["played"] == club["won"] + club["drawn"] + club["lost"]
        assert club["goal_difference"] == club["goals_for"] - club["goals_against"]
        assert histories[club["id"]][-1]["rating"] == club["rating"]
    first = results[-1]
    clubs = {c["id"]: c for c in league["clubs"]}
    expected = update_ratings(
        clubs[first["home_id"]]["initial_rating"],
        clubs[first["away_id"]]["initial_rating"],
        2,
        1,
        config.elo,
    )
    assert first["home_change"] == expected.home_change
    assert first["away_change"] == -first["home_change"]
    assert sum(c["rating"] for c in league["clubs"]) == pytest.approx(
        sum(c["initial_rating"] for c in league["clubs"])
    )


@pytest.mark.parametrize(
    "row",
    [
        "E0,21/08/2026,20:00,Barcelona,Real Madrid,2,1,H\n",
        "SP1,21/08/2026,20:00,Arsenal,Real Madrid,2,1,H\n",
        "SP1,21/08/2026,20:00,Barcelona,Unknown,2,1,H\n",
        "SP1,21/08/2026,20:00,Barcelona,Real Madrid,2,1,D\n",
    ],
)
def test_rejects_wrong_division_club_and_outcome_without_mutation(leagues, row):
    engine, _, spain = leagues
    before = league_data(engine, SEASON)
    spain.write_text(HEADER + row)
    with pytest.raises(ImportValidationError):
        refresh_season(engine, SEASON, spain, league="laliga")
    assert domestic_snapshot(league_data(engine, SEASON)) == domestic_snapshot(before)
    with Session(engine) as session:
        assert session.scalars(select(Match).where(Match.league == "laliga")).all() == []


def test_madrid_kickoff_conversion_and_repeat_import(leagues):
    engine, _, spain = leagues
    first = import_csv(engine, spain, SEASON, league="laliga")
    second = import_csv(engine, spain, SEASON, league="laliga")
    assert first.inserted == second.unchanged == 2
    with Session(engine) as session:
        match = session.scalar(select(Match).where(Match.league == "laliga").order_by(Match.id))
        assert match.kickoff_at == datetime(2026, 8, 21, 18, 0)  # Madrid CEST, not London BST
    with pytest.raises(ValueError, match="No verified roster"):
        import_csv(engine, spain, "2027-2028", league="laliga")


def test_la_liga_squads_match_verified_roster_and_source(leagues):
    engine, _, _ = leagues
    frame = pd.read_csv(ROOT / "data/squads/laliga-2026-2027.csv")
    manifest = json.loads((ROOT / "data/rosters/laliga-2026-2027.json").read_text())
    assert set(frame.team) == {c["provider_name"] for c in manifest["clubs"]}
    assert len(frame) == 20 and (frame.value_eur > 0).all()
    assert set(frame.as_of) == {"2026-09-06"}
    assert set(frame.source_url) == {manifest["valuation_source"]}
    assert import_squads(engine, ROOT / "data/squads/laliga-2026-2027.csv", SEASON, "laliga") == 20
    with pytest.raises(ImportValidationError, match="Unknown team"):
        import_squads(engine, ROOT / "data/squads/2026-2027.csv", SEASON, "laliga")


def test_unified_staleness_invalidates_every_view_and_rebuilds_atomically(leagues):
    engine, _, spain = leagues
    refresh_season(engine, SEASON, spain, league="laliga")
    spanish = league_data(engine, SEASON, "laliga")
    with Session(engine) as session, session.begin():
        session.scalar(select(SquadValue).where(SquadValue.league == "epl")).value_eur += 100
    with pytest.raises(DataUnavailable):
        league_data(engine, SEASON)
    with pytest.raises(DataUnavailable):
        league_data(engine, SEASON, "laliga")
    calculate_season(engine, SEASON)
    assert domestic_snapshot(league_data(engine, SEASON, "laliga")) == domestic_snapshot(spanish)


def test_spanish_import_does_not_invalidate_legacy_epl_model(leagues):
    engine, _, spain = leagues
    with Session(engine) as session, session.begin():
        session.add(ModelVersion(config_hash="x" * 64, parameters={}, needs_rebuild=False))
        session.scalar(select(Match)).processed = True
    refresh_season(engine, SEASON, spain, league="laliga")
    with Session(engine) as session:
        assert not session.scalar(select(ModelVersion)).needs_rebuild
        assert session.scalar(select(Match).where(Match.league == "epl")).processed


def test_api_refresh_routes_only_selected_league_and_checks_team_scope(leagues, monkeypatch):
    import app.main as module

    engine, _, spain = leagues
    refresh_season(engine, SEASON, spain, league="laliga")
    with TestClient(create_app(engine, SEASON)) as client:
        english = client.get("/api/league").json()
        spanish = client.get("/api/league?league=laliga").json()
        assert english["league_id"] == "epl" and spanish["league_id"] == "laliga"
        for league, data, other in [("epl", english, "laliga"), ("laliga", spanish, "epl")]:
            club = next(c for c in data["clubs"] if c["played"])
            detail = client.get(f"/api/teams/{club['id']}?league={league}")
            assert detail.status_code == 200
            assert detail.json()["club"] == club
            assert len(detail.json()["history"]) == club["played"] + 1
            assert client.get(f"/api/teams/{club['id']}?league={other}").status_code == 404
        called = []

        def refresh(bind, season, **kwargs):
            called.append(kwargs["league"])
            return refresh_season(bind, season, spain, league=kwargs["league"])

        monkeypatch.setattr(module, "refresh_season", refresh)
        assert client.post("/api/refresh?league=laliga").status_code == 200
        assert called == ["laliga"]
        assert domestic_snapshot(client.get("/api/league").json()) == domestic_snapshot(english)
        for method, url in [
            (client.get, "/api/league"),
            (client.post, "/api/refresh"),
            (client.get, "/api/teams/1"),
        ]:
            assert method(url + "?league=eredivisie").status_code == 422


def test_failed_spanish_refresh_rolls_back_and_preserves_both_leagues(leagues, tmp_path):
    engine, _, spain = leagues
    refresh_season(engine, SEASON, spain, league="laliga")
    before = [league_data(engine, SEASON, league) for league in ["epl", "laliga"]]
    spain.write_text(spain.read_text().replace("2,1,H", "1,2,A"))
    with pytest.raises(ImportValidationError):
        refresh_season(engine, SEASON, spain, ROOT / "data/squads/2026-2027.csv", league="laliga")
    assert [league_data(engine, SEASON, league) for league in ["epl", "laliga"]] == before


def test_additive_migration_preserves_existing_epl_rows(tmp_path, monkeypatch):
    path = tmp_path / "migration.sqlite3"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    config = Config(str(ROOT / "backend/alembic.ini"))
    command.upgrade(config, "fdeead65fb74")
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(
            text("INSERT INTO teams (canonical_name, display_name) VALUES ('Arsenal', 'Arsenal')")
        )
    command.upgrade(config, "head")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT id,canonical_name,league FROM teams")).all() == [
            (1, "Arsenal", "epl")
        ]
        assert conn.execute(text("PRAGMA foreign_key_check")).all() == []
    engine.dispose()


@pytest.fixture
def five_leagues(leagues, tmp_path):
    """Small synthetic results exercise real reviewed roster/value files without network."""
    from app.core.leagues import LEAGUES

    engine, england, spain = leagues
    files = {"epl": england, "laliga": spain}
    refresh_season(engine, SEASON, spain, league="laliga")
    for league in ("seriea", "bundesliga", "ligue1"):
        manifest = json.loads((ROOT / f"data/rosters/{league}-{SEASON}.json").read_text())
        home, away = [c["provider_name"] for c in manifest["clubs"][:2]]
        path = tmp_path / f"{league}.csv"
        path.write_text(
            HEADER + f"{LEAGUES[league].division},28/08/2026,20:00,{home},{away},2,1,H\n"
        )
        files[league] = path
        refresh_season(engine, SEASON, path, league=league)
    return engine, files


def test_all_five_api_rosters_stats_and_histories_are_isolated(five_leagues):
    from app.core.leagues import LEAGUES

    engine, _ = five_leagues
    seen = set()
    with TestClient(create_app(engine, SEASON)) as client:
        for league, info in LEAGUES.items():
            data = client.get(f"/api/league?league={league}").json()
            assert len(data["clubs"]) == info.club_count
            assert data["squad_coverage"] == info.club_count
            assert data["squad_reference_eur"] == season_config().squad_reference_eur
            ids = {c["id"] for c in data["clubs"]}
            assert seen.isdisjoint(ids)
            seen |= ids
            for club in data["clubs"]:
                detail = client.get(f"/api/teams/{club['id']}?league={league}").json()
                assert detail["club"] == club
                assert len(detail["history"]) == club["played"] + 1
                assert detail["history"][-1]["rating"] == club["rating"]
                for match in detail["results"]:
                    assert match["home_id"] in ids and match["away_id"] in ids
                    assert match["home_change"] == -match["away_change"]
                assert club["played"] == club["won"] + club["drawn"] + club["lost"]
                assert club["goal_difference"] == club["goals_for"] - club["goals_against"]
            for other in LEAGUES.keys() - {league}:
                assert client.get(f"/api/teams/{next(iter(ids))}?league={other}").status_code == 404


@pytest.mark.parametrize("league", ["seriea", "bundesliga", "ligue1"])
def test_new_league_refresh_is_idempotent_and_preserves_other_four(
    five_leagues, league, monkeypatch
):
    import app.main as module
    from app.core.leagues import LEAGUES

    engine, files = five_leagues
    before = {key: league_data(engine, SEASON, key) for key in LEAGUES}
    files[league].write_text(files[league].read_text().replace("2,1,H", "1,1,D"))
    called = []

    def selected_refresh(bind, season, **kwargs):
        selected = kwargs["league"]
        called.append(selected)
        return refresh_season(bind, season, files[selected], league=selected)

    monkeypatch.setattr(module, "refresh_season", selected_refresh)
    with TestClient(create_app(engine, SEASON)) as client:
        assert client.post(f"/api/refresh?league={league}").status_code == 200
    assert called == [league]
    assert league_data(engine, SEASON, league)[1] != before[league][1]
    for other in LEAGUES.keys() - {league}:
        assert domestic_snapshot(league_data(engine, SEASON, other)) == domestic_snapshot(
            before[other]
        )
    again = refresh_season(engine, SEASON, files[league], league=league)
    assert again["import"]["unchanged"] == 1
    assert again["matches"] == 1 and again["history_rows"] == 2


@pytest.mark.parametrize("league", ["seriea", "bundesliga", "ligue1"])
def test_new_league_mappings_values_timezone_and_wrong_club_rejection(five_leagues, league):
    from app.core.leagues import LEAGUES
    from app.ingestion.teams import resolve_team

    engine, files = five_leagues
    manifest = json.loads((ROOT / f"data/rosters/{league}-{SEASON}.json").read_text())
    frame = pd.read_csv(ROOT / f"data/squads/{league}-{SEASON}.csv")
    assert len(frame) == LEAGUES[league].club_count
    assert set(frame.team) == {c["provider_name"] for c in manifest["clubs"]}
    assert set(frame.source_url) == {manifest["valuation_source"]}
    assert (frame.value_eur > 0).all() and np.isfinite(frame.value_eur).all()
    before = league_data(engine, SEASON, league)
    with Session(engine) as session:
        for club in manifest["clubs"]:
            assert resolve_team(
                session, club["provider_name"], "football-data.co.uk", league
            ) == resolve_team(session, club["official_name"], "football-data.co.uk", league)
        match = session.scalar(select(Match).where(Match.league == league))
        assert match.kickoff_at == datetime(2026, 8, 28, 18, 0)
    home = manifest["clubs"][0]["provider_name"]
    files[league].write_text(files[league].read_text().replace(home, "Arsenal"))
    with pytest.raises(ImportValidationError, match="Unknown team"):
        refresh_season(engine, SEASON, files[league], league=league)
    assert league_data(engine, SEASON, league) == before
    with pytest.raises(ValueError, match="No verified roster"):
        import_csv(engine, files[league], "2027-2028", league=league)
