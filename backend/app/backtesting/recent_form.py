"""Offline recent-form Elo/advancement-probability ensembles. No production imports of this module.

First run --stage individual, inspect errors, then --stage ensemble --input the saved JSON.
"""

import argparse
import hashlib
import json
import math
from datetime import date
from functools import lru_cache
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import (
    TieFixture,
    actual_winner,
    advancement_metrics,
    advancement_probability,
    conditional_scores,
)
from app.backtesting.tournament import (
    ROUNDS,
    build_tree,
    evaluate_forecasts,
    final_probability,
    grouped_ties,
    solve_bracket,
)
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, Team
from app.db.session import get_engine
from app.elo.season import replay_season
from app.predictions.model import PredictionConfig
from app.services.ratings import played
from app.services.season import fingerprint

TRAIN = tuple(f"{y}-{y + 1}" for y in range(2013, 2017))
VALIDATION = tuple(f"{y}-{y + 1}" for y in range(2017, 2020))
TEST = tuple(f"{y}-{y + 1}" for y in range(2020, 2026))
WEIGHTS = tuple(i / 10 for i in range(11))  # B weight; declared before error inspection.


def window_start(cutoff, years):
    if years not in (1, 2, 3):
        raise ValueError("Recent replay window must be 1, 2 or 3 years")
    try:
        return cutoff.replace(year=cutoff.year - years)
    except ValueError:
        return cutoff.replace(year=cutoff.year - years, day=28)


def reconstruct(matches, cutoff, years=None, k=20):
    start = date(2010, 7, 1) if years is None else window_start(cutoff, years)
    prefix = [m for m in matches if m.status == "finished" and start <= m.match_date < cutoff]
    config = SeasonConfig()
    config = config.model_copy(update={"elo": config.elo.model_copy(update={"k_factor": k})})
    members = dict.fromkeys(t for m in prefix for t in (m.home_team_id, m.away_team_id))
    replay, _ = replay_season(
        played(prefix), members, config, offseason_regression=config.elo.season_regression
    )
    return {
        "ratings": replay.ratings,
        "start": str(start),
        "cutoff": str(cutoff),
        "matches": len(prefix),
        "latest": str(max((m.match_date for m in prefix), default=None)),
        "input_hash": fingerprint(prefix, [], config),
    }


def rows(model, seasons):
    return [r for s in model["seasons"] if s["season"] in seasons for r in s["predictions"]]


def calibration(records):
    output = []
    for i in range(5):
        selected = [r for r in records if min(int(r["p_a"] * 5), 4) == i]
        output.append(
            {
                "lower": i / 5,
                "upper": (i + 1) / 5,
                "n": len(selected),
                "mean_probability": float(np.mean([r["p_a"] for r in selected]))
                if selected
                else None,
                "actual_rate": float(
                    np.mean([r["actual_winner"] == r["team_a_id"] for r in selected])
                )
                if selected
                else None,
            }
        )
    return output


def compare_errors(a, b):
    if [(r["season"], r["tie_id"], r["team_a_id"], r["actual_winner"]) for r in a] != [
        (r["season"], r["tie_id"], r["team_a_id"], r["actual_winner"]) for r in b
    ]:
        raise ValueError("Unaligned prediction records")
    correct_a = [r["predicted_winner"] == r["actual_winner"] for r in a]
    correct_b = [r["predicted_winner"] == r["actual_winner"] for r in b]
    n01 = sum(not x and y for x, y in zip(correct_a, correct_b, strict=True))
    n10 = sum(x and not y for x, y in zip(correct_a, correct_b, strict=True))
    n = n01 + n10
    return {
        "n": len(a),
        "both_correct": sum(x and y for x, y in zip(correct_a, correct_b, strict=True)),
        "both_wrong": sum(not x and not y for x, y in zip(correct_a, correct_b, strict=True)),
        "B_rescues_A": n01,
        "B_spoils_A": n10,
        "disagreements": n,
        "oracle_union_correct": sum(x or y for x, y in zip(correct_a, correct_b, strict=True)),
        "paired_accuracy_exact_p": min(
            1, 2 * sum(math.comb(n, i) for i in range(min(n01, n10) + 1)) / 2**n
        ),
        "A_wrong": [r for r in a if r["predicted_winner"] != r["actual_winner"]],
        "B_wrong": [r for r in b if r["predicted_winner"] != r["actual_winner"]],
        "disagreement_ties": [
            {"A": x, "B": y}
            for x, y in zip(a, b, strict=True)
            if x["predicted_winner"] != y["predicted_winner"]
        ],
    }


def blend_rows(a, b, weight):
    if not math.isfinite(weight) or not 0 <= weight <= 1:
        raise ValueError("B weight must be between zero and one")
    compare_errors(a, b)
    output = []
    for x, y in zip(a, b, strict=True):
        p = (
            x["p_a"]
            if weight == 0
            else y["p_a"]
            if weight == 1
            else (1 - weight) * x["p_a"] + weight * y["p_a"]
        )
        output.append(
            {
                **x,
                "p_a": p,
                "p_b": 1 - p,
                "predicted_winner": x["team_a_id"] if p >= 0.5 else x["team_b_id"],
            }
        )
    return output


def select_weight(a, b):
    candidates = [
        {"weight_B": w, "metrics": advancement_metrics(blend_rows(a, b, w))} for w in WEIGHTS
    ]
    return min(candidates, key=lambda r: (r["metrics"]["log_loss"], r["weight_B"])), candidates


def wilson(k, n):
    z = 1.96
    center = (k / n + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [center - half, center + half]


def score(records, baseline=None):
    metrics = advancement_metrics(records)
    output = {
        "metrics": metrics,
        "calibration": calibration(records),
        "accuracy_wilson_95": wilson(metrics["correct"], metrics["ties"]),
        "favorite_confidence": float(np.mean([max(r["p_a"], 1 - r["p_a"]) for r in records])),
    }
    if baseline is not None:
        diffs = []
        for season in sorted({r["season"] for r in records}):
            losses = []
            for x, y in zip(
                [r for r in records if r["season"] == season],
                [r for r in baseline if r["season"] == season],
                strict=True,
            ):
                actual = x["actual_winner"] == x["team_a_id"]
                losses.append(
                    -math.log(x["p_a"] if actual else 1 - x["p_a"])
                    + math.log(y["p_a"] if actual else 1 - y["p_a"])
                )
            diffs.append(float(np.mean(losses)))
        delta = float(np.mean(diffs))
        se = float(np.std(diffs, ddof=1) / math.sqrt(len(diffs))) if len(diffs) > 1 else 0
        output["paired_log_loss_delta"] = delta
        output["paired_season_approx_95"] = [delta - 2.571 * se, delta + 2.571 * se]
        output["delta_vs_A"] = {
            k: metrics[k] - advancement_metrics(baseline)[k]
            for k in ("accuracy", "brier_score", "log_loss")
        }
    return output


def load(engine):
    with Session(engine) as session:
        matches = session.scalars(
            select(Match).where(
                Match.league.in_([*LEAGUES, "ucl"]),
                Match.status == "finished",
                Match.match_date >= date(2010, 7, 1),
                Match.match_date < date(2026, 7, 1),
            )
        ).all()
        names = {t.id: t.display_name for t in session.scalars(select(Team))}
    return matches, names


def individual_experiment(engine):
    matches, names = load(engine)
    candidates = [("A", None, 20)] + [
        (f"B-window{w}-K{k}", w, k) for w in (1, 2, 3) for k in (20, 25, 30, 40)
    ]
    models = {key: {"years": years, "k": k, "seasons": []} for key, years, k in candidates}
    for season in (*TRAIN, *VALIDATION, *TEST):
        print("Individual " + season, flush=True)
        ties = grouped_ties(
            [m for m in matches if m.league == "ucl" and m.season == season], "round_of_16", 8
        )
        cutoff = min(legs[0].match_date for _, legs in ties)
        conditionals = conditional_scores([m for m in matches if m.match_date < cutoff])
        for key, years, k in candidates:
            snapshot = reconstruct(matches, cutoff, years, k)
            ratings = snapshot.pop("ratings")
            required = {t for _, (m, _) in ties for t in (m.home_team_id, m.away_team_id)}
            if not required <= ratings.keys():
                raise ValueError("Participating club has no pre-cutoff recent match history")
            forecasts = []
            for tid, (first, second) in ties:
                a, b = first.home_team_id, first.away_team_id
                p = advancement_probability(
                    TieFixture(a, b, first.neutral, second.neutral),
                    ratings,
                    conditionals,
                    PredictionConfig(),
                    int(season[:4]) <= 2020,
                )
                forecasts.append(
                    {
                        "season": season,
                        "tie_id": tid,
                        "team_a_id": a,
                        "team_b_id": b,
                        "team_a": names[a],
                        "team_b": names[b],
                        "p_a": p,
                        "p_b": 1 - p,
                        "predicted_winner": a if p >= 0.5 else b,
                        "elo_a": ratings[a],
                        "elo_b": ratings[b],
                    }
                )
            models[key]["seasons"].append(
                {
                    "season": season,
                    **snapshot,
                    "predictions": forecasts,
                    "ratings": {
                        t: ratings[t]
                        for _, (m, _) in ties
                        for t in (m.home_team_id, m.away_team_id)
                    },
                }
            )
        # Read result labels only after every candidate's forecasts have been frozen.
        labels = {
            tid: (
                first.home_team_id
                if actual_winner(first, second, int(season[:4]) <= 2020) == "A"
                else first.away_team_id
            )
            for tid, (first, second) in ties
        }
        for model in models.values():
            for r in model["seasons"][-1]["predictions"]:
                r["actual_winner"] = labels[r["tie_id"]]
    best = min(
        (key for key in models if key != "A"),
        key=lambda key: (
            advancement_metrics(rows(models[key], TRAIN))["log_loss"],
            models[key]["k"],
            models[key]["years"],
        ),
    )
    comparisons = {
        key: {
            "training": score(rows(model, TRAIN)),
            "validation": score(rows(model, VALIDATION)),
            "test": score(rows(model, TEST), rows(models["A"], TEST)),
        }
        for key, model in models.items()
    }
    return {
        "stage": "individual",
        "splits": {"training": TRAIN, "validation": VALIDATION, "test": TEST},
        "protocol": {
            "windows": "Rolling calendar years, neutral 1500 reset at window start",
            "cutoff": "Earliest R16 first-leg date, exclusive for all ties",
            "K_grid": [20, 25, 30, 40],
            "weight_grid_B": WEIGHTS,
            "selection": "B by training log loss; weight by validation log loss",
            "test_status": "Previously examined seasons; retrospective parameter-held-out",
        },
        "selected_B": best,
        "comparisons": comparisons,
        "models": models,
        "individual_errors": {
            split: compare_errors(rows(models["A"], seasons), rows(models[best], seasons))
            for split, seasons in [("validation", VALIDATION), ("test", TEST)]
        },
    }


def higher_bracket(root, ratings):
    """Decision-only propagated bracket; do not invent probability confidence."""

    def visit(node):
        if isinstance(node, int):
            return node, []
        a, left = visit(node.left)
        b, right = visit(node.right)
        winner = a if ratings[a] >= ratings[b] else b
        return winner, left + right + [
            {
                "id": node.id,
                "round": node.round,
                "team_a_id": a,
                "team_b_id": b,
                "winner_id": winner,
            }
        ]

    champion, matches = visit(root)
    return {"champion_id": champion, "matches": matches}


def bracket_comparison(matches, models, weight, season):
    rounds = {
        r: grouped_ties([m for m in matches if m.league == "ucl" and m.season == season], r, n)
        for r, n in zip(ROUNDS, (8, 4, 2, 1), strict=True)
    }
    root = build_tree(rounds, "observed_draw")
    cutoff = min(legs[0].match_date for _, legs in rounds["round_of_16"])
    conditionals = conditional_scores([m for m in matches if m.match_date < cutoff])
    ratings = [
        {
            int(t): v
            for t, v in next(s for s in model["seasons"] if s["season"] == season)[
                "ratings"
            ].items()
        }
        for model in models
    ]

    @lru_cache(maxsize=None)
    def probability(node, a, b):
        def component(rs):
            if node.round == "final":
                return final_probability(a, b, rs, conditionals, PredictionConfig())
            return advancement_probability(
                TieFixture(a, b, node.neutral_first, node.neutral_second),
                rs,
                conditionals,
                PredictionConfig(),
                int(season[:4]) <= 2020,
            )

        if weight == 0:
            return component(ratings[0])
        if weight == 1:
            return component(ratings[1])
        return (1 - weight) * component(ratings[0]) + weight * component(ratings[1])

    forecasts = {
        method: solve_bracket(root, probability, method) for method in ("greedy", "global")
    }
    evaluation = evaluate_forecasts(root, rounds, forecasts, probability, int(season[:4]) <= 2020)
    # Higher-Elo heuristic is defined for A/B; an advancement-probability mixture has no Elo scale.
    higher = {}
    for label, rs in zip(("A", "B"), ratings, strict=True):
        higher[label] = {
            r: sum(
                (p["team_a_id"] if rs[p["team_a_id"]] >= rs[p["team_b_id"]] else p["team_b_id"])
                == p["actual_winner_id"]
                for p in evaluation["actual_participants"]["predictions"]
                if p["round"] == r
            )
            for r in ROUNDS
        }
    higher_own = {}
    for label, rs in zip(("A", "B"), ratings, strict=True):
        decision = higher_bracket(root, rs)
        measured = evaluate_forecasts(
            root, rounds, {"decision": decision}, probability, int(season[:4]) <= 2020
        )
        higher_own[label] = measured["own_predicted_winners"]["decision"]
    return {
        "season": season,
        "cutoff": str(cutoff),
        "conditional_future_draws": True,
        "forecasts": forecasts,
        "evaluation": evaluation,
        "higher_elo": higher,
        "higher_elo_own": higher_own,
    }


def ensemble_experiment(engine, individual):
    a = individual["models"]["A"]
    b = individual["models"][individual["selected_B"]]
    selected, grid = select_weight(rows(a, VALIDATION), rows(b, VALIDATION))
    matches, _ = load(engine)
    output = {
        "stage": "ensemble",
        "selected_B": individual["selected_B"],
        "weight_selection": selected,
        "weight_candidates": grid,
        "results": {},
        "splits": individual["splits"],
        "scope": "Conditional on recorded future draws; pre-R16 ratings frozen",
    }
    for name, w in [("A", 0), ("B", 1), ("equal", 0.5), ("weighted", selected["weight_B"])]:
        print("Ensemble " + name, flush=True)
        records = blend_rows(rows(a, TEST), rows(b, TEST), w)
        forecasts = [bracket_comparison(matches, (a, b), w, season) for season in TEST]
        actual = [
            p for s in forecasts for p in s["evaluation"]["actual_participants"]["predictions"]
        ]
        stage_scores = {}
        for stage in ROUNDS:
            subset = [
                {
                    "team_a_id": r["team_a_id"],
                    "p_a": r["p_a"],
                    "predicted_winner": r["winner_id"],
                    "actual_winner": r["actual_winner_id"],
                }
                for r in actual
                if r["round"] == stage
            ]
            stage_scores[stage] = advancement_metrics(subset)
        full = {}
        for method in ("greedy", "global"):
            metric = [s["evaluation"]["own_predicted_winners"][method] for s in forecasts]
            full[method] = {
                "correct": sum(m["correct"] for m in metric),
                "total": 90,
                "champions": sum(m["champion_correct"] for m in metric),
                "finalists": sum(m["correct_finalists"] for m in metric),
                "exact_brackets": sum(m["exact_bracket"] for m in metric),
                "seasons": 6,
            }
        output["results"][name] = {
            "weight_B": w,
            "r16": score(records, rows(a, TEST)),
            "predictions": records,
            "conditional_actual_participants": stage_scores,
            "conditional_own_winners": full,
            "seasons": forecasts,
            "higher_elo_own": {
                label: {
                    key: sum(s["higher_elo_own"][label][key] for s in forecasts)
                    for key in (
                        "correct",
                        "total",
                        "correct_finalists",
                        "champion_correct",
                        "exact_bracket",
                    )
                }
                for label in ("A", "B")
            },
            "higher_elo": {
                label: {r: sum(s["higher_elo"][label][r] for s in forecasts) for r in ROUNDS}
                for label in ("A", "B")
            },
        }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("individual", "ensemble"), default="individual")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = get_engine()
    database = Path(engine.url.database)
    signature = hashlib.sha256(database.read_bytes()).hexdigest()
    if args.stage == "individual":
        result = individual_experiment(engine)
    else:
        if not args.input:
            parser.error("--input is required for ensemble stage")
        individual = json.loads(args.input.read_text())
        if individual["database_sha256"] != signature:
            raise ValueError("Saved individual data hash differs")
        result = ensemble_experiment(engine, individual)
        result["individual_artifact_sha256"] = hashlib.sha256(args.input.read_bytes()).hexdigest()
    if signature != hashlib.sha256(database.read_bytes()).hexdigest():
        raise RuntimeError("Database changed")
    result["database_sha256"] = signature
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print("Saved " + str(args.output))


if __name__ == "__main__":
    main()
