from datetime import date
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.elo import EloConfig
from app.core.season import SeasonConfig
from app.db.models import Base, Match
from app.db.session import get_engine
from app.elo.engine import update_ratings
from app.elo.replay import PlayedMatch
from app.elo.season import replay_season
from app.ingestion.domestic_history import import_domestic_history
from app.ingestion.historical import import_csv
from app.ingestion.ucl_history import import_history, read_history
from app.main import create_app
from app.services.historical import get_team_elo_at_date, historical_elo_snapshot


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'history.sqlite3'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_full_domestic_history_is_idempotent_and_rejects_missing_rows(engine, tmp_path):
    original = Path(__file__).parent / "fixtures/domestic/D1-2010-2011.csv"
    path = tmp_path / original.name
    path.write_bytes(original.read_bytes())
    first = import_domestic_history(engine, "2010-2011", "2010-2011", "bundesliga", tmp_path)[
        "seasons"
    ][0]
    assert first["matches"] == 306 and first["inserted"] == 306 and not first["errors"]
    second = import_domestic_history(engine, "2010-2011", "2010-2011", "bundesliga", tmp_path)[
        "seasons"
    ][0]
    assert second["inserted"] == 0 and second["unchanged"] == 306
    path.write_text("\n".join(path.read_text().splitlines()[:-1]) + "\n")
    result = import_domestic_history(engine, "2010-2011", "2010-2011", "bundesliga", tmp_path)[
        "seasons"
    ][0]
    assert "Expected 306" in result["errors"][0]
    path.write_text(original.read_text().replace("Bayern Munich", "Unreviewed FC"))
    result = import_domestic_history(engine, "2010-2011", "2010-2011", "bundesliga", tmp_path)[
        "seasons"
    ][0]
    assert result["unmatched_teams"] == ["Unreviewed FC"]
    with Session(engine) as session:
        assert session.scalar(select(func.count(Match.id))) == 306


def test_cutoff_excludes_same_day_future_results_and_future_membership(engine, tmp_path):
    path = tmp_path / "results.csv"
    path.write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,01/02/2021,Arsenal,Man City,2,0,H\n"
        "E0,16/02/2021,Man City,Arsenal,0,3,A\n"
        "E0,01/03/2021,Liverpool,Arsenal,9,0,H\n"
    )
    import_csv(engine, path, "2020-2021")
    with Session(engine) as session:
        arsenal = session.scalar(select(Match).order_by(Match.match_date)).home_team_id
        future = session.scalar(select(Match).where(Match.match_date == date(2021, 3, 1)))
        future_id = future.id
        liverpool = future.home_team_id
    cutoff = date(2021, 2, 16)
    before = historical_elo_snapshot(engine, cutoff)
    assert before["matches"] == 1 and liverpool not in before["ratings"]
    expected = update_ratings(1500, 1500, 2, 0, EloConfig()).home_after
    assert get_team_elo_at_date(arsenal, cutoff, engine=engine) == pytest.approx(expected)
    with Session(engine) as session, session.begin():
        session.get(Match, future_id).home_goals = 0
        session.get(Match, future_id).away_goals = 99
    assert historical_elo_snapshot(engine, cutoff) == before
    with TestClient(create_app(engine)) as client:
        response = client.get(f"/api/teams/{arsenal}/historical-elo?cutoff=2021-02-16")
        assert response.status_code == 200 and response.json()["rating"] == pytest.approx(expected)
        assert response.json()["cutoff_exclusive"]


def test_offseason_regression_carry_and_covid_overlapping_leagues():
    first = PlayedMatch(1, "2019-2020", date(2020, 8, 2), None, 1, 2, 3, 0)
    other = PlayedMatch(2, "2020-2021", date(2020, 8, 15), None, 3, 4, 0, 0)
    ucl = PlayedMatch(3, "2019-2020", date(2020, 8, 18), None, 1, 5, 1, 0, "finals", True)
    new = PlayedMatch(4, "2020-2021", date(2020, 9, 1), None, 1, 2, 0, 0)
    config = SeasonConfig()
    result, _ = replay_season([new, ucl, other, first], dict.fromkeys(range(1, 6)), config, 0.25)
    assert [r.match.id for r in result.entries] == [1, 2, 3, 4]
    assert result.entries[-1].update.home_before == pytest.approx(
        1500 + (result.entries[2].update.home_after - 1500) * 0.75
    )
    carried, _ = replay_season([first, new], {1: None, 2: None}, config, 0)
    assert carried.entries[1].update.home_before == carried.entries[0].update.home_after
    neutral, _ = replay_season([ucl], {1: None, 5: None}, config, 0)
    assert neutral.entries[0].update.expected_home == 0.5


def test_covid_domestic_finish_and_ucl_dates_preserve_ids(engine, tmp_path):
    path = tmp_path / "italy.csv"
    path.write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nI1,02/08/2020,Inter,Atalanta,2,0,H\n"
    )
    assert import_csv(engine, path, "2019-2020", league="seriea").inserted == 1
    source = Path(__file__).parent / "fixtures/ucl/2019-2020.txt"
    parsed = read_history(source, "2019-2020")
    semi = next(r for r in parsed["rows"] if r["round"] == "semifinal" and "Paris" in r["away"])
    assert semi["date"] == "2020-08-18"
    assert not parsed["errors"]
    assert import_history(engine, source, "2019-2020")["imported"]
    with Session(engine) as session, session.begin():
        match = session.scalar(select(Match).where(Match.match_date == date(2020, 8, 18)))
        identity = match.id
        match.match_date = date(2019, 8, 18)
        match.ucl_detail = {**match.ucl_detail, "date": "2019-08-18"}
    report = import_history(engine, source, "2019-2020")
    assert report["inserted"] == 0 and report["enriched"] == 1
    with Session(engine) as session:
        assert session.get(Match, identity).match_date == date(2020, 8, 18)
