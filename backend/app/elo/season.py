"""Current-season Elo, reusing the existing match mathematics without research model versions."""

import math
from collections import defaultdict
from itertools import groupby

import numpy as np

from app.core.season import SeasonConfig
from app.elo.engine import update_ratings
from app.elo.replay import PlayedMatch, ReplayEntry, ReplayResult


def starting_rating(value: float | None, reference: float | None, config: SeasonConfig) -> float:
    if value is None or reference is None:
        return config.elo.initial_rating
    if not all(math.isfinite(v) and v > 0 for v in (value, reference)):
        raise ValueError("Squad values must be positive and finite")
    adjustment = np.clip(
        config.squad_log_scale * np.log(value / reference), -config.squad_cap, config.squad_cap
    )
    return float(config.elo.initial_rating + adjustment)


def replay_season(
    matches: list[PlayedMatch], values: dict[int, float | None], config: SeasonConfig
) -> tuple[ReplayResult, dict[int, float]]:
    if len({m.id for m in matches}) != len(matches):
        raise ValueError("Duplicate match IDs")
    seasons = {m.season for m in matches}
    if len(seasons) > 1:
        raise ValueError("Current-season replay accepts one season only")
    initial = {
        team: starting_rating(value, config.squad_reference_eur, config)
        for team, value in values.items()
    }
    ratings = initial.copy()
    entries = []
    ordered = sorted(matches, key=lambda m: (m.match_date, m.home_team_id, m.away_team_id))
    for _, group in groupby(ordered, key=lambda m: m.match_date):
        day = list(group)
        if any(m.kickoff_at is None for m in day):
            batches = [day]
        else:
            day.sort(key=lambda m: (m.kickoff_at, m.home_team_id, m.away_team_id))
            batches = [list(items) for _, items in groupby(day, key=lambda m: m.kickoff_at)]
        for batch in batches:
            seen = set()
            pending = defaultdict(float)
            for match in batch:
                home, away = match.home_team_id, match.away_team_id
                if home == away or home in seen or away in seen:
                    raise ValueError("Club repeated in a kickoff group")
                seen.update((home, away))
                result = update_ratings(
                    ratings[home], ratings[away], match.home_goals, match.away_goals, config.elo
                )
                entries.append(ReplayEntry(match, len(entries) + 1, result))
                pending[home] += result.home_change
                pending[away] += result.away_change
            for team, delta in pending.items():
                ratings[team] += delta
    return ReplayResult(entries, ratings, next(iter(seasons), None), set(values)), initial
