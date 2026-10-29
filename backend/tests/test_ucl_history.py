from pathlib import Path

import pytest
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from alembic import command
from app.db.models import Base, ImportRun, Match, MatchObservation, Team
from app.db.session import get_engine
from app.ingestion.ucl_history import import_history, read_history, score_parts
from app.main import create_app
from app.services.season import refresh_season

FIXTURES = Path(__file__).parent / "fixtures/ucl"


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'ucl.sqlite3'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.mark.parametrize(
    "season,count", [("2011-2012", 125), ("2019-2020", 119), ("2024-2025", 189), ("2025-2026", 189)]
)
def test_real_archive_eras_parse_complete_stage_and_tie_coverage(season, count):
    report = read_history(FIXTURES / f"{season}.txt", season)
    assert not report["errors"]
    assert len(report["rows"]) == count
    if season == "2019-2020":
        assert all(
            r["tie_format"] == "single"
            for r in report["rows"]
            if r["round"] in {"quarterfinal", "semifinal"}
        )
    if season == "2024-2025":
        psv = next(r for r in report["rows"] if r["home"] == "PSV" and r["date"] == "2025-02-19")
        assert (psv["home_goals"], psv["extra_time_home"]) == (2, 3)
        assert psv["erratum"]["original_score"] == [3, 1]
        assert "3-1 (0-0)" in psv["source_text"]
    if season == "2011-2012":
        final = next(r for r in report["rows"] if r["round"] == "final")
        assert (final["home_goals"], final["away_goals"]) == (1, 1)
        assert (final["penalties_home"], final["penalties_away"]) == (3, 4)
        napoli = [
            r
            for r in report["rows"]
            if r["round"] == "round_of_16" and "Chelsea FC" in (r["home"], r["away"])
        ]
        assert sorted(r["leg"] for r in napoli) == [1, 2]
        assert len({r["tie_id"] for r in napoli}) == 1
        assert next(r for r in napoli if r["leg"] == 2)["extra_time_home"] == 4


def test_safe_regulation_extra_time_penalty_split():
    assert score_parts("3-4 pen. 1-1 a.e.t. (1-1, 0-0)")["home_goals"] == 1
    assert score_parts("4-1 a.e.t. (3-1, 1-0)")["home_goals"] == 3
    assert score_parts("8-7 pen. 0-0 a.e.t. (0-0)")["home_goals"] == 0
    for invalid in ["3-1 a.e.t.", "1-1 (2-0)", "-1-0", "3-3 pen. 1-1 a.e.t. (1-1, 0-0)"]:
        with pytest.raises(ValueError):
            score_parts(invalid)


def test_idempotent_history_aliases_and_preserved_domestic_data(engine, tmp_path):
    file = tmp_path / "epl.csv"
    file.write_text(
        "Div,Date,HomeTeam,AwayTeam,FTHG,FTAG,FTR\nE0,21/08/2026,Arsenal,Man City,1,1,D\n"
    )
    refresh_season(engine, "2026-2027", file)
    with TestClient(create_app(engine, "2026-2027")) as client:
        before = client.get("/api/league").json()
        first = import_history(engine, FIXTURES / "2011-2012.txt", "2011-2012")
        assert first["inserted"] == 125 and first["imported"]
        second = import_history(engine, FIXTURES / "2011-2012.txt", "2011-2012")
        assert second["inserted"] == 0 and second["unchanged"] == 125
        assert client.get("/api/league").json() == before
        coverage = client.get("/api/ucl/seasons").json()["seasons"]
        assert len(coverage) == 21
        assert next(s for s in coverage if s["season"] == "2011-2012")["complete"]
        assert (
            next(s for s in coverage if s["season"] == "2005-2006")["status"]
            == "source_unavailable"
        )
        matches = client.get("/api/ucl/matches?season=2011-2012").json()["matches"]
        assert [m["date"] for m in matches] == sorted(m["date"] for m in matches)
        finals = client.get("/api/ucl/matches?season=2011-2012&stage=final").json()["matches"]
        assert len(finals) == 1 and finals[0]["penalties_away"] == 4
        bayern = next(
            t
            for t in client.get("/api/ucl/matches?season=2011-2012").json()["teams"]
            if t["name"] == "Bayern Munich"
        )
        team = client.get(f"/api/ucl/matches?season=2011-2012&team_id={bayern['id']}").json()[
            "matches"
        ]
        assert all(bayern["id"] in (m["home_id"], m["away_id"]) for m in team)
        assert client.get("/api/ucl/matches?season=bad").status_code == 422
        assert client.get("/api/ucl/matches?season=2011-2012&stage=bogus").status_code == 422
    with Session(engine) as session:
        assert session.scalar(select(func.count(Match.id)).where(Match.league == "ucl")) == 125
        assert (
            session.scalar(
                select(func.count(Team.id)).where(Team.canonical_name == "Bayern Munich")
            )
            == 1
        )
        assert session.scalar(select(func.count(MatchObservation.id))) == 251


def test_missing_malformed_duplicate_and_unresolved_records(engine, tmp_path):
    original = (FIXTURES / "2011-2012.txt").read_text()
    path = tmp_path / "season.txt"
    line = next(
        row for row in original.splitlines() if "Manchester City (ENG)" in row and " v " in row
    )
    path.write_text(original.replace(line, ""))
    result = import_history(engine, path, "2011-2012")
    assert result["errors"] and not result["imported"]
    path.write_text(original.replace("Bayern München", "Unknown Munich"))
    result = import_history(engine, path, "2011-2012")
    assert result["unresolved_teams"] == ["Unknown Munich"]
    assert not result["imported"]
    path.write_text(original.replace(line, line + "\n" + line))
    result = import_history(engine, path, "2011-2012")
    assert result["duplicates"] == 1 and result["inserted"] == 125
    with Session(engine) as session:
        assert session.scalar(select(func.count(ImportRun.id))) == 1
    path.write_text(original.replace("1-1 (0-0)", "bad score", 1))
    assert read_history(path, "2011-2012")["errors"]


def test_cross_provider_score_conflict_rejected_without_overwrite(engine):
    assert import_history(engine, FIXTURES / "2011-2012.txt", "2011-2012")["imported"]
    with Session(engine) as session, session.begin():
        match = session.scalar(select(Match))
        identity = match.id
        match.source = "another-provider"
        match.home_goals = 99
    report = import_history(engine, FIXTURES / "2011-2012.txt", "2011-2012")
    assert not report["imported"] and "conflict" in report["errors"][0]
    with Session(engine) as session:
        assert session.get(Match, identity).home_goals == 99
        assert session.scalar(select(func.count(ImportRun.id))) == 1


def test_nullable_migration_preserves_existing_rows_and_is_repeatable(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "b571ccaa9802")
    engine = get_engine()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO teams(id,league,canonical_name,display_name) "
                "VALUES (1,'epl','One','One'),(2,'epl','Two','Two')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO matches(id,league,season,match_date,home_team_id,away_team_id,"
                "home_goals,away_goals,status,source,processed,created_at,updated_at) "
                "VALUES (1,'epl','2023-2024','2023-09-01',1,2,1,0,'finished','test',0,"
                "CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)"
            )
        )
    command.upgrade(config, "head")
    command.upgrade(config, "head")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT id,home_goals,ucl_detail FROM matches")).one()
        assert tuple(row) == (1, 1, None)
    command.check(config)
    engine.dispose()


def test_pinned_download_receipt_and_local_file_provenance(engine, tmp_path, monkeypatch):
    import hashlib
    import io
    import json

    from app.ingestion.ucl_history import REVISION, download_history

    payload = (FIXTURES / "2011-2012.txt").read_bytes()
    monkeypatch.setattr(
        "app.ingestion.ucl_history.urlopen", lambda *args, **kwargs: io.BytesIO(payload)
    )
    path = download_history("2011-2012", tmp_path)
    receipt = json.loads(path.with_suffix(".source.json").read_text())
    assert receipt["sha256"] == hashlib.sha256(payload).hexdigest()
    assert import_history(engine, path, "2011-2012")["imported"]
    with Session(engine) as session:
        assert session.scalar(select(Match)).ucl_detail["revision"] == REVISION
    # A locally edited file must not retain a claim of being byte-identical to the pin.
    path.write_bytes(payload + b"\n")
    assert import_history(engine, path, "2011-2012")["imported"]
    with Session(engine) as session:
        assert session.scalar(select(Match)).ucl_detail["revision"] is None
        latest = session.scalar(select(ImportRun).order_by(ImportRun.id.desc()))
        assert latest.location == str(path.resolve())
