"""Cutoff-frozen UCL R16 backtest; exact score enumeration, never tournament simulation."""

import math
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date

import pandas as pd
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.metrics import scores
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, Team
from app.ingestion.historical import season_start
from app.predictions.model import PredictionConfig, probabilities
from app.services.historical import historical_elo_snapshot


@dataclass(frozen=True)
class TieFixture:
    """Only the known pairing/nominal home order, never observed scores or advancement."""

    a: int  # First-leg home club; second-leg away club.
    b: int
    neutral_first: bool = False
    neutral_second: bool = False


def regulation_winner(first, second, away_goals):
    """Return A/B or None after 180 minutes. Scores are (home, away) in each leg."""
    h1, a1 = first
    h2, a2 = second
    aggregate = (h1 + a2, a1 + h2)
    if aggregate[0] != aggregate[1]:
        return "A" if aggregate[0] > aggregate[1] else "B"
    if away_goals and a2 != a1:
        return "A" if a2 > a1 else "B"
    return None


def extra_time_winner(home, away, away_goals):
    # Extra time is at B's nominal home. Under old rules a scoring ET draw favors away A.
    if away != home:
        return "A" if away > home else "B"
    if away_goals and away > 0:
        return "A"
    return None


def actual_winner(first: Match, second: Match, away_goals: bool):
    winner = regulation_winner(
        (first.home_goals, first.away_goals), (second.home_goals, second.away_goals), away_goals
    )
    detail = second.ucl_detail or {}
    et = (detail.get("extra_time_home"), detail.get("extra_time_away"))
    pens = (detail.get("penalties_home"), detail.get("penalties_away"))
    if winner:
        if any(v is not None for v in (*et, *pens)):
            raise ValueError("Extra time/penalties recorded for an already resolved tie")
        return winner
    if any(v is None for v in et):
        raise ValueError("Unresolved tie: missing extra-time score")
    h, a = et[0] - second.home_goals, et[1] - second.away_goals
    if min(h, a) < 0:
        raise ValueError("Extra-time score decreased")
    winner = extra_time_winner(h, a, away_goals)
    if winner:
        if any(v is not None for v in pens):
            raise ValueError("Unexpected penalties on resolved tie")
        return winner
    if any(v is None for v in pens) or pens[0] == pens[1]:
        raise ValueError("Unresolved tie: missing/invalid shootout score")
    return "A" if pens[1] > pens[0] else "B"


def conditional_scores(matches):
    """Empirical P(home goals,away goals | H/D/A), fitted ONLY to pre-cutoff results."""
    counts = [Counter(), Counter(), Counter()]
    for m in matches:
        outcome = 0 if m.home_goals > m.away_goals else (1 if m.home_goals == m.away_goals else 2)
        counts[outcome][(m.home_goals, m.away_goals)] += 1
    if any(not c for c in counts):
        raise ValueError("Pre-cutoff data must contain H, D and A results")
    return [{pair: n / sum(c.values()) for pair, n in c.items()} for c in counts]


def score_distribution(home, away, conditionals, config, neutral=False):
    if neutral:
        config = config.model_copy(
            update={"elo": config.elo.model_copy(update={"home_advantage": 0})}
        )
        # A neutral venue must not retain the fitted home/away score-shape asymmetry.
        winning = defaultdict(float)
        for pair, mass in conditionals[0].items():
            winning[pair] += mass / 2
        for (h, a), mass in conditionals[2].items():
            winning[a, h] += mass / 2
        conditionals = [
            dict(winning),
            conditionals[1],
            {(a, h): p for (h, a), p in winning.items()},
        ]
    outcome = probabilities(home, away, config)
    pmf = {
        pair: float(outcome[i]) * weight
        for i, rows in enumerate(conditionals)
        for pair, weight in rows.items()
    }
    if not math.isclose(sum(pmf.values()), 1, abs_tol=1e-10):
        raise ValueError("Score mass is not one")
    return pmf


def extra_time_distribution(pmf):
    """Independent 1/3 binomial thinning of the 90-minute goal counts (fixed assumption)."""
    output = defaultdict(float)
    for (h, a), p in pmf.items():
        for i in range(h + 1):
            for j in range(a + 1):
                output[i, j] += (
                    p
                    * math.comb(h, i)
                    * (1 / 3) ** i
                    * (2 / 3) ** (h - i)
                    * math.comb(a, j)
                    * (1 / 3) ** j
                    * (2 / 3) ** (a - j)
                )
    return dict(output)


def advancement_probability(fixture, ratings, conditionals, config, away_goals):
    first = score_distribution(
        ratings[fixture.a], ratings[fixture.b], conditionals, config, fixture.neutral_first
    )
    second = score_distribution(
        ratings[fixture.b], ratings[fixture.a], conditionals, config, fixture.neutral_second
    )
    et_a = sum(
        p
        * (
            1
            if extra_time_winner(h, a, away_goals) == "A"
            else 0
            if extra_time_winner(h, a, away_goals) == "B"
            else 0.5
        )
        for (h, a), p in extra_time_distribution(second).items()
    )
    total = 0.0
    for pair1, p1 in first.items():
        for pair2, p2 in second.items():
            winner = regulation_winner(pair1, pair2, away_goals)
            total += p1 * p2 * (1 if winner == "A" else 0 if winner == "B" else et_a)
    if not 0 <= total <= 1:
        raise ValueError("Invalid advancement probability")
    return total


def advancement_metrics(records):
    if not records:
        raise ValueError("No evaluated knockout ties")
    frame = pd.DataFrame(
        [
            {
                "p_home": r["p_a"],
                "p_draw": 0.0,
                "p_away": 1 - r["p_a"],
                "actual": "H" if r["actual_winner"] == r["team_a_id"] else "A",
            }
            for r in records
        ]
    )
    measured = scores(frame)
    # Existing multiclass sum is twice the conventional binary advancement Brier score.
    return {
        "ties": len(records),
        "correct": sum(r["predicted_winner"] == r["actual_winner"] for r in records),
        "accuracy": measured["accuracy"],
        "brier_score": measured["brier_score"] / 2,
        "log_loss": measured["log_loss"],
    }


def backtest_round_of_16(engine, season="2020-2021", config=None, draw_strength=0.7):
    year = season_start(season)
    config = config or SeasonConfig()
    probability_config = PredictionConfig(elo=config.elo, draw_strength=draw_strength)
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")  # One read-only database snapshot, including labels.
        with Session(connection) as session:
            matches = session.scalars(
                select(Match).where(
                    Match.league == "ucl", Match.season == season, Match.status == "finished"
                )
            ).all()
            matches = [
                m for m in matches if m.ucl_detail and m.ucl_detail.get("round") == "round_of_16"
            ]
            groups = defaultdict(list)
            for m in matches:
                groups[m.ucl_detail.get("tie_id")].append(m)
            if len(matches) != 16 or len(groups) != 8 or None in groups:
                raise ValueError(f"{season}: require 16 matches and 8 reviewed Round-of-16 ties")
            ties = []
            for key, legs in groups.items():
                legs.sort(key=lambda m: m.match_date)
                first, second = legs if len(legs) == 2 else (None, None)
                if (
                    first is None
                    or first.home_team_id != second.away_team_id
                    or first.away_team_id != second.home_team_id
                    or first.match_date >= second.match_date
                    or first.ucl_detail.get("leg") != 1
                    or second.ucl_detail.get("leg") != 2
                ):
                    raise ValueError(f"{season}: invalid two-leg tie {key}")
                ties.append((key, first, second))
            if len({t for _, m, _ in ties for t in (m.home_team_id, m.away_team_id)}) != 16:
                raise ValueError("A club appears in multiple R16 ties")
            cutoff = min(m.match_date for _, m, _ in ties)
            names = {t.id: t.display_name for t in session.scalars(select(Team))}
            calibration = session.scalars(
                select(Match).where(
                    Match.status == "finished",
                    Match.league.in_([*LEAGUES, "ucl"]),
                    Match.match_date >= date(2010, 7, 1),
                    Match.match_date < cutoff,
                )
            ).all()
        snapshot = historical_elo_snapshot(connection, cutoff, config)
        ratings = snapshot["ratings"]
        conditionals = conditional_scores(calibration)
        away_goals = year <= 2020
        forecasts = []
        # Freeze EVERY forecast before reading any observed score for evaluation.
        for key, first, second in sorted(ties):
            fixture = TieFixture(
                first.home_team_id, first.away_team_id, first.neutral, second.neutral
            )
            if fixture.a not in ratings or fixture.b not in ratings:
                raise ValueError("Participating club has no pre-cutoff match history")
            p_a = advancement_probability(
                fixture, ratings, conditionals, probability_config, away_goals
            )
            forecasts.append(
                {
                    "tie_id": key,
                    "team_a_id": fixture.a,
                    "team_b_id": fixture.b,
                    "team_a": names[fixture.a],
                    "team_b": names[fixture.b],
                    "elo_a": ratings[fixture.a],
                    "elo_b": ratings[fixture.b],
                    "first_leg_home_id": fixture.a,
                    "second_leg_home_id": fixture.b,
                    "neutral_first": fixture.neutral_first,
                    "neutral_second": fixture.neutral_second,
                    "p_a": p_a,
                    "p_b": 1 - p_a,
                    "predicted_winner": fixture.a if p_a >= 0.5 else fixture.b,
                }
            )
        labels = {key: actual_winner(first, second, away_goals) for key, first, second in ties}
        by_key = {key: first for key, first, _ in ties}
        for r in forecasts:
            first = by_key[r["tie_id"]]
            r["actual_winner"] = (
                first.home_team_id if labels[r["tie_id"]] == "A" else first.away_team_id
            )
        return {
            "backtest_revision": "r16-davidson-empirical-v1",
            "season": season,
            "round": "round_of_16",
            "cutoff": str(cutoff),
            "cutoff_exclusive": True,
            "away_goals_rule": away_goals,
            "snapshot_matches": snapshot["matches"],
            "latest_input_match": str(snapshot["latest_match"]),
            "input_hash": snapshot["input_hash"],
            "config_hash": snapshot["config_hash"],
            "parameters": {
                "elo": config.model_dump(),
                "probability": probability_config.model_dump(),
                "extra_time_minutes_ratio": 1 / 3,
                "penalty_probability": 0.5,
            },
            "score_calibration_matches": len(calibration),
            "metrics": advancement_metrics(forecasts),
            "predictions": forecasts,
        }


def backtest_seasons(engine, seasons, config=None, draw_strength=0.7):
    if len(seasons) != len(set(seasons)):
        raise ValueError("Duplicate evaluation seasons")
    results = [backtest_round_of_16(engine, s, config, draw_strength) for s in seasons]
    return {
        "seasons": results,
        "overall": advancement_metrics([r for s in results for r in s["predictions"]]),
        "scope": "Round of 16 only; frozen pre-round ratings; no tournament simulator",
    }
