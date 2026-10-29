"""Validate full historical domestic snapshots, then reuse the audited CSV importer."""

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from app.core.leagues import LEAGUES, competition
from app.db.session import ROOT
from app.ingestion.historical import download_season, import_csv, parse_csv, season_start


def import_domestic_history(
    engine, first="2010-2011", last="2025-2026", league=None, directory=None
):
    start, end = season_start(first), season_start(last)
    if end < start:
        raise ValueError("End season precedes start")
    registry = json.loads((ROOT / "data/domestic-history.json").read_text())
    reports = []
    for key in [league] if league else LEAGUES:
        info = competition(key)
        for year in range(start, end + 1):
            season = f"{year}-{year + 1}"
            report = {"league": key, "season": season, "errors": [], "unmatched_teams": []}
            try:
                expected = registry["seasons"].get(key, {}).get(season)
                if expected is None:
                    raise ValueError("Season has no reviewed full-season coverage manifest")
                path = (
                    Path(directory) / f"{info.division}-{season}.csv"
                    if directory
                    else download_season(season, ROOT / "data/raw/domestic-history", key)
                )
                frame = parse_csv(path.read_bytes(), season)
                if not frame.FTR.isin(["H", "D", "A"]).all():
                    raise ValueError("Unfinished or malformed full-time result in historical feed")
                if (
                    "Status" in frame
                    and frame.Status.str.lower()
                    .isin(["scheduled", "postponed", "cancelled", "abandoned", "incomplete"])
                    .any()
                ):
                    raise ValueError("Unplayed status in historical results feed")
                names = set(frame.HomeTeam) | set(frame.AwayTeam)
                report["unmatched_teams"] = sorted(names - set(registry["clubs"][key]))
                if report["unmatched_teams"]:
                    raise ValueError("Unresolved explicit club aliases")
                if names != set(expected["clubs"]):
                    raise ValueError("Clubs do not match the reviewed season roster")
                pairs = list(zip(frame.HomeTeam, frame.AwayTeam, strict=True))
                if len(set(pairs)) != len(pairs):
                    raise ValueError("Duplicate domestic home/away fixture in full-season feed")
                if len(frame) != expected["expected_matches"]:
                    raise ValueError(
                        f"Expected {expected['expected_matches']} completed matches; "
                        f"found {len(frame)}"
                    )
                if not expected["curtailed"]:
                    played = Counter([*frame.HomeTeam, *frame.AwayTeam])
                    if any(n != 2 * (len(names) - 1) for n in played.values()):
                        raise ValueError("Incomplete per-club schedule")
                result = import_csv(
                    engine,
                    path,
                    season,
                    league=key,
                    complete_snapshot=True,
                    location=str(path.resolve())
                    if directory
                    else (
                        "https://www.football-data.co.uk/mmz4281/"
                        f"{str(year)[-2:]}{str(year + 1)[-2:]}/{info.division}.csv"
                    ),
                )
                if result.skipped:
                    raise ValueError("Unexpected unplayed rows in historical full-season feed")
                report.update(
                    **asdict(result),
                    matches=len(frame),
                    expected=expected["expected_matches"],
                    status="curtailed_season" if expected["curtailed"] else "complete",
                )
            except (ValueError, OSError) as exc:
                report["errors"].append(str(exc))
                report["status"] = "failed"
            reports.append(report)
    return {"seasons": reports}
