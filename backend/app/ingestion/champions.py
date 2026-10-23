"""Normalize the public UEFA result feed into the existing audited CSV importer."""

import hashlib
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen

import pandas as pd

from app.db.session import ROOT
from app.ingestion.historical import ImportValidationError, import_csv, season_start

SOURCE = "fixturedownload.com"


def normalize_results(payload: bytes, season: str) -> pd.DataFrame:
    year = season_start(season)
    rows = json.loads(payload)
    if not isinstance(rows, list) or not rows:
        raise ImportValidationError("Champions League feed contains no fixtures")
    overrides = {
        (r["season"], r["date"], r["home"], r["away"]): r["score"]
        for r in json.loads((ROOT / "data/ucl-regulation-scores.json").read_text())
    }
    output, seen = [], set()
    for item in rows:
        home, away = item.get("HomeTeamScore"), item.get("AwayTeamScore")
        if home is None and away is None:
            continue
        if type(home) is not int or type(away) is not int or min(home, away) < 0:
            raise ImportValidationError("Incomplete or invalid Champions League score")
        kickoff = datetime.fromisoformat(item["DateUtc"].replace("Z", "+00:00"))
        if kickoff.tzinfo is None:
            raise ImportValidationError("UCL kickoff must include UTC offset")
        kickoff = kickoff.astimezone(timezone.utc)
        if not date(year, 7, 1) <= kickoff.date() < date(year + 1, 7, 1):
            raise ImportValidationError("Champions League date outside selected season")
        if kickoff.date() > datetime.now(timezone.utc).date():
            raise ImportValidationError("A future fixture cannot have a completed score")
        number = item["RoundNumber"]
        if type(number) is not int or not 1 <= number <= 17:
            raise ImportValidationError("Unknown Champions League round; review importance mapping")
        stage = "league" if number <= 8 else ("knockout" if number <= 14 else "finals")
        key = (kickoff.date().isoformat(), item["HomeTeam"], item["AwayTeam"])
        if key in seen:
            raise ImportValidationError("Duplicate Champions League fixture")
        seen.add(key)
        # The provider's score includes extra time on three reviewed historic fixtures.
        # Penalty Winner is deliberately ignored: a drawn match remains a draw for Elo.
        home, away = overrides.get((season, *key), (home, away))
        output.append(
            {
                "Div": "UCL",
                "Date": key[0],
                "Time": kickoff.strftime("%H:%M"),
                "HomeTeam": item["HomeTeam"],
                "AwayTeam": item["AwayTeam"],
                "FTHG": home,
                "FTAG": away,
                "FTR": "H" if home > away else ("A" if away > home else "D"),
                "Stage": stage,
                "Neutral": int(number == 17),
            }
        )
    if not output:
        raise ImportValidationError("No completed Champions League matches")
    if year in (2024, 2025) and len(output) != 189:
        raise ImportValidationError(
            "Historical Champions League season must have 189 main-draw matches"
        )
    return pd.DataFrame(output)


def download_champions(season: str, directory: Path) -> Path:
    year = season_start(season)
    url = f"https://fixturedownload.com/feed/json/champions-league-{year}"
    with urlopen(Request(url, headers={"User-Agent": "PitchRank/1.0"}), timeout=45) as response:
        payload = response.read(5_000_001)
    if len(payload) > 5_000_000:
        raise ImportValidationError("Champions League feed exceeds 5 MB")
    frame = normalize_results(payload, season)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"UCL-{season}.csv"
    temporary = path.with_suffix(".tmp")
    frame.to_csv(temporary, index=False)
    temporary.replace(path)
    path.with_suffix(".source.json").write_text(
        json.dumps(
            {
                "url": url,
                "sha256": hashlib.sha256(payload).hexdigest(),
                "retrieved_at": datetime.now(timezone.utc).isoformat(),
                "completed_matches": len(frame),
            },
            indent=2,
        )
    )
    return path


def import_champions(bind, path: Path, season: str):
    return import_csv(
        bind,
        path,
        season,
        source=SOURCE,
        league="ucl",
        location=f"https://fixturedownload.com/feed/json/champions-league-{season[:4]}",
    )
