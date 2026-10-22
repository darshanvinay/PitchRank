"""Chronological replay independent of persistence and HTTP concerns."""

from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from itertools import groupby
from statistics import mean

from app.core.elo import EloConfig
from app.elo.engine import RatingUpdate, update_ratings


@dataclass(frozen=True)
class PlayedMatch:
    id: int
    season: str
    match_date: date
    kickoff_at: datetime | None
    home_team_id: int
    away_team_id: int
    home_goals: int
    away_goals: int


@dataclass(frozen=True)
class ReplayEntry:
    match: PlayedMatch
    sequence: int
    update: RatingUpdate


@dataclass(frozen=True)
class ReplayResult:
    entries: list[ReplayEntry]
    ratings: dict[int, float]
    season: str | None
    active_teams: set[int]


def replay(
    matches: list[PlayedMatch],
    config: EloConfig,
    before_match: Callable[[PlayedMatch, float, float], None] | None = None,
) -> ReplayResult:
    if len({match.id for match in matches}) != len(matches):
        raise ValueError("Replay contains duplicate match IDs")
    ordered = sorted(matches, key=lambda m: (m.match_date, m.home_team_id, m.away_team_id))
    members: dict[str, set[int]] = defaultdict(set)
    for match in ordered:
        if match.home_team_id == match.away_team_id:
            raise ValueError("A club cannot play itself")
        members[match.season].update((match.home_team_id, match.away_team_id))
    ratings: dict[int, float] = {}
    active: set[int] = set()
    season = None
    seen_seasons = set()
    entries = []
    for (_, day_season), day_iter in groupby(ordered, key=lambda m: (m.match_date, m.season)):
        day_matches = list(day_iter)
        if day_season != season:
            if day_season in seen_seasons or (season and day_season < season):
                raise ValueError("Season dates overlap or run out of order; review the data")
            new_active = members[day_season]
            if season is None:
                ratings = dict.fromkeys(new_active, config.initial_rating)
            else:
                gap = int(day_season[:4]) - int(season[:4])
                relegated = active - new_active if gap == 1 else set()
                promotion = (
                    mean(ratings[t] for t in relegated) if relegated else (config.promoted_default)
                )
                # Regress retained clubs once for every elapsed off-season. Promotion uses
                # the departing clubs' final ratings BEFORE regression, and ignores stale
                # ratings of returning clubs.
                retention = (1 - config.season_regression) ** gap
                ratings = {
                    team: config.initial_rating
                    + (ratings[team] - config.initial_rating) * retention
                    if team in active
                    else promotion
                    for team in new_active
                }
            season, active = day_season, new_active
            seen_seasons.add(season)
        # If any kickoff is unknown, no result on this day informs another match that day.
        if any(m.kickoff_at is None for m in day_matches):
            groups = [day_matches]
        else:
            by_time = sorted(
                day_matches, key=lambda m: (m.kickoff_at, m.home_team_id, m.away_team_id)
            )
            groups = [list(group) for _, group in groupby(by_time, key=lambda m: m.kickoff_at)]
        for group in groups:
            teams = [team for m in group for team in (m.home_team_id, m.away_team_id)]
            if len(teams) != len(set(teams)):
                raise ValueError(
                    "A club appears twice in an ambiguous kickoff group; review the data"
                )
            before = ratings.copy()
            # Predict the entire ambiguous group before applying any of its results.
            if before_match is not None:
                for match in group:
                    before_match(match, before[match.home_team_id], before[match.away_team_id])
            for match in group:
                result = update_ratings(
                    before[match.home_team_id],
                    before[match.away_team_id],
                    match.home_goals,
                    match.away_goals,
                    config,
                )
                entries.append(ReplayEntry(match, len(entries) + 1, result))
                ratings[match.home_team_id] = result.home_after
                ratings[match.away_team_id] = result.away_after
    return ReplayResult(entries, ratings, season, active)
