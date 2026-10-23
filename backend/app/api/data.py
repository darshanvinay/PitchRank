from datetime import timedelta

import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.core.leagues import LEAGUES, competition
from app.core.season import season_config
from app.db.models import Match, SeasonHistory, SeasonRating, SquadValue, Team
from app.services.season import fingerprint


class DataUnavailable(ValueError):
    pass


def league_data(engine: Engine, season: str, league: str = "epl"):
    info = competition(league) if league != "europe" else None
    config = season_config()
    weights = {
        "domestic": config.domestic_importance,
        "league": config.ucl_league_importance,
        "knockout": config.ucl_knockout_importance,
        "finals": config.ucl_finals_importance,
    }
    with Session(engine) as session:
        session.execute(text("BEGIN"))
        pool = session.scalars(
            select(Match)
            .where(
                Match.season >= config.history_start,
                Match.season <= season,
                Match.league.in_([*LEAGUES, "ucl"]),
                Match.status == "finished",
            )
            .order_by(Match.match_date, Match.kickoff_at, Match.id)
        ).all()
        values = session.scalars(select(SquadValue).where(SquadValue.season <= season)).all()
        ratings = session.scalars(select(SeasonRating).where(SeasonRating.season == season)).all()
        teams = {t.id: t for t in session.scalars(select(Team))}
        # Current-season domestic membership excludes relegated and UCL-only opponents.
        members = {key: set() for key in LEAGUES}
        for match in pool:
            if match.season == season and match.league in members:
                members[match.league].update((match.home_team_id, match.away_team_id))
        for value in values:
            if value.season == season and value.league in members:
                members[value.league].add(value.team_id)
        selected = set().union(*members.values()) if league == "europe" else members[league]
        if not selected or (info and len(selected) != info.club_count):
            raise DataUnavailable(
                "Current ratings are not ready. Run 'pitchrank refresh --league europe'."
            )
        if league == "europe" and any(len(members[k]) != v.club_count for k, v in LEAGUES.items()):
            raise DataUnavailable(
                "Load all five domestic leagues before viewing European rankings."
            )
        rating_map = {r.team_id: r for r in ratings}
        if not selected.issubset(rating_map):
            raise DataUnavailable(
                "Unified ratings are not ready. Run 'pitchrank refresh --league europe'."
            )
        signature = fingerprint(pool, values, config)
        if any(r.input_hash != signature for r in ratings):
            raise DataUnavailable(
                "Results or squad values changed. "
                "Run 'pitchrank refresh --league europe' to recalculate."
            )
        current = [m for m in pool if m.season == season]
        relevant = [m for m in current if m.home_team_id in selected or m.away_team_id in selected]
        history = session.scalars(
            select(SeasonHistory)
            .where(SeasonHistory.match_id.in_([m.id for m in current]))
            .order_by(SeasonHistory.sequence)
        ).all()
        if len(history) != 2 * len(current):
            raise DataUnavailable("Rating history is incomplete. Refresh to rebuild it.")
        history_by_match = {(h.match_id, h.team_id): h for h in history}
        histories = {team: [] for team in selected}
        start = min((m.match_date for m in current), default=None)
        for team in selected:
            histories[team].append(
                {
                    "date": str(start - timedelta(days=1)) if start else f"{season[:4]}-08-01",
                    "rating": rating_map[team].initial_rating,
                    "change": 0,
                    "opponent": None,
                    "result": None,
                }
            )
        stats_rows, results = [], []
        forms = {team: [] for team in selected}
        for match in relevant:
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
                    "competition": "Champions League"
                    if match.league == "ucl"
                    else LEAGUES[match.league].name,
                    "importance": weights[match.stage],
                }
            )
            for team, opponent, gf, ga in [
                (match.home_team_id, match.away_team_id, match.home_goals, match.away_goals),
                (match.away_team_id, match.home_team_id, match.away_goals, match.home_goals),
            ]:
                if team not in selected:
                    continue
                outcome = "W" if gf > ga else ("L" if gf < ga else "D")
                forms[team].append(outcome)
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
                if match.league != "ucl":
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
        grouped = (
            pd.DataFrame(stats_rows).groupby("team_id").sum().to_dict("index") if stats_rows else {}
        )
        squad_lookup = {v.team_id: v for v in values if v.season == season}
        club_league = {team: key for key, group in members.items() for team in group}
        for result in results:
            result["home_league"] = club_league.get(result["home_id"])
            result["away_league"] = club_league.get(result["away_id"])
        clubs = []
        for team_id in sorted(
            selected, key=lambda t: (-rating_map[t].rating, teams[t].display_name)
        ):
            team, rating = teams[team_id], rating_map[team_id]
            value = squad_lookup.get(team_id)
            stats = grouped.get(
                team_id,
                dict.fromkeys(("played", "won", "drawn", "lost", "goals_for", "goals_against"), 0),
            )
            clubs.append(
                {
                    "id": team_id,
                    "name": team.display_name,
                    "crest_url": team.crest_url,
                    "league_id": club_league[team_id],
                    "league_name": LEAGUES[club_league[team_id]].name,
                    "rank": len(clubs) + 1,
                    "rating": rating.rating,
                    "initial_rating": rating.initial_rating,
                    "change": rating.rating - rating.initial_rating,
                    "last_change": histories[team_id][-1]["change"],
                    **{key: int(number) for key, number in stats.items()},
                    "goal_difference": int(stats["goals_for"] - stats["goals_against"]),
                    "squad_value": value.value_eur if value else None,
                    "valuation_date": str(value.as_of) if value else None,
                    "value_source": value.source_url if value else None,
                    "form": forms[team_id][-5:],
                }
            )
        if league == "europe":
            clubs = clubs[:25]
        domestic = [m for m in current if m.league == league] if info else current
        data = {
            "league_id": league,
            "name": info.name if info else "European Rankings",
            "country": info.country if info else "Europe",
            "season": season,
            "valuation_note": info.valuation_note
            if info
            else "One initial squad-value prior per club; ratings carry across seasons.",
            "source": info.source
            if info
            else "https://fixturedownload.com/results/champions-league-2026",
            "results_through": str(max(m.match_date for m in current)) if current else None,
            "refreshed_at": max(r.calculated_at for r in ratings).isoformat() + "Z",
            "matches": len(domestic),
            "squad_coverage": sum(t in squad_lookup for t in selected),
            "squad_count": len(selected),
            "squad_log_scale": config.squad_log_scale,
            "squad_cap": config.squad_cap,
            "squad_reference_eur": config.squad_reference_eur,
            "pool_matches": len(pool),
            "pool_teams": len({t for m in pool for t in (m.home_team_id, m.away_team_id)}),
            "ucl_matches": sum(m.league == "ucl" for m in pool),
            "history_start": config.history_start,
            "importance_weights": weights,
            "clubs": clubs,
        }
        return data, list(reversed(results)), histories
