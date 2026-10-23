import hashlib
import io
import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import select, update
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.leagues import Competition, competition
from app.db.models import ImportRun, Match, MatchObservation, ModelVersion
from app.ingestion.teams import resolve_team, seed_teams, verified_roster

SOURCE = "football-data.co.uk"
REQUIRED = {"Date", "HomeTeam", "AwayTeam", "FTHG", "FTAG", "FTR"}


class ImportValidationError(ValueError):
    pass


class Result(BaseModel):
    model_config = ConfigDict(strict=True)
    match_date: date
    kickoff_at: datetime | None
    home_team_id: int
    away_team_id: int
    home_goals: int = Field(ge=0)
    away_goals: int = Field(ge=0)
    outcome: str

    @model_validator(mode="after")
    def validate_result(self):
        if self.home_team_id == self.away_team_id:
            raise ValueError("A club cannot play itself")
        expected = (
            "H"
            if self.home_goals > self.away_goals
            else ("A" if self.home_goals < self.away_goals else "D")
        )
        if self.outcome != expected:
            raise ValueError("FTR disagrees with the full-time score")
        return self


@dataclass(frozen=True)
class ImportSummary:
    run_id: int
    inserted: int
    updated: int
    unchanged: int


def season_start(season: str) -> int:
    if not re.fullmatch(r"\d{4}-\d{4}", season):
        raise ImportValidationError("Season must use YYYY-YYYY, e.g. 2023-2024")
    start, end = map(int, season.split("-"))
    if start < 1992 or end != start + 1:
        raise ImportValidationError("Season must be consecutive years starting in 1992 or later")
    return start


def download_season(season: str, directory: Path, league: str = "epl") -> Path:
    division = competition(league).division
    start = season_start(season)
    code = f"{start % 100:02d}{(start + 1) % 100:02d}"
    url = f"https://www.football-data.co.uk/mmz4281/{code}/{division}.csv"
    request = Request(url, headers={"User-Agent": "PitchRank/0.1 historical research"})
    with urlopen(request, timeout=60) as response:
        payload = response.read(10_000_001)
    if len(payload) > 10_000_000:
        raise ImportValidationError("CSV exceeds 10 MB limit")
    # Check before retaining a possible HTML/error response as a dataset.
    parse_csv(payload, season)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{division}-{season}.csv"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    return path


def parse_csv(payload: bytes, season: str) -> pd.DataFrame:
    season_start(season)
    try:
        frame = pd.read_csv(
            io.BytesIO(payload), dtype=str, keep_default_na=False, encoding="utf-8-sig"
        )
    except (ValueError, UnicodeError, pd.errors.ParserError) as exc:
        raise ImportValidationError(f"Cannot parse CSV: {exc}") from exc
    missing = REQUIRED - set(frame.columns)
    if missing:
        raise ImportValidationError(f"Missing required columns: {', '.join(sorted(missing))}")
    frame = frame.apply(lambda column: column.str.strip())
    frame = frame.loc[~frame.eq("").all(axis=1)]
    if frame.empty:
        raise ImportValidationError("CSV contains no match results")
    return frame


def parse_date(value: str) -> date:
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Invalid match date {value!r}")


def score(value: str) -> int:
    if not re.fullmatch(r"\d+", value):
        raise ValueError(f"Invalid non-negative integer score {value!r}")
    return int(value)


def import_csv(
    engine: Engine,
    path: Path,
    season: str,
    source: str = SOURCE,
    location: str | None = None,
    league: str = "epl",
) -> ImportSummary:
    info = (
        competition(league)
        if league != "ucl"
        else Competition(
            "Champions League", "Europe", "UCL", "UTC", "https://fixturedownload.com", ""
        )
    )
    if league != "ucl":
        verified_roster(league, season)
    payload = path.read_bytes()
    frame = parse_csv(payload, season)
    start = season_start(season)
    # One transaction includes seed, validation, all writes, and the successful import audit.
    with Session(engine) as session, session.begin():
        seed_teams(session, league)
        validated = []
        seen = {}
        errors = []
        for index, row in frame.iterrows():
            row_number = int(index) + 2
            try:
                if "Div" in row and row["Div"] != info.division:
                    raise ValueError(f"Expected {info.name} division {info.division}")
                day = parse_date(row["Date"])
                # Wide boundaries admit the COVID-delayed 2019-2020 season (July finish).
                if not date(start, 7, 1) <= day <= date(start + 1, 8, 1):
                    raise ValueError(f"Date {day} falls outside season {season}")
                kickoff = None
                if row.get("Time", ""):
                    local = datetime.strptime(f"{day} {row['Time']}", "%Y-%m-%d %H:%M")
                    kickoff = local.replace(tzinfo=ZoneInfo(info.timezone)).astimezone(timezone.utc)
                stage = row.get("Stage", "domestic")
                if stage not in (
                    {"league", "knockout", "finals"} if league == "ucl" else {"domestic"}
                ):
                    raise ValueError("Invalid competition stage")
                if row.get("Neutral", "0") not in {"0", "1"}:
                    raise ValueError("Neutral venue must be 0 or 1")
                result = Result(
                    match_date=day,
                    kickoff_at=kickoff,
                    home_team_id=resolve_team(session, row["HomeTeam"], source, league),
                    away_team_id=resolve_team(session, row["AwayTeam"], source, league),
                    home_goals=score(row["FTHG"]),
                    away_goals=score(row["FTAG"]),
                    outcome=row["FTR"],
                )
                key = (day, result.home_team_id, result.away_team_id)
                if key in seen and seen[key] != result:
                    raise ValueError("Conflicting duplicate results within the CSV")
                if key not in seen:
                    validated.append((row_number, result, row.to_dict()))
                    seen[key] = result
            except ValueError as exc:
                errors.append(f"row {row_number}: {exc}")
        if errors:
            raise ImportValidationError("Import rejected:\n" + "\n".join(errors))
        run = ImportRun(
            league=league,
            source=source,
            location=location or str(path.resolve()),
            sha256=hashlib.sha256(payload).hexdigest(),
            season=season,
        )
        session.add(run)
        session.flush()
        inserted = updated = unchanged = 0
        for row_number, result, raw in validated:
            match = session.scalar(
                select(Match).where(
                    Match.season == season,
                    Match.league == league,
                    Match.match_date == result.match_date,
                    Match.home_team_id == result.home_team_id,
                    Match.away_team_id == result.away_team_id,
                )
            )
            if match is None:
                values = result.model_dump(exclude={"outcome"})
                match = Match(
                    stage=raw.get("Stage", "domestic"),
                    neutral=raw.get("Neutral", "0") == "1",
                    **values,
                    season=season,
                    source=source,
                    status="finished",
                    league=league,
                )
                session.add(match)
                session.flush()
                inserted += 1
            else:
                corrected = (match.home_goals, match.away_goals, match.status) != (
                    result.home_goals,
                    result.away_goals,
                    "finished",
                )
                # Never silently overwrite a conflicting result from a different provider.
                if corrected and match.source != source:
                    raise ImportValidationError(
                        f"row {row_number}: conflicting result from {source}; "
                        f"existing match {match.id} belongs to {match.source}. Review required."
                    )
                stored_kickoff = match.kickoff_at
                if stored_kickoff and stored_kickoff.tzinfo is None:
                    stored_kickoff = stored_kickoff.replace(tzinfo=timezone.utc)
                time_changed = result.kickoff_at is not None and stored_kickoff != result.kickoff_at
                metadata_changed = (match.stage, match.neutral) != (
                    raw.get("Stage", "domestic"),
                    raw.get("Neutral", "0") == "1",
                )
                if corrected or time_changed or metadata_changed:
                    match.stage, match.neutral = (
                        raw.get("Stage", "domestic"),
                        raw.get("Neutral", "0") == "1",
                    )
                    match.home_goals, match.away_goals = result.home_goals, result.away_goals
                    match.status = "finished"
                    if result.kickoff_at:
                        match.kickoff_at = result.kickoff_at
                    match.processed = False
                    updated += 1
                else:
                    unchanged += 1
            session.add(
                MatchObservation(
                    match_id=match.id, import_run_id=run.id, row_number=row_number, payload=raw
                )
            )
        if inserted or updated:
            # Future engines must rebuild before serving a model marked stale.
            if league == "epl":
                session.execute(update(ModelVersion).values(needs_rebuild=True))
            session.execute(update(Match).where(Match.league == league).values(processed=False))
        run.inserted, run.updated, run.unchanged = inserted, updated, unchanged
        return ImportSummary(run.id, inserted, updated, unchanged)
