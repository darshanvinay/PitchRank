"""Read-only historical UCL views over the existing match/audit tables."""

from collections import Counter

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import ImportRun, Match, Team
from app.ingestion.ucl_history import AVAILABLE, SOURCE, expected_rounds

SOURCE_PAGE = "https://github.com/openfootball/champions-league"


def history_seasons(engine, *, public: bool = False):
    with Session(engine) as session:
        matches = session.scalars(
            select(Match).where(Match.league == "ucl", Match.ucl_detail.is_not(None))
        ).all()
        runs = session.scalars(
            select(ImportRun).where(ImportRun.source == SOURCE).order_by(ImportRun.imported_at)
        ).all()
        output = []
        for year in range(2005, 2026):
            season = f"{year}-{year + 1}"
            rows = [
                m
                for m in matches
                if m.season == season and m.ucl_detail and m.ucl_detail.get("source") == SOURCE
            ]
            counts = dict(Counter(m.ucl_detail["round"] for m in rows))
            latest = next((r for r in reversed(runs) if r.season == season), None)
            expected = expected_rounds(season)
            location = latest.location if latest else None
            public_url = location if location and location.startswith("https://") else None
            output.append(
                {
                    "season": season,
                    "source_available": season in AVAILABLE,
                    "imported_matches": len(rows),
                    "expected_matches": sum(expected.values()),
                    "complete": counts == expected,
                    "stage_counts": counts,
                    "status": "complete_main_draw"
                    if counts == expected
                    else ("not_imported" if season in AVAILABLE else "source_unavailable"),
                    "last_imported_at": latest.imported_at.isoformat() + "Z" if latest else None,
                    "source_url": public_url or SOURCE_PAGE,
                    "source_location": public_url if public else location,
                    "license": "CC0-1.0",
                    "reviewed_errata": sum(bool(m.ucl_detail.get("erratum")) for m in rows),
                    "scope": "main draw; qualifiers excluded",
                    "limitations": [
                        "Kickoff time zones are unavailable; chronology uses match dates.",
                        "Leg numbers are derived from chronological home/away pairs.",
                        "Group identifiers are unavailable in matchday-organized files.",
                    ],
                }
            )
        return {"seasons": list(reversed(output))}


def history_matches(engine, season=None, stage=None, team_id=None, *, public: bool = False):
    with Session(engine) as session:
        query = select(Match).where(Match.league == "ucl", Match.ucl_detail.is_not(None))
        if season is not None:
            query = query.where(Match.season == season)
        if team_id is not None:
            query = query.where((Match.home_team_id == team_id) | (Match.away_team_id == team_id))
        matches = session.scalars(query.order_by(Match.match_date, Match.id)).all()
        teams = {t.id: t for t in session.scalars(select(Team))}
        all_rows = [m for m in matches if m.ucl_detail and m.ucl_detail.get("source") == SOURCE]
        available_teams = sorted(
            {t for m in all_rows for t in (m.home_team_id, m.away_team_id)},
            key=lambda t: teams[t].display_name,
        )
        rows = []
        for match in all_rows:
            detail = match.ucl_detail
            if stage and detail["round"] != stage:
                continue
            source_url = detail.get("source_url")
            if public and not (source_url and source_url.startswith("https://")):
                source_url = SOURCE_PAGE
            rows.append(
                {
                    "match_id": match.id,
                    "competition": "UEFA Champions League",
                    "season": match.season,
                    "date": match.match_date.isoformat(),
                    "status": match.status,
                    "home_id": match.home_team_id,
                    "away_id": match.away_team_id,
                    "home": teams[match.home_team_id].display_name,
                    "away": teams[match.away_team_id].display_name,
                    "home_crest": teams[match.home_team_id].crest_url,
                    "away_crest": teams[match.away_team_id].crest_url,
                    "home_goals": match.home_goals,
                    "away_goals": match.away_goals,
                    "source_url": source_url,
                    **{
                        key: detail.get(key)
                        for key in (
                            "round",
                            "group",
                            "leg",
                            "tie_id",
                            "tie_format",
                            "leg_basis",
                            "extra_time_home",
                            "extra_time_away",
                            "penalties_home",
                            "penalties_away",
                            "source",
                            "source_id",
                            "source_line",
                            "revision",
                            "away_goals_rule",
                            "erratum",
                        )
                    },
                }
            )
        return {
            "season": season,
            "matches": rows,
            "teams": [{"id": t, "name": teams[t].display_name} for t in available_teams],
        }
