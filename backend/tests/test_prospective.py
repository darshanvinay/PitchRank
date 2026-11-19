import sqlite3
from datetime import UTC, date, datetime

import pytest
from sqlalchemy.orm import Session
from test_knockout import dataset as knockout_dataset

from app.backtesting import prospective
from app.db.models import Match

base_dataset = knockout_dataset


def test_prospective_capture_is_append_only_and_scores_after_both_legs(
    base_dataset, tmp_path, monkeypatch
):
    class Clock(datetime):
        instant = datetime(2026, 11, 18, tzinfo=UTC)

        @classmethod
        def now(cls, tz=None):
            return cls.instant.astimezone(tz)

    monkeypatch.setattr(prospective, "datetime", Clock)
    with Session(base_dataset) as session, session.begin():
        for mid, day, home, away in [(101, 24, 1, 2), (102, 30, 2, 1)]:
            session.add(
                Match(
                    id=mid,
                    season="2026-2027",
                    league="ucl",
                    stage="knockout",
                    match_date=date(2026, 11, day),
                    kickoff_at=datetime(2026, 11, day, tzinfo=UTC),
                    home_team_id=home,
                    away_team_id=away,
                    status="scheduled",
                    source="test",
                )
            )
    ledger = tmp_path / "forecast.sqlite3"
    capture = prospective.capture(base_dataset, ledger, 101, 102)
    assert capture["xg_fallback"]
    assert len(set(capture["forecasts"].values())) == 1
    with pytest.raises(sqlite3.IntegrityError):
        prospective.capture(base_dataset, ledger, 101, 102)
    with prospective.ledger(ledger) as conn, pytest.raises(sqlite3.IntegrityError):
        conn.execute("DELETE FROM forecasts")
    assert len(prospective.evaluate(base_dataset, ledger)["pending"]) == 1

    Clock.instant = datetime(2026, 12, 1, tzinfo=UTC)
    with pytest.raises(ValueError, match="before first-leg kickoff"):
        prospective.capture(base_dataset, tmp_path / "late.sqlite3", 101, 102)
    with Session(base_dataset) as session, session.begin():
        for mid, home, away in [(101, 2, 0), (102, 0, 0)]:
            match = session.get(Match, mid)
            match.status, match.home_goals, match.away_goals = "finished", home, away
    result = prospective.evaluate(base_dataset, ledger)
    assert result["pending"] == []
    assert result["resolved"][0]["actual_a"]
    assert result["resolved"][0]["forecasts"] == capture["forecasts"]
    assert result["metrics"]["Model A"]["ties"] == 1
