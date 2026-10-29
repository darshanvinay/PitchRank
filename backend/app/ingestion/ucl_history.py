"""Pinned Openfootball main-draw archive, preserving regulation/extra-time/penalty scores."""

import hashlib
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportRun, Match, MatchObservation, Team, TeamAlias
from app.db.session import ROOT
from app.ingestion.historical import ImportValidationError, provider_ssl_context, season_start
from app.ingestion.teams import normalize_name, seed_ucl_teams

SOURCE = "openfootball/champions-league"
REVISION = "abfaeddc2ee3d14f99ecc163c9ddb46cb4d67cef"
AVAILABLE = tuple(f"{y}-{y + 1}" for y in range(2011, 2026))
ROUNDS = {"group": 96, "round_of_16": 16, "quarterfinal": 8, "semifinal": 4, "final": 1}
MONTHS = {m: i for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split(), 1)}


def expected_rounds(season):
    year = season_start(season)
    if year >= 2024:
        return {
            "league": 144,
            "playoff": 16,
            "round_of_16": 16,
            "quarterfinal": 8,
            "semifinal": 4,
            "final": 1,
        }
    return {**ROUNDS, **({"quarterfinal": 4, "semifinal": 2} if year == 2019 else {})}


def download_history(season: str, directory: Path) -> Path:
    if season not in AVAILABLE:
        raise ImportValidationError(f"{season}: absent from pinned Openfootball archive")
    short = f"{season[:4]}-{season[-2:]}"
    url = (
        f"https://raw.githubusercontent.com/openfootball/champions-league/{REVISION}/{short}/cl.txt"
    )
    with urlopen(
        Request(url, headers={"User-Agent": "PitchRank/1.0"}),
        timeout=45,
        context=provider_ssl_context(),
    ) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ImportValidationError("Historical file exceeds 2 MB")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{season}.txt"
    temporary = path.with_suffix(".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)
    path.with_suffix(".source.json").write_text(
        json.dumps(
            {"url": url, "revision": REVISION, "sha256": hashlib.sha256(payload).hexdigest()},
            indent=2,
        )
    )
    return path


def stage_name(heading):
    text = heading.lower()
    if re.match(r"gr(?:oup|uppe)\b", text):
        return "group"
    if text.startswith("league"):
        return "league"
    if text.startswith("playoffs"):
        return "playoff"
    if "round of 16" in text:
        return "round_of_16"
    if "quarterfinal" in text:
        return "quarterfinal"
    if "semifinal" in text:
        return "semifinal"
    if text in {"final", "finals, final"}:
        return "final"
    raise ValueError(f"Unknown stage {heading!r}")


def score_parts(text):
    """football.txt: shootout first, then after-ET score, then (90-minute, half-time)."""
    match = re.fullmatch(
        r"(?:(\d+)-(\d+) pen\. )?(\d+)-(\d+)(?: (a\.e\.t\.))?"
        r"(?: \((\d+)-(\d+)(?:, (\d+)-(\d+))?\))?",
        text.strip(),
    )
    if not match:
        raise ValueError(f"Unrecognized score {text!r}")
    ph, pa, h, a, aet, first_h, first_a, half_h, half_a = match.groups()
    h, a = int(h), int(a)
    if ph is not None and (not aet or ph == pa):
        raise ValueError("Invalid shootout annotation")
    if aet:
        # A lone (0-0) for a scoreless ET match is unambiguous. Other missing 90-minute
        # splits must be reviewed rather than treating an after-ET score as regulation.
        if half_h is not None:
            regulation = (int(first_h), int(first_a))
        elif h == a == 0:
            regulation = (0, 0)
        else:
            raise ValueError("Extra-time result lacks an unambiguous regulation score")
        if regulation[0] > h or regulation[1] > a:
            raise ValueError("Extra-time score decreased")
        if half_h is not None and (int(half_h) > regulation[0] or int(half_a) > regulation[1]):
            raise ValueError("Half-time score exceeds regulation score")
    else:
        regulation = (h, a)
        if first_h is not None and (int(first_h) > h or int(first_a) > a):
            raise ValueError("Half-time score exceeds final score")
    return {
        "home_goals": regulation[0],
        "away_goals": regulation[1],
        "extra_time_home": h if aet else None,
        "extra_time_away": a if aet else None,
        "penalties_home": int(ph) if ph is not None else None,
        "penalties_away": int(pa) if pa is not None else None,
    }


def read_history(path: Path, season: str):
    year = season_start(season)
    rows, errors, seen = [], [], {}
    day = round_name = group = None
    duplicates = skipped = 0
    text = path.read_text(encoding="utf-8-sig")
    errata = json.loads((ROOT / "data/ucl-history-errata.json").read_text())
    if not re.search(rf"= UEFA Champions League {year}/{str(year + 1)[-2:]}", text):
        raise ImportValidationError("File title does not match Champions League season")
    for number, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith(("#", "=")):
            continue
        try:
            if line.startswith("▪"):
                round_name = stage_name(line[1:].strip())
                found = re.fullmatch(r"Gr(?:oup|uppe) ([A-H])", line[1:].strip())
                group = found[1] if found else None
                day = None
                continue
            dated = re.fullmatch(
                r"(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (\w{3}) (\d{1,2})(?: (\d{4}))?", line
            )
            if dated:
                month = MONTHS[dated[1]]
                day = date(
                    int(dated[3])
                    if dated[3]
                    else year + int(month < 7 or round_name not in {"group", "league"}),
                    month,
                    int(dated[2]),
                )
                if not date(year, 7, 1) <= day < date(year + 1, 9, 1):
                    raise ValueError("Date outside season")
                continue
            if not re.search(r"\s+v\s+", line):
                if line.startswith("("):
                    continue  # optional scorer notes, not matches
                raise ValueError(f"Unrecognized archive line {line!r}")
            if day is None or round_name is None:
                raise ValueError("Match has no date or stage")
            if day > date.today():
                raise ValueError("Future completed historical match")
            fixture = re.fullmatch(r"(?:(\d{1,2}:\d{2})\s+)?(.+?)\s+v\s+(.+?)\s+(\d+-\d+.*)", line)
            if not fixture:
                raise ValueError("Malformed or unfinished match")
            clock, home, away, score = fixture.groups()
            home, away = [re.sub(r"\s+\([A-Z]{3}\)$", "", name).strip() for name in (home, away)]
            if home == away:
                raise ValueError("Club cannot play itself")
            row = {
                "date": day.isoformat(),
                "season": season,
                "round": round_name,
                "group": group,
                "home": home,
                "away": away,
                "status": "finished",
                "kickoff_label": clock,
                "source_line": number,
                "source_text": raw,
                **score_parts(score),
            }
            for erratum in errata:
                if (season, row["date"], home, away) == (
                    erratum["season"],
                    erratum["date"],
                    erratum["home"],
                    erratum["away"],
                ):
                    if [row["home_goals"], row["away_goals"]] != erratum["original_score"]:
                        raise ValueError(
                            "Reviewed erratum no longer matches source; review required"
                        )
                    row.update(
                        home_goals=erratum["regulation_score"][0],
                        away_goals=erratum["regulation_score"][1],
                        extra_time_home=erratum["after_extra_time"][0],
                        extra_time_away=erratum["after_extra_time"][1],
                        erratum=erratum,
                    )
            key = (row["date"], home, away)
            if key in seen:
                if any(
                    row[k] != seen[key][k]
                    for k in (
                        "round",
                        "home_goals",
                        "away_goals",
                        "extra_time_home",
                        "extra_time_away",
                        "penalties_home",
                        "penalties_away",
                    )
                ):
                    raise ValueError("Conflicting duplicate match")
                duplicates += 1
                continue
            seen[key] = row
            rows.append(row)
        except (ValueError, KeyError) as exc:
            errors.append(f"line {number}: {exc}")
    counts = Counter(row["round"] for row in rows)
    expected = expected_rounds(season)
    if dict(counts) != expected:
        errors.append(f"Stage coverage mismatch: expected {expected}; found {dict(counts)}")
    clubs = {row[t] for row in rows for t in ("home", "away")}
    # Source aliases vary between seasons, not within an individual season's file.
    if len(clubs) != (36 if year >= 2024 else 32):
        errors.append(f"Unexpected club count: {len(clubs)}")
    phase = "league" if year >= 2024 else "group"
    phase_rows = [r for r in rows if r["round"] == phase]
    appearances = Counter(t for r in phase_rows for t in (r["home"], r["away"]))
    if set(appearances) != clubs or any(
        n != (8 if year >= 2024 else 6) for n in appearances.values()
    ):
        errors.append("Incomplete group/league-phase appearances per club")
    for row in rows:
        row["leg"] = None
        row["tie_id"] = None
        row["tie_format"] = None
    ties = defaultdict(list)
    for row in rows:
        if row["round"] not in {"group", "league"}:
            ties[(row["round"], *sorted((row["home"], row["away"])))].append(row)
    for (stage, home, away), legs in ties.items():
        single = stage == "final" or (year == 2019 and stage in {"quarterfinal", "semifinal"})
        if len(legs) != (1 if single else 2):
            errors.append(f"Incomplete {stage} tie: {home} / {away}")
        ordered = sorted(legs, key=lambda row: row["date"])
        if (
            not single
            and len(ordered) == 2
            and (
                ordered[0]["home"] != ordered[1]["away"] or ordered[0]["date"] == ordered[1]["date"]
            )
        ):
            errors.append(f"Invalid home/away legs: {home} / {away}")
        key = hashlib.sha256(f"{season}|{stage}|{home}|{away}".encode()).hexdigest()[:24]
        for i, row in enumerate(ordered, 1):
            row.update(
                tie_id=key,
                leg=None if single else i,
                tie_format="single" if single else "two_legged",
                leg_basis="chronological home/away pair" if not single else None,
            )
    return {
        "season": season,
        "rows": rows,
        "expected": sum(expected.values()),
        "stage_counts": dict(counts),
        "skipped": skipped,
        "duplicates": duplicates,
        "errors": errors,
        "unresolved_teams": [],
        "source_notes": [r["erratum"] for r in rows if "erratum" in r],
    }


def seed_history_aliases(session):
    seed_ucl_teams(session)
    registry = json.loads((ROOT / "data/ucl-history-teams.json").read_text())
    for item in registry["aliases"]:
        team = session.scalar(select(Team).where(Team.canonical_name == item["canonical"]))
        if team is None:
            team = Team(
                canonical_name=item["canonical"],
                display_name=item["canonical"],
                league=item["league"],
            )
            session.add(team)
            session.flush()
        name = normalize_name(item["name"])
        alias = session.scalar(
            select(TeamAlias).where(TeamAlias.source == SOURCE, TeamAlias.name == name)
        )
        if alias and alias.team_id != team.id:
            raise ImportValidationError(f"Conflicting explicit alias: {name}")
        if alias is None:
            session.add(TeamAlias(team_id=team.id, source=SOURCE, name=name))
    session.flush()


def import_history(engine, path: Path, season: str):
    report = read_history(path, season)
    report.update(inserted=0, enriched=0, unchanged=0, imported=False)
    payload = path.read_bytes()
    short = f"{season[:4]}-{season[-2:]}"
    expected_url = (
        f"https://raw.githubusercontent.com/openfootball/champions-league/{REVISION}/{short}/cl.txt"
    )
    receipt_path = path.with_suffix(".source.json")
    receipt = json.loads(receipt_path.read_text()) if receipt_path.exists() else {}
    pinned = (
        receipt.get("sha256") == hashlib.sha256(payload).hexdigest()
        and receipt.get("url") == expected_url
    )
    location = expected_url if pinned else str(path.resolve())
    if report["errors"]:
        return {k: v for k, v in report.items() if k != "rows"}
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN IMMEDIATE")
        try:
            with Session(connection) as session, session.begin():
                seed_history_aliases(session)
                aliases = {
                    a.name: a.team_id
                    for a in session.scalars(select(TeamAlias).where(TeamAlias.source == SOURCE))
                }
                report["unresolved_teams"] = sorted(
                    {
                        r[t]
                        for r in report["rows"]
                        for t in ("home", "away")
                        if normalize_name(r[t]) not in aliases
                    }
                )
                if report["unresolved_teams"]:
                    raise ImportValidationError("Unresolved explicit club aliases")
                run = ImportRun(
                    league="ucl",
                    source=SOURCE,
                    location=location,
                    sha256=hashlib.sha256(payload).hexdigest(),
                    season=season,
                )
                session.add(run)
                session.flush()
                for row in report["rows"]:
                    home, away = (
                        aliases[normalize_name(row["home"])],
                        aliases[normalize_name(row["away"])],
                    )
                    match = session.scalar(
                        select(Match).where(
                            Match.league == "ucl",
                            Match.season == season,
                            Match.match_date == date.fromisoformat(row["date"]),
                            Match.home_team_id == home,
                            Match.away_team_id == away,
                        )
                    )
                    if match is None:
                        # Exact retained source observation allows safe correction of the
                        # old yearless COVID knockout date inference without a duplicate.
                        candidate = session.scalar(
                            select(Match).where(
                                Match.league == "ucl",
                                Match.season == season,
                                Match.source == SOURCE,
                                Match.home_team_id == home,
                                Match.away_team_id == away,
                                Match.ucl_detail["source_line"].as_integer() == row["source_line"],
                            )
                        )
                        if (
                            candidate
                            and candidate.ucl_detail.get("source_text") == row["source_text"]
                        ):
                            match = candidate
                    detail = {
                        **row,
                        "source": SOURCE,
                        "source_url": location,
                        "revision": REVISION if pinned else None,
                        "away_goals_rule": int(season[:4]) < 2021,
                    }
                    detail["source_id"] = hashlib.sha256(
                        f"{season}|{row['round']}|{row['date']}|{row['home']}|{row['away']}".encode()
                    ).hexdigest()
                    importance_stage = (
                        "league"
                        if row["round"] in {"group", "league"}
                        else ("finals" if row["round"] in {"semifinal", "final"} else "knockout")
                    )
                    neutral = row["round"] == "final" or (
                        season == "2019-2020" and row["round"] in {"quarterfinal", "semifinal"}
                    )
                    if match:
                        if (match.home_goals, match.away_goals, match.status) != (
                            row["home_goals"],
                            row["away_goals"],
                            "finished",
                        ):
                            raise ImportValidationError(
                                f"Score/status conflict with existing match {match.id}; "
                                "no scores overwritten"
                            )
                        match.match_date = date.fromisoformat(row["date"])
                        if match.ucl_detail == detail:
                            report["unchanged"] += 1
                        else:
                            match.ucl_detail = detail
                            report["enriched"] += 1
                        if match.source == SOURCE:
                            match.external_id = detail["source_id"]
                    else:
                        identity = detail["source_id"]
                        match = Match(
                            league="ucl",
                            season=season,
                            match_date=date.fromisoformat(row["date"]),
                            home_team_id=home,
                            away_team_id=away,
                            home_goals=row["home_goals"],
                            away_goals=row["away_goals"],
                            status="finished",
                            source=SOURCE,
                            external_id=identity,
                            stage=importance_stage,
                            neutral=neutral,
                            ucl_detail=detail,
                        )
                        session.add(match)
                        session.flush()
                        report["inserted"] += 1
                    session.add(
                        MatchObservation(
                            match_id=match.id,
                            import_run_id=run.id,
                            row_number=row["source_line"],
                            payload=detail,
                        )
                    )
                run.inserted, run.updated, run.unchanged = (
                    report["inserted"],
                    report["enriched"],
                    report["unchanged"],
                )
            # Preserve current leaderboard mathematics; history imports outside its configured
            # replay window are archival. A new overlap requires an explicit normal replay.
            from app.core.season import current_season, season_config

            if report["inserted"] and season >= season_config().history_start:
                from app.services.season import calculate_season

                calculate_season(connection, current_season())
            connection.commit()
            report["imported"] = True
        except (ValueError, ImportValidationError) as exc:
            connection.rollback()
            report["errors"].append(str(exc))
            report.update(inserted=0, enriched=0, unchanged=0)
    return {k: v for k, v in report.items() if k != "rows"}
