"""Frozen-Elo fixed-bracket forecasts. Draw scenarios are explicit, never assumed known."""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import (
    TieFixture,
    actual_winner,
    advancement_probability,
    conditional_scores,
    extra_time_distribution,
    score_distribution,
)
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, Team
from app.db.session import get_engine
from app.predictions.model import PredictionConfig
from app.services.historical import historical_elo_snapshot

ROUNDS = ("round_of_16", "quarterfinal", "semifinal", "final")


@dataclass(frozen=True)
class Node:
    id: str
    round: str
    left: "Node | int"
    right: "Node | int"
    neutral_first: bool = False
    neutral_second: bool = False


def leaves(node):
    return [node] if isinstance(node, int) else leaves(node.left) + leaves(node.right)


def validate_tree(root):
    counts = defaultdict(int)

    def visit(node, depth):
        if isinstance(node, int):
            if depth != 4:
                raise ValueError("All clubs must enter at Round of 16")
            return
        if depth >= 4 or node.round != ROUNDS[3 - depth]:
            raise ValueError("Invalid round progression")
        counts[node.id] += 1
        visit(node.left, depth + 1)
        visit(node.right, depth + 1)

    visit(root, 0)
    clubs = leaves(root)
    if len(clubs) != 16 or len(set(clubs)) != 16 or len(counts) != 15 or max(counts.values()) != 1:
        raise ValueError("Require 16 distinct clubs and 15 distinct ties")


def solve_bracket(root, probability, method="global"):
    """Maximum joint-probability complete outcome tree, NOT marginal champion probability.

    State per node: for each possible champion, the best subtree log probability
    and its traceback. Independent child subtrees combine with the matchup probability.
    """
    validate_tree(root)
    if method not in ("greedy", "global"):
        raise ValueError("Unknown bracket method")

    def visit(node):
        if isinstance(node, int):
            return {node: (0.0, [])}
        left, right = visit(node.left), visit(node.right)
        states = {}
        for a, (la, pa) in left.items():
            for b, (lb, pb) in right.items():
                p = probability(node, a, b)
                if not math.isfinite(p) or not 0 < p < 1:
                    raise ValueError("Matchup probabilities must be strictly between zero and one")
                winners = (a if p >= 0.5 else b,) if method == "greedy" else (a, b)
                for winner in winners:
                    selected_p = p if winner == a else 1 - p
                    log_p = la + lb + math.log(selected_p)
                    row = {
                        "id": node.id,
                        "round": node.round,
                        "team_a_id": a,
                        "team_b_id": b,
                        "p_a": p,
                        "p_b": 1 - p,
                        "winner_id": winner,
                        "selected_probability": selected_p,
                        "single_match": node.round == "final",
                        "neutral_first": node.neutral_first,
                        "neutral_second": node.neutral_second,
                    }
                    if winner not in states or log_p > states[winner][0]:
                        states[winner] = log_p, pa + pb + [row]
        return states

    states = visit(root)
    champion, (log_p, matches) = max(states.items(), key=lambda item: item[1][0])
    # Preorder traversal makes ties visually adjacent within each round.
    order = {}

    def index(node):
        if isinstance(node, Node):
            order[node.id] = len(order)
            index(node.left)
            index(node.right)

    index(root)
    matches.sort(key=lambda r: (ROUNDS.index(r["round"]), order[r["id"]]))
    return {
        "method": method,
        "champion_id": champion,
        "log_joint_probability": log_p,
        "joint_probability": math.exp(log_p),
        "matches": matches,
    }


def final_probability(a, b, ratings, conditionals, config):
    """Neutral single-match final, with ET and 50/50 penalties after a regulation draw."""
    pmf = score_distribution(ratings[a], ratings[b], conditionals, config, neutral=True)
    et_win = sum(
        p * (1 if h > aw else 0 if h < aw else 0.5)
        for (h, aw), p in extra_time_distribution(pmf).items()
    )
    return sum(p * (1 if h > aw else 0 if h < aw else et_win) for (h, aw), p in pmf.items())


def grouped_ties(matches, round_name, expected):
    groups = defaultdict(list)
    for m in matches:
        if (m.ucl_detail or {}).get("round") == round_name:
            groups[m.ucl_detail.get("tie_id")].append(m)
    if len(groups) != expected or None in groups:
        raise ValueError(f"Require {expected} reviewed {round_name} ties")
    output = []
    for key, legs in sorted(groups.items()):
        legs.sort(key=lambda m: m.match_date)
        if round_name == "final":
            if len(legs) != 1:
                raise ValueError("Final must be a single match")
        elif (
            len(legs) != 2
            or legs[0].home_team_id != legs[1].away_team_id
            or legs[0].away_team_id != legs[1].home_team_id
            or legs[0].match_date >= legs[1].match_date
            or [m.ucl_detail.get("leg") for m in legs] != [1, 2]
        ):
            raise ValueError("Invalid two-leg fixture")
        output.append((key, legs))
    ids = [t for _, legs in output for t in (legs[0].home_team_id, legs[0].away_team_id)]
    if len(set(ids)) != 2 * expected:
        raise ValueError("Club appears in multiple round ties")
    return output


def build_tree(rounds, scenario):
    nodes = [
        Node(
            key,
            "round_of_16",
            legs[0].home_team_id,
            legs[0].away_team_id,
            legs[0].neutral,
            legs[1].neutral,
        )
        for key, legs in rounds["round_of_16"]
    ]
    if scenario == "r16_order":
        for round_name in ROUNDS[1:]:
            nodes = [
                Node(
                    f"scenario-{round_name}-{i // 2}",
                    round_name,
                    nodes[i],
                    nodes[i + 1],
                    round_name == "final",
                )
                for i in range(0, len(nodes), 2)
            ]
    elif scenario == "observed_draw":
        # Fixture IDs/participants specify a conditional scenario. Scores are NOT read here.
        for round_name in ROUNDS[1:]:
            next_nodes, used = [], set()
            for key, legs in rounds[round_name]:
                first = legs[0]
                left = [n for n in nodes if first.home_team_id in leaves(n)]
                right = [n for n in nodes if first.away_team_id in leaves(n)]
                if len(left) != 1 or len(right) != 1 or left[0] == right[0]:
                    raise ValueError("Later fixture does not link distinct prior bracket slots")
                if left[0].id in used or right[0].id in used:
                    raise ValueError("Prior bracket slot used twice")
                used.update((left[0].id, right[0].id))
                next_nodes.append(
                    Node(
                        key,
                        round_name,
                        left[0],
                        right[0],
                        True if round_name == "final" else first.neutral,
                        legs[1].neutral if len(legs) == 2 else False,
                    )
                )
            if len(used) != len(nodes):
                raise ValueError("Unconnected bracket slot")
            nodes = next_nodes
    else:
        raise ValueError("Unknown bracket scenario")
    validate_tree(nodes[0])
    return nodes[0]


def forecast_tournament(engine, season="2020-2021", scenario="r16_order", evaluate=False):
    if season not in [f"{y}-{y + 1}" for y in range(2020, 2026)]:
        raise ValueError("Full historical brackets support 2020/21–2025/26")
    if evaluate and scenario != "observed_draw":
        raise ValueError(
            "Historical bracket scoring requires the explicitly conditional observed draw"
        )
    config = SeasonConfig()
    with engine.connect() as connection:
        connection.exec_driver_sql("BEGIN")
        with Session(connection) as session:
            matches = session.scalars(
                select(Match).where(
                    Match.league == "ucl", Match.season == season, Match.status == "finished"
                )
            ).all()
            rounds = {"round_of_16": grouped_ties(matches, "round_of_16", 8)}
            if scenario == "observed_draw":
                rounds.update(
                    {
                        r: grouped_ties(matches, r, count)
                        for r, count in zip(ROUNDS[1:], (4, 2, 1), strict=True)
                    }
                )
            cutoff = min(legs[0].match_date for _, legs in rounds["round_of_16"])
            clubs = {
                t.id: {"id": t.id, "name": t.display_name, "crest": t.crest_url}
                for t in session.scalars(select(Team))
            }
            calibration = session.scalars(
                select(Match).where(
                    Match.league.in_([*LEAGUES, "ucl"]),
                    Match.status == "finished",
                    Match.match_date >= date(2010, 7, 1),
                    Match.match_date < cutoff,
                )
            ).all()
        snapshot = historical_elo_snapshot(connection, cutoff, config)
        root = build_tree(rounds, scenario)
        ratings = snapshot["ratings"]
        if any(t not in ratings for t in leaves(root)):
            raise ValueError("A club has no pre-cutoff history")
        conditionals = conditional_scores(calibration)
        probabilities_config = PredictionConfig(elo=config.elo)
        away_goals = int(season[:4]) <= 2020

        @lru_cache(maxsize=None)
        def probability(node, a, b):
            if node.round == "final":
                return final_probability(a, b, ratings, conditionals, probabilities_config)
            return advancement_probability(
                TieFixture(a, b, node.neutral_first, node.neutral_second),
                ratings,
                conditionals,
                probabilities_config,
                away_goals,
            )

        forecasts = {
            method: solve_bracket(root, probability, method) for method in ("greedy", "global")
        }
        scenario_tree = asdict(root)
        output = {
            "season": season,
            "cutoff": str(cutoff),
            "cutoff_exclusive": True,
            "ratings_frozen": True,
            "model": "A",
            "scenario": scenario,
            "conditional": True,
            "unconditional_historical_forecast": False,
            "scenario_tree": scenario_tree,
            "scenario_hash": hashlib.sha256(
                json.dumps(scenario_tree, sort_keys=True).encode()
            ).hexdigest(),
            "scenario_description": (
                "Fixed scenario: sorted R16 tie IDs, adjacent winners meet; left slot hosts first. "
                "Later draw and venue outcomes are not used; "
                "later two-leg venues assumed non-neutral."
                if scenario == "r16_order"
                else "Retrospective conditional scenario: recorded later-round pairings, "
                "home order and "
                "venue flags supplied. These were not established as known at the cutoff. "
                "Later participants identify bracket slots; they are not model-predicted entrants."
            ),
            "rules": {
                "away_goals": away_goals,
                "final": "single neutral match",
                "penalty_probability": 0.5,
                "extra_time_minutes_ratio": 1 / 3,
            },
            "input_hash": snapshot["input_hash"],
            "config_hash": snapshot["config_hash"],
            "latest_input_match": str(snapshot["latest_match"]),
            "snapshot_matches": snapshot["matches"],
            "clubs": [{**clubs[t], "elo": ratings[t]} for t in sorted(leaves(root))],
            "forecasts": forecasts,
        }
        if evaluate:
            output["evaluation"] = evaluate_forecasts(
                root, rounds, forecasts, probability, away_goals
            )
        return output


def evaluate_forecasts(root, rounds, forecasts, probability, away_goals):
    """Labels accessed only AFTER all forecasts, including DP alternatives, have been frozen."""
    nodes = {}

    def visit(node):
        if isinstance(node, Node):
            nodes[node.id] = node
            visit(node.left)
            visit(node.right)

    visit(root)
    labels, actual_participants = {}, []
    for round_name in ROUNDS:
        for key, legs in rounds[round_name]:
            first = legs[0]
            a, b = first.home_team_id, first.away_team_id
            if round_name == "final":
                result = actual_winner(SimpleNamespace(home_goals=0, away_goals=0), first, False)
                winner = a if result == "B" else b
            else:
                winner = a if actual_winner(first, legs[1], away_goals) == "A" else b
            labels[key] = winner
            p = probability(nodes[key], a, b)
            actual_participants.append(
                {
                    "id": key,
                    "round": round_name,
                    "winner_id": a if p >= 0.5 else b,
                    "actual_winner_id": winner,
                    "team_a_id": a,
                    "team_b_id": b,
                    "p_a": p,
                }
            )

    def metrics(rows):
        stages = {
            r: {
                "correct": sum(m["winner_id"] == labels[m["id"]] for m in rows if m["round"] == r),
                "total": sum(m["round"] == r for m in rows),
            }
            for r in ROUNDS
        }
        correct = sum(v["correct"] for v in stages.values())
        return {
            "rounds": stages,
            "correct_finalists": stages["semifinal"]["correct"],
            "finalists_total": 2,
            "champion_correct": bool(stages["final"]["correct"]),
            "correct": correct,
            "total": 15,
            "accuracy": correct / 15,
            "exact_bracket": correct == 15,
        }

    return {
        "scope": "Conditional on retrospective draw scenario; not an unconditional forecast",
        "own_predicted_winners": {k: metrics(v["matches"]) for k, v in forecasts.items()},
        "actual_participants": {
            "metrics": metrics(actual_participants),
            "predictions": actual_participants,
        },
        "actual_winners": labels,
    }


def backtest_tournaments(engine, seasons):
    if not seasons or len(set(seasons)) != len(seasons):
        raise ValueError("Provide distinct seasons")
    results = [forecast_tournament(engine, s, "observed_draw", evaluate=True) for s in seasons]
    summary = {}
    for mode in ("greedy", "global", "actual_participants"):
        rows = [
            r["evaluation"]["actual_participants"]["metrics"]
            if mode == "actual_participants"
            else r["evaluation"]["own_predicted_winners"][mode]
            for r in results
        ]
        stages = {
            stage: {key: sum(r["rounds"][stage][key] for r in rows) for key in ("correct", "total")}
            for stage in ROUNDS
        }
        correct = sum(r["correct"] for r in rows)
        summary[mode] = {
            "rounds": stages,
            "correct": correct,
            "total": 15 * len(rows),
            "accuracy": correct / (15 * len(rows)),
            "correct_finalists": sum(r["correct_finalists"] for r in rows),
            "finalists_total": 2 * len(rows),
            "correct_champions": sum(r["champion_correct"] for r in rows),
            "exact_brackets": sum(r["exact_bracket"] for r in rows),
            "seasons": len(rows),
        }
    return {
        "scope": "Retrospective draw-conditional evaluation; frozen pre-R16 ratings",
        "summary": summary,
        "seasons": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seasons", nargs="+", default=[f"{y}-{y + 1}" for y in range(2020, 2026)])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = get_engine()
    database = Path(engine.url.database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = backtest_tournaments(engine, args.seasons)
    if before != hashlib.sha256(database.read_bytes()).hexdigest():
        raise RuntimeError("Database changed during backtest; rerun on a stable snapshot")
    result["database_sha256"] = before
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result["summary"], indent=2))


if __name__ == "__main__":
    main()
