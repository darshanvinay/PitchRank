from pathlib import Path

import pytest
from alembic.config import Config
from sqlalchemy import func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from alembic import command
from app.db.models import (
    Base,
    ImportRun,
    Match,
    MatchObservation,
    ModelVersion,
    Team,
    TeamAlias,
)
from app.db.session import get_engine
from app.ingestion.historical import ImportValidationError, import_csv
from app.ingestion.teams import resolve_team, seed_teams

HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
ROW = "E0,11/08/2023,20:00,Burnley,Man City,0,3,A\n"


@pytest.fixture
def engine(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'test.sqlite3'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def csv(tmp_path):
    def write(content=ROW):
        path = tmp_path / "results.csv"
        path.write_text(HEADER + content)
        return path

    return write


def count(engine, model):
    with Session(engine) as session:
        return session.scalar(select(func.count()).select_from(model))


def test_import_normalizes_dates_names_and_kickoff(engine, csv):
    summary = import_csv(engine, csv(), "2023-2024")
    assert (summary.inserted, summary.updated, summary.unchanged) == (1, 0, 0)
    with Session(engine) as session:
        match = session.scalar(select(Match))
        assert match.match_date.isoformat() == "2023-08-11"
        assert match.kickoff_at.isoformat() == "2023-08-11T19:00:00"
        assert match.home_goals == 0 and match.away_goals == 3
        assert not match.processed
        run = session.scalar(select(ImportRun))
        assert len(run.sha256) == 64
        observation = session.scalar(select(MatchObservation))
        assert observation.payload["HomeTeam"] == "Burnley"
        assert observation.row_number == 2


def test_reimport_is_idempotent_but_audited(engine, csv):
    path = csv()
    import_csv(engine, path, "2023-2024")
    result = import_csv(engine, path, "2023-2024")
    assert result.unchanged == 1 and result.inserted == 0
    assert count(engine, Match) == 1
    assert count(engine, ImportRun) == 2
    assert count(engine, MatchObservation) == 2


def test_same_source_correction_preserves_old_observation_and_invalidates(engine, csv):
    import_csv(engine, csv(), "2023-2024")
    with Session(engine) as session, session.begin():
        session.add(ModelVersion(config_hash="a" * 64, parameters={}, needs_rebuild=False))
        session.scalar(select(Match)).processed = True
    result = import_csv(engine, csv(ROW.replace("0,3,A", "1,1,D")), "2023-2024")
    assert result.updated == 1
    with Session(engine) as session:
        assert session.scalar(select(Match)).home_goals == 1
        assert not session.scalar(select(Match)).processed
        assert session.scalar(select(ModelVersion)).needs_rebuild
        rows = session.scalars(select(MatchObservation).order_by(MatchObservation.id)).all()
        assert [r.payload["FTHG"] for r in rows] == ["0", "1"]


@pytest.mark.parametrize(
    "bad",
    [
        ROW.replace("Burnley", "Unknown FC"),
        ROW.replace("0,3,A", "-1,3,A"),
        ROW.replace("0,3,A", "0.5,3,A"),
        ROW.replace("0,3,A", ",3,A"),
        ROW.replace("0,3,A", "0,3,H"),
        ROW.replace("11/08/2023", "31/02/2023"),
        ROW.replace("11/08/2023", "11/08/2021"),
        ROW.replace("E0,", "E1,"),
        ROW.replace("Man City", "Burnley"),
        ROW.replace("20:00", "25:00"),
    ],
)
def test_invalid_import_rolls_back_everything(engine, csv, bad):
    with pytest.raises(ImportValidationError, match="row"):
        import_csv(engine, csv(ROW + bad), "2023-2024")
    assert count(engine, Match) == 0
    assert count(engine, Team) == 0
    assert count(engine, ImportRun) == 0


def test_missing_columns(engine, tmp_path):
    path = tmp_path / "bad.csv"
    path.write_text("Date,HomeTeam\n11/08/2023,Burnley\n")
    with pytest.raises(ImportValidationError, match="Missing required columns"):
        import_csv(engine, path, "2023-2024")


def test_conflicting_duplicates_in_file_rejected(engine, csv):
    with pytest.raises(ImportValidationError, match="Conflicting duplicate"):
        import_csv(engine, csv(ROW + ROW.replace("0,3,A", "1,1,D")), "2023-2024")
    assert count(engine, Match) == 0


def test_identical_duplicates_in_file_collapsed(engine, csv):
    result = import_csv(engine, csv(ROW + ROW), "2023-2024")
    assert result.inserted == 1


def test_cross_source_identity_and_conflict(engine, csv):
    import_csv(engine, csv(), "2023-2024")
    alternate = ROW.replace("Man City", "Manchester City FC").replace("Burnley", "Burnley FC")
    result = import_csv(engine, csv(alternate), "2023-2024", source="football-data.org")
    assert result.unchanged == 1
    with pytest.raises(ImportValidationError, match="Review required"):
        import_csv(
            engine,
            csv(alternate.replace("0,3,A", "1,1,D")),
            "2023-2024",
            source="football-data.org",
        )
    assert count(engine, Match) == 1
    assert count(engine, ImportRun) == 2


def test_name_mapping_is_explicit_and_source_scoped(engine):
    with Session(engine) as session, session.begin():
        seed_teams(session)
        seed_teams(session)
        assert resolve_team(session, "  MAN   UNITED ", "football-data.co.uk") == resolve_team(
            session, "Manchester United FC", "football-data.org"
        )
        assert count(engine, Team) == 0  # uncommitted transaction is isolated
        with pytest.raises(ValueError, match="Unknown team"):
            resolve_team(session, "Manchester Untied", "football-data.org")
    assert count(engine, Team) == 51


def test_missing_kickoff_is_null_and_two_digit_dates_supported(engine, csv):
    import_csv(engine, csv(ROW.replace("20:00", "").replace("11/08/2023", "11/08/23")), "2023-2024")
    with Session(engine) as session:
        assert session.scalar(select(Match)).kickoff_at is None


def test_constraints_and_foreign_keys(engine):
    with Session(engine) as session:
        with pytest.raises(IntegrityError):
            session.execute(
                text(
                    "INSERT INTO team_aliases (team_id, source, name) "
                    "VALUES (999, 'test', 'unknown')"
                )
            )
            session.commit()
        session.rollback()
    assert count(engine, TeamAlias) == 0


def test_transaction_rolls_back_on_mid_write_failure(engine, csv, monkeypatch):
    from sqlalchemy import event

    def fail(*_):
        raise RuntimeError("simulated disk/write failure")

    event.listen(MatchObservation, "before_insert", fail)
    try:
        with pytest.raises(RuntimeError, match="simulated"):
            import_csv(engine, csv(), "2023-2024")
    finally:
        event.remove(MatchObservation, "before_insert", fail)
    assert count(engine, Match) == 0
    assert count(engine, ImportRun) == 0
    assert count(engine, Team) == 0


def test_migrations_upgrade_downgrade(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'migration.sqlite3'}")
    config = Config(str(Path(__file__).parents[1] / "alembic.ini"))
    command.upgrade(config, "head")
    engine = get_engine()
    assert count(engine, Match) == 0
    command.check(config)
    command.downgrade(config, "base")
    command.upgrade(config, "head")
    assert count(engine, Match) == 0
    engine.dispose()
