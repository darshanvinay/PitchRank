import json
from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.data import league_data
from app.core.elo import EloConfig
from app.core.season import SeasonConfig
from app.db.models import Base, SeasonRating, Team
from app.db.session import get_engine
from app.elo.engine import update_ratings
from app.elo.replay import PlayedMatch
from app.elo.season import replay_season
from app.ingestion.champions import import_champions, normalize_results
from app.ingestion.historical import ImportValidationError
from app.ingestion.teams import resolve_team
from app.main import create_app
from app.services.season import calculate_season, refresh_season


@pytest.mark.parametrize("importance", [1.0, 1.25, 1.5, 1.75])
def test_importance_scales_existing_formula_and_remains_zero_sum(importance):
    ordinary = update_ratings(1550, 1500, 3, 0, EloConfig())
    weighted = update_ratings(1550, 1500, 3, 0, EloConfig(), importance)
    assert weighted.home_change == pytest.approx(ordinary.home_change * importance)
    assert weighted.away_change == -weighted.home_change
    assert update_ratings(1500, 1500, 1, 1, EloConfig(), importance, neutral=True).home_change == 0


def test_chronology_and_carry_forward_apply_prior_once():
    one = PlayedMatch(1, "2024-2025", date(2024, 9, 1), None, 1, 2, 1, 0)
    two = PlayedMatch(2, "2025-2026", date(2025, 9, 1), None, 1, 2, 1, 1, "league")
    three = PlayedMatch(3, "2026-2027", date(2026, 9, 1), None, 1, 3, 0, 2, "finals", True)
    config = SeasonConfig()
    result, initial = replay_season([three, two, one], {1: 1e9, 2: None, 3: None}, config)
    assert [e.match.id for e in result.entries] == [1, 2, 3]
    assert result.entries[1].update.home_before == result.entries[0].update.home_after
    assert result.entries[2].update.home_before == result.entries[1].update.home_after
    assert result.entries[0].update.home_before == initial[1]
    assert sum(result.ratings.values()) == pytest.approx(sum(initial.values()))


def fixture(home, away, score, round_number=1, day="2026-09-08"):
    return {
        "MatchNumber": 1,
        "RoundNumber": round_number,
        "DateUtc": f"{day} 19:00:00Z",
        "HomeTeam": home,
        "AwayTeam": away,
        "HomeTeamScore": score[0],
        "AwayTeamScore": score[1],
        "Winner": home,
    }


def test_ucl_normalization_stages_neutral_venue_and_scheduled_results():
    rows = [
        fixture("Paris", "Arsenal", (1, 1), 17),
        fixture("Man City", "Porto", (2, 0), 1, "2026-09-09"),
        fixture("Barcelona", "Benfica", (1, 0), 11, "2026-09-10"),
        fixture("Bayern München", "Celtic", (None, None)),
    ]
    frame = normalize_results(json.dumps(rows).encode(), "2026-2027")
    assert list(frame.Stage) == ["finals", "league", "knockout"]
    assert list(frame.Neutral) == [1, 0, 0]
    assert frame.iloc[0].FTR == "D"  # Winner field must not turn shootouts into Elo wins.
    with pytest.raises(ImportValidationError, match="Duplicate"):
        normalize_results(json.dumps([rows[0], rows[0]]).encode(), "2026-2027")
    with pytest.raises(ImportValidationError, match="Unknown.*round"):
        normalize_results(
            json.dumps([fixture("Paris", "Arsenal", (1, 1), 18)]).encode(), "2026-2027"
        )


def test_ucl_alias_identity_external_opponents_and_connected_top25(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'connected.sqlite3'}")
    Base.metadata.create_all(engine)
    for league, home, away, division in [
        ("epl", "Man City", "Arsenal", "E0"),
        ("laliga", "Barcelona", "Real Madrid", "SP1"),
        ("seriea", "Inter", "Milan", "I1"),
        ("bundesliga", "Bayern Munich", "Dortmund", "D1"),
        ("ligue1", "Paris SG", "Monaco", "F1"),
    ]:
        path = tmp_path / f"{league}.csv"
        path.write_text(
            "Div,Date,Time,HomeTeam,AwayTeam,FTHG,FTAG,FTR\n"
            f"{division},22/08/2026,20:00,{home},{away},1,1,D\n"
        )
        refresh_season(engine, "2026-2027", path, league=league)
    before = {
        c["name"]: c["rating"] for c in league_data(engine, "2026-2027", "europe")[0]["clubs"]
    }
    rows = [
        fixture("Paris", "Man City", (3, 0)),
        fixture("Bayern München", "Barcelona", (1, 2), 1, "2026-09-09"),
        fixture("Porto", "Inter", (0, 2), 1, "2026-09-10"),
    ]
    path = tmp_path / "ucl.csv"
    normalize_results(json.dumps(rows).encode(), "2026-2027").to_csv(path, index=False)
    assert import_champions(engine, path, "2026-2027").inserted == 3
    assert import_champions(engine, path, "2026-2027").unchanged == 3
    calculate_season(engine, "2026-2027")
    data, results, history = league_data(engine, "2026-2027", "europe")
    assert len(data["clubs"]) == 25
    assert all(
        c["league_id"] in {"epl", "laliga", "seriea", "bundesliga", "ligue1"} for c in data["clubs"]
    )
    assert "Porto" not in [c["name"] for c in data["clubs"]]
    with Session(engine) as session:
        psg = resolve_team(session, "Paris", "fixturedownload.com", "ucl")
        assert psg == resolve_team(session, "Paris SG", "football-data.co.uk", "ligue1")
        porto = resolve_team(session, "Porto", "fixturedownload.com", "ucl")
        assert session.scalar(select(SeasonRating).where(SeasonRating.team_id == porto)) is not None
        assert session.scalar(select(Team).where(Team.id == porto)).league == "other"
    after = {c["name"]: c["rating"] for c in data["clubs"]}
    assert after["Paris Saint-Germain"] > before["Paris Saint-Germain"]
    for league in ["epl", "laliga", "seriea", "bundesliga", "ligue1"]:
        for club in league_data(engine, "2026-2027", league)[0]["clubs"]:
            if club["id"] in [c["id"] for c in data["clubs"]]:
                assert club["rating"] == next(
                    c["rating"] for c in data["clubs"] if c["id"] == club["id"]
                )
    paris = next(c for c in data["clubs"] if c["name"] == "Paris Saint-Germain")
    assert paris["last_change"] == history[paris["id"]][-1]["change"]
    assert (
        paris["played"] == 1 and len(history[paris["id"]]) == 3
    )  # domestic stats; mixed Elo history
    with TestClient(create_app(engine, "2026-2027")) as client:
        assert client.get("/api/league?league=europe").status_code == 200
        detail = client.get(f"/api/teams/{paris['id']}?league=ligue1").json()
        ucl = next(m for m in detail["results"] if m["competition"] == "Champions League")
        assert ucl["away_league"] == "epl"
    engine.dispose()


@pytest.mark.parametrize(
    "season,day,home,away,raw,expected",
    [
        ("2024-2025", "2025-02-19", "PSV", "Juventus", (3, 1), (2, 1)),
        ("2025-2026", "2026-02-25", "Juventus", "Galatasaray", (3, 2), (3, 0)),
        ("2025-2026", "2026-03-17", "Sporting CP", "Bodø/Glimt", (5, 0), (3, 0)),
    ],
)
def test_reviewed_extra_time_scores_use_ninety_minutes(season, day, home, away, raw, expected):
    rows = [fixture(home, away, raw, 9, day)]
    rows += [fixture(f"Home {n}", f"Away {n}", (0, 0), 1, day) for n in range(188)]
    frame = normalize_results(json.dumps(rows).encode(), season)
    assert tuple(frame.iloc[0][["FTHG", "FTAG"]]) == expected
