"""Incremental updates preserve identities, audit times and chronological ratings."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.data import league_data
from app.db.models import Base, ImportRun, Match, SeasonHistory, SeasonRating
from app.db.session import get_engine
from app.ingestion.historical import ImportValidationError, import_csv
from app.main import create_app
from app.services.season import calculate_season, refresh_season

HEADER = "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR,Status\n"
FIRST = "E0,21/08/2026,20:00,Arsenal,Coventry,3,0,H,\n"
SECOND = "E0,28/08/2026,20:00,Man City,Arsenal,1,1,D,\n"


@pytest.fixture
def dataset(tmp_path, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(2026, 10, 28, 12, tzinfo=timezone.utc).astimezone(tz)

    monkeypatch.setattr("app.ingestion.historical.datetime", Clock)
    engine = get_engine(f"sqlite:///{tmp_path / 'freshness.sqlite3'}")
    Base.metadata.create_all(engine)
    path = tmp_path / "results.csv"

    def write(rows):
        path.write_text(HEADER + rows)
        return path

    yield engine, write
    engine.dispose()


def ratings(engine):
    with Session(engine) as session:
        return dict(session.execute(select(SeasonRating.team_id, SeasonRating.rating)).all())


def test_incremental_import_correction_and_date_change_preserve_match_identity(dataset):
    engine, write = dataset
    refresh_season(engine, "2026-2027", write(SECOND))
    original = ratings(engine)
    # Newly received earlier result must be placed before the already imported match.
    result = refresh_season(engine, "2026-2027", write(SECOND + FIRST))
    assert result["import"]["inserted"] == 1
    assert ratings(engine) != original
    with Session(engine) as session:
        pairs = session.execute(
            select(SeasonHistory.sequence, Match.match_date)
            .join(Match)
            .order_by(SeasonHistory.sequence)
        ).all()
        assert [d for _, d in pairs] == sorted(d for _, d in pairs)
        match_id = session.scalar(select(Match.id).where(Match.home_goals == 3))
        history = session.scalars(select(SeasonHistory).order_by(SeasonHistory.sequence)).all()
        previous = {}
        for row in history:
            if row.team_id in previous:
                assert row.rating_before == pytest.approx(previous[row.team_id])
            previous[row.team_id] = row.rating_after
    before = ratings(engine)
    corrected = FIRST.replace("21/08/2026", "24/08/2026").replace("3,0,H", "0,2,A")
    result = refresh_season(engine, "2026-2027", write(SECOND + corrected))
    assert result["import"]["updated"] == 1
    assert ratings(engine) != before
    with Session(engine) as session:
        assert session.scalar(select(func.count(Match.id))) == 2
        assert session.get(Match, match_id).match_date.isoformat() == "2026-08-24"
    stable = ratings(engine)
    assert (
        refresh_season(engine, "2026-2027", write(SECOND + corrected))["import"]["unchanged"] == 2
    )
    assert ratings(engine) == stable


def test_full_snapshot_detects_missing_previously_completed_match_and_rolls_back(dataset):
    engine, write = dataset
    refresh_season(engine, "2026-2027", write(FIRST + SECOND))
    before = ratings(engine)
    with Session(engine) as session:
        imports = session.scalar(select(func.count(ImportRun.id)))
    with pytest.raises(ImportValidationError, match="missing 1 previously completed"):
        import_csv(engine, write(SECOND), "2026-2027", complete_snapshot=True)
    with Session(engine) as session:
        assert session.scalar(select(func.count(ImportRun.id))) == imports
        assert session.scalar(select(func.count(Match.id))) == 2
    assert ratings(engine) == before


def test_unplayed_postponed_and_future_fixtures_never_become_results(dataset):
    engine, write = dataset
    rows = (
        FIRST
        + "E0,29/10/2026,20:00,Man City,Arsenal,,,,\n"
        + "E0,20/08/2026,20:00,Coventry,Arsenal,0,0,D,postponed\n"
    )
    summary = import_csv(engine, write(rows), "2026-2027")
    assert summary.inserted == 1 and summary.skipped == 2
    with pytest.raises(ImportValidationError, match="Future fixture"):
        import_csv(engine, write(FIRST.replace("21/08/2026", "29/10/2026")), "2026-2027")
    with pytest.raises(ImportValidationError, match="Invalid non-negative"):
        import_csv(engine, write(FIRST.replace("3,0,H", "3,,H")), "2026-2027")
    with Session(engine) as session:
        assert session.scalar(select(func.count(Match.id))) == 1


def test_freshness_is_per_league_not_global_rating_calculation(dataset):
    engine, write = dataset
    refresh_season(engine, "2026-2027", write(FIRST))
    epl = league_data(engine, "2026-2027")[0]
    spanish = (
        FIRST.replace("E0", "SP1")
        .replace("21/08/2026", "22/08/2026")
        .replace("Arsenal,Coventry", "Barcelona,Real Madrid")
    )
    refresh_season(engine, "2026-2027", write(spanish), league="laliga")
    calculate_season(engine, "2026-2027")
    current = league_data(engine, "2026-2027")[0]
    assert current["results_through"] == epl["results_through"] == "2026-08-21"
    assert current["last_synced_at"] == epl["last_synced_at"]
    assert league_data(engine, "2026-2027", "laliga")[0]["results_through"] == "2026-08-22"
    with TestClient(create_app(engine, "2026-2027")) as client:
        response = client.get("/api/league")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.json()["last_synced_at"] == epl["last_synced_at"]


@pytest.mark.parametrize(
    "platform,setting,expected",
    [
        ("darwin", None, {"cafile": "/etc/ssl/cert.pem"}),
        ("darwin", "SSL_CERT_FILE", {}),
        ("darwin", "SSL_CERT_DIR", {}),
        ("linux", None, {}),
    ],
)
def test_system_tls_bundle_fallback_respects_explicit_settings(
    monkeypatch, platform, setting, expected
):
    from types import SimpleNamespace

    from app.ingestion.historical import provider_ssl_context

    monkeypatch.delenv("SSL_CERT_FILE", raising=False)
    monkeypatch.delenv("SSL_CERT_DIR", raising=False)
    if setting:
        monkeypatch.setenv(setting, "/explicit/trust")
    monkeypatch.setattr("app.ingestion.historical.sys.platform", platform)
    monkeypatch.setattr(
        "app.ingestion.historical.ssl.get_default_verify_paths",
        lambda: SimpleNamespace(cafile=None),
    )
    monkeypatch.setattr("app.ingestion.historical.Path.is_file", lambda _: True)
    calls = []
    monkeypatch.setattr(
        "app.ingestion.historical.ssl.create_default_context", lambda **kwargs: calls.append(kwargs)
    )
    provider_ssl_context()
    assert calls == [expected]


def test_failed_replay_does_not_advance_successful_sync_or_commit_results(dataset, monkeypatch):
    engine, write = dataset
    refresh_season(engine, "2026-2027", write(FIRST))
    before = league_data(engine, "2026-2027")[0]

    def fail(*args, **kwargs):
        raise RuntimeError("replay failed")

    monkeypatch.setattr("app.services.season.calculate_season", fail)
    with pytest.raises(RuntimeError, match="replay failed"):
        refresh_season(engine, "2026-2027", write(FIRST + SECOND))
    after = league_data(engine, "2026-2027")[0]
    assert after["last_synced_at"] == before["last_synced_at"]
    assert after["matches"] == before["matches"] == 1
    assert after["clubs"] == before["clubs"]
