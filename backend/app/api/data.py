from datetime import timedelta

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.leagues import competition
from app.core.season import season_config
from app.db.models import Match, SeasonHistory, SeasonRating, SquadValue, Team
from app.services.season import fingerprint


class DataUnavailable(ValueError):
    pass


def league_data(
    engine: Engine, season: str, league: str = "epl"
) -> tuple[dict, list[dict], dict[int, list[dict]]]:
    info = competition(league)
    league_id = league
    with Session(engine) as session:
        session.execute(text("BEGIN"))
        matches = session.scalars(
            select(Match)
            .where(Match.season == season, Match.league == league, Match.status == "finished")
            .order_by(Match.match_date, Match.kickoff_at, Match.id)
        ).all()
        values = session.scalars(
            select(SquadValue).where(SquadValue.season == season, SquadValue.league == league)
        ).all()
        ratings = session.scalars(
            select(SeasonRating).where(SeasonRating.season == season, SeasonRating.league == league)
        ).all()
        if len(ratings) != info.club_count:
            raise DataUnavailable(
                "Current-season ratings are not ready. Run 'pitchrank refresh' first."
            )
        config = season_config()
        signature = fingerprint(matches, values, config)
        if any(r.input_hash != signature for r in ratings):
            raise DataUnavailable(
                "Results or squad values changed. Run 'pitchrank refresh' to recalculate."
            )
        teams = {t.id: t for t in session.scalars(select(Team).where(Team.league == league))}
        history = session.scalars(
            select(SeasonHistory)
            .where(
                SeasonHistory.match_id.in_(
                    select(Match.id).where(Match.season == season, Match.league == league)
                )
            )
            .order_by(SeasonHistory.sequence)
        ).all()
        if len(history) != len(matches) * 2:
            raise DataUnavailable(
                "Rating history is incomplete. Run 'pitchrank refresh' to rebuild it."
            )
        history_by_match = {(h.match_id, h.team_id): h for h in history}
        stats_rows = []
        results = []
        histories: dict[int, list[dict]] = {r.team_id: [] for r in ratings}
        start = min((m.match_date for m in matches), default=None)
        for r in ratings:
            histories[r.team_id].append(
                {
                    "date": str(start - timedelta(days=1)) if start else (f"{season[:4]}-08-01"),
                    "rating": r.initial_rating,
                    "change": 0,
                    "opponent": None,
                    "result": None,
                }
            )
        for match in matches:
            results.append(
                {
                    "match_id": match.id,
                    "date": str(match.match_date),
                    "home_id": match.home_team_id,
                    "away_id": match.away_team_id,
                    "home": teams[match.home_team_id].display_name,
                    "away": teams[match.away_team_id].display_name,
                    "home_goals": match.home_goals,
                    "away_goals": match.away_goals,
                    "home_change": history_by_match[(match.id, match.home_team_id)].rating_change,
                    "away_change": history_by_match[(match.id, match.away_team_id)].rating_change,
                }
            )
            for team, opponent, gf, ga in (
                (match.home_team_id, match.away_team_id, match.home_goals, match.away_goals),
                (match.away_team_id, match.home_team_id, match.away_goals, match.home_goals),
            ):
                outcome = "W" if gf > ga else ("L" if gf < ga else "D")
                stats_rows.append(
                    {
                        "team_id": team,
                        "played": 1,
                        "won": int(gf > ga),
                        "drawn": int(gf == ga),
                        "lost": int(gf < ga),
                        "goals_for": gf,
                        "goals_against": ga,
                    }
                )
                row = history_by_match[(match.id, team)]
                histories[team].append(
                    {
                        "date": str(match.match_date),
                        "rating": row.rating_after,
                        "change": row.rating_change,
                        "opponent": teams[opponent].display_name,
                        "result": outcome,
                    }
                )
        grouped = (
            pd.DataFrame(stats_rows).groupby("team_id").sum().to_dict("index") if stats_rows else {}
        )
        squad_lookup = {v.team_id: v for v in values}
        clubs = []
        for r in sorted(ratings, key=lambda r: (-r.rating, teams[r.team_id].display_name)):
            team = teams[r.team_id]
            v = squad_lookup.get(r.team_id)
            stats = grouped.get(
                r.team_id,
                dict.fromkeys(("played", "won", "drawn", "lost", "goals_for", "goals_against"), 0),
            )
            clubs.append(
                {
                    "id": team.id,
                    "name": team.display_name,
                    "crest_url": team.crest_url,
                    "rank": len(clubs) + 1,
                    "rating": r.rating,
                    "initial_rating": r.initial_rating,
                    "change": r.rating - r.initial_rating,
                    **{key: int(value) for key, value in stats.items()},
                    "goal_difference": int(stats["goals_for"] - stats["goals_against"]),
                    "squad_value": v.value_eur if v else None,
                    "valuation_date": str(v.as_of) if v else None,
                    "value_source": v.source_url if v else None,
                    "form": [h["result"] for h in histories[team.id][1:]][-5:],
                }
            )
        league = {
            "season": season,
            "results_through": str(max(m.match_date for m in matches)) if matches else None,
            "refreshed_at": max(r.calculated_at for r in ratings).isoformat() + "Z",
            "matches": len(matches),
            "squad_coverage": len(values),
            "squad_count": len(ratings),
            "source": info.source,
            "league_id": league_id,
            "name": info.name,
            "country": info.country,
            "valuation_note": info.valuation_note,
            "squad_log_scale": config.squad_log_scale,
            "squad_cap": config.squad_cap,
            "squad_reference_eur": config.squad_reference_eur,
            "clubs": clubs,
        }
        return league, list(reversed(results)), histories
