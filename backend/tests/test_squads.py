from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Base, Match, SquadValue
from app.db.session import get_engine
from app.ingestion.historical import ImportValidationError, import_csv
from app.ingestion.squads import import_squads


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'squads.sqlite3'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def write_csv(path: Path, values: str) -> Path:
    path.write_text("team,value_eur,as_of,source_url\n" + values)
    return path


def test_squad_import_and_correction_are_idempotent(engine, tmp_path):
    path = write_csv(
        tmp_path / "values.csv", "Arsenal,100000000,2026-09-01,https://example.com/source\n"
    )
    assert import_squads(engine, path, "2026-2027") == 1
    import_squads(engine, path, "2026-2027")
    path.write_text(path.read_text().replace("100000000", "200000000"))
    import_squads(engine, path, "2026-2027")
    with Session(engine) as session:
        values = session.scalars(select(SquadValue)).all()
        assert len(values) == 1 and values[0].value_eur == 200000000
        assert str(values[0].as_of) == "2026-09-01"
        assert values[0].source_url == "https://example.com/source"


@pytest.mark.parametrize(
    "bad",
    [
        "Arsenal,-1,2026-09-01,https://example.com/source",
        "Arsenal,nan,2026-09-01,https://example.com/source",
        "Arsenal,100,2026-09-01,",
        "Unknown Club,100,2026-09-01,https://example.com/source",
        "Arsenal,100,bad-date,https://example.com/source",
        "Arsenal,100,2999-09-01,https://example.com/source",
        "Arsenal,100,2026-09-01,javascript:bad",
    ],
)
def test_bad_squad_file_rolls_back(engine, tmp_path, bad):
    path = write_csv(
        tmp_path / "bad.csv", "Chelsea,200,2026-09-01,https://example.com/source\n" + bad
    )
    with pytest.raises(ImportValidationError, match="row"):
        import_squads(engine, path, "2026-2027")
    with Session(engine) as session:
        assert session.scalars(select(SquadValue)).all() == []


def test_squad_duplicate_rejected(engine, tmp_path):
    row = "Arsenal,100,2026-09-01,https://example.com/source\n"
    path = write_csv(tmp_path / "bad.csv", row + row)
    with pytest.raises(ImportValidationError, match="Duplicate"):
        import_squads(engine, path, "2026-2027")


def test_current_season_results_use_existing_ingestion(engine, tmp_path):
    path = tmp_path / "results.csv"
    path.write_text(
        "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
        "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H\n"
    )
    assert import_csv(engine, path, "2026-2027").inserted == 1
    assert import_csv(engine, path, "2026-2027").unchanged == 1
    with Session(engine) as session:
        assert len(session.scalars(select(Match)).all()) == 1
