from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Base, SquadValue
from app.db.session import get_engine
from app.main import create_app
from app.services.season import refresh_season


@pytest.fixture
def client(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'api.sqlite3'}")
    Base.metadata.create_all(engine)
    path = tmp_path / "results.csv"
    path.write_text(
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H\n"
    )
    squads = Path(__file__).parents[2] / "data/squads/2026-2027.csv"
    refresh_season(engine, "2026-2027", path, squads)
    with TestClient(create_app(engine, "2026-2027")) as client:
        yield client, engine
    engine.dispose()


def test_league_statistics_reconcile(client):
    http, _ = client
    response = http.get("/api/league")
    assert response.status_code == 200
    data = response.json()
    assert len(data["clubs"]) == 20
    assert data["matches"] == 1 and data["squad_coverage"] == 20
    assert sum(c["played"] for c in data["clubs"]) == 2
    assert sum(c["won"] for c in data["clubs"]) == sum(c["lost"] for c in data["clubs"]) == 1
    assert (
        sum(c["goals_for"] for c in data["clubs"])
        == sum(c["goals_against"] for c in data["clubs"])
        == 3
    )
    for c in data["clubs"]:
        assert c["played"] == c["won"] + c["drawn"] + c["lost"]
        assert c["goal_difference"] == c["goals_for"] - c["goals_against"]
    assert [c["rating"] for c in data["clubs"]] == sorted(
        [c["rating"] for c in data["clubs"]], reverse=True
    )


def test_team_history_and_result_changes_match_snapshot(client):
    http, _ = client
    club = next(c for c in http.get("/api/league").json()["clubs"] if c["name"] == "Arsenal")
    response = http.get(f"/api/teams/{club['id']}")
    assert response.status_code == 200
    data = response.json()
    assert data["history"][0]["rating"] == club["initial_rating"]
    assert data["history"][-1]["rating"] == club["rating"]
    assert data["results"][0]["home_change"] == -data["results"][0]["away_change"]
    assert data["history"][-1]["change"] == data["results"][0]["home_change"]
    assert data["club"]["goals_for"] == 3
    assert http.get("/api/teams/99999").status_code == 404
    assert http.get("/api/predictions").status_code == 404


def test_stale_values_are_not_served(client):
    http, engine = client
    with Session(engine) as session, session.begin():
        session.scalar(select(SquadValue)).value_eur += 1
    response = http.get("/api/league")
    assert response.status_code == 503
    assert "recalculate" in response.json()["detail"]


def test_refresh_provider_failure_preserves_data(client, monkeypatch):
    import app.main as module

    http, _ = client
    before = http.get("/api/league").json()

    def fail(*_, **__):
        raise OSError("provider unavailable")

    monkeypatch.setattr(module, "refresh_season", fail)
    response = http.post("/api/refresh")
    assert response.status_code == 502
    assert "unchanged" in response.json()["detail"]
    assert http.get("/api/league").json() == before


def test_refresh_success_and_cross_site_rejection(client, monkeypatch):
    import app.main as module

    http, _ = client
    called = []
    monkeypatch.setattr(module, "refresh_season", lambda *_, **__: called.append(True))
    assert http.post("/api/refresh", headers={"Origin": "https://other.example"}).status_code == 403
    assert not called
    assert http.post("/api/refresh", headers={"Origin": "http://testserver"}).status_code == 200
    assert called == [True]


def test_archived_xg_is_read_from_the_selected_clubs_perspective(client):
    from app.db.models import Match, MatchXG

    http, engine = client
    with Session(engine) as session, session.begin():
        match = session.scalar(select(Match))
        home, away = match.home_team_id, match.away_team_id
        session.add(
            MatchXG(
                match_id=match.id,
                source="understat",
                external_id="1",
                home_xg=2.4,
                away_xg=0.6,
                source_url="https://understat.com/match/1",
                archive_url="https://understat.com",
                archive_sha256="0" * 64,
                provider_date=match.match_date,
            )
        )
    home_xg = http.get(f"/api/teams/{home}/xg").json()[0]
    away_xg = http.get(f"/api/teams/{away}/xg").json()[0]
    assert (home_xg["xg"], home_xg["xga"]) == (2.4, 0.6)
    assert (away_xg["xg"], away_xg["xga"]) == (0.6, 2.4)
    assert (home_xg["opponent"], away_xg["opponent"]) == ("Coventry", "Arsenal")
    assert http.get("/api/teams/999999/xg").status_code == 404
