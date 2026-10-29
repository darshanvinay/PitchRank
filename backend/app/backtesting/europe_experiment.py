"""Offline residual-calibration experiment. No production ratings or data are written.

Run from backend: python -m app.backtesting.europe_experiment
    --output ../docs/europe-experiment.json
"""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import advancement_metrics, backtest_round_of_16
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match
from app.db.session import get_engine
from app.elo.season import replay_season
from app.services.ratings import played

TRAIN = tuple(f"{y}-{y + 1}" for y in range(2012, 2017))
VALIDATION = tuple(f"{y}-{y + 1}" for y in range(2017, 2020))
EVALUATION = tuple(f"{y}-{y + 1}" for y in range(2020, 2026))
COEFFICIENTS = (-8, -4, -2, -1, 0, 1, 2, 4, 8)
HALF_LIVES = (0.5, 1, 2, 4)
PRIOR_MATCHES = 10.0


def european_features(engine, cutoff, half_lives=HALF_LIVES, prior_matches=PRIOR_MATCHES):
    """Pre-match UCL innovations from the unchanged chronological Elo replay.

    Each UCL match contributes one signed residual per participant, not another
    Elo update. Ten zero-residual pseudo-matches shrink sparse histories to zero.
    """
    if type(cutoff) is not date or cutoff <= date(2010, 7, 1):
        raise ValueError("Invalid cutoff")
    if not math.isfinite(prior_matches) or prior_matches <= 0:
        raise ValueError("Prior match count must be positive")
    if any(not math.isfinite(h) or h <= 0 for h in half_lives):
        raise ValueError("Half-lives must be positive")
    config = SeasonConfig()
    with Session(engine) as session:
        matches = session.scalars(
            select(Match).where(
                Match.league.in_([*LEAGUES, "ucl"]),
                Match.status == "finished",
                Match.match_date >= date(2010, 7, 1),
                Match.match_date < cutoff,
            )
        ).all()
    members = dict.fromkeys(t for m in matches for t in (m.home_team_id, m.away_team_id))
    result, _ = replay_season(
        played(matches), members, config, offseason_regression=config.elo.season_regression
    )
    ucl_ids = {m.id for m in matches if m.league == "ucl"}
    features = {}
    for half_life in (None, *half_lives):
        sums, weights = defaultdict(float), defaultdict(float)
        for entry in result.entries:
            m, update = entry.match, entry.update
            if m.id not in ucl_ids:
                continue
            age = (cutoff - m.match_date).days / 365.25
            weight = 1.0 if half_life is None else 2 ** (-age / half_life)
            residual = update.actual_home - update.expected_home
            for team, sign in ((m.home_team_id, 1), (m.away_team_id, -1)):
                sums[team] += weight * sign * residual
                weights[team] += weight
        features[str(half_life)] = {
            team: sums[team] / (weights[team] + prior_matches) for team in members
        }
    # Descriptive ablation only: how much existing UCL results already affect Elo.
    domestic, _ = replay_season(
        played([m for m in matches if m.league != "ucl"]),
        members,
        config,
        offseason_regression=config.elo.season_regression,
    )
    return {
        "features": features,
        "prefix_matches": len(matches),
        "ucl_matches": len(ucl_ids),
        "latest_input": str(max((m.match_date for m in matches), default=None)),
        "ucl_rating_effect": {t: result.ratings[t] - domestic.ratings[t] for t in members},
    }


def calibrated_probability(p, difference, coefficient):
    if not all(math.isfinite(v) for v in (p, difference, coefficient)) or not 0 < p < 1:
        raise ValueError("Finite interior probability and finite calibration parameters required")
    if coefficient == 0 or difference == 0:
        return p  # Exact identity, including the saved baseline probabilities.
    logit = math.log(p) - math.log1p(-p) + coefficient * difference
    return 1 / (1 + math.exp(-logit)) if logit >= 0 else math.exp(logit) / (1 + math.exp(logit))


def adjusted_rows(seasons, features, coefficient=0, half_life=None):
    output = []
    for season in seasons:
        values = features[season["season"]]["features"][str(half_life)]
        for row in season["predictions"]:
            a, b = row["team_a_id"], row["team_b_id"]
            difference = values.get(a, 0) - values.get(b, 0)
            p = calibrated_probability(row["p_a"], difference, coefficient)
            output.append(
                {
                    **row,
                    "season": season["season"],
                    "baseline_p_a": row["p_a"],
                    "residual_difference": difference,
                    "p_a": p,
                    "p_b": 1 - p,
                    "predicted_winner": a if p >= 0.5 else b,
                }
            )
    return output


def select_parameters(
    training, validation, features, coefficients=COEFFICIENTS, half_lives=HALF_LIVES
):
    """Fit coefficients on training only; select C's decay on validation only."""
    if not coefficients or 0 not in coefficients or any(not math.isfinite(b) for b in coefficients):
        raise ValueError("Coefficient grid must be finite and include zero")
    if not half_lives or any(not math.isfinite(h) or h <= 0 for h in half_lives):
        raise ValueError("Half-life grid must be positive and finite")
    candidates = []
    for half_life in (None, *half_lives):
        fits = [
            (
                advancement_metrics(adjusted_rows(training, features, beta, half_life))["log_loss"],
                abs(beta),
                beta,
            )
            for beta in coefficients
        ]
        loss, _, beta = min(fits)  # Prefer less adjustment on exact ties.
        candidates.append(
            {
                "half_life_years": half_life,
                "coefficient": beta,
                "training_log_loss": loss,
                "validation": advancement_metrics(
                    adjusted_rows(validation, features, beta, half_life)
                ),
            }
        )
    b = candidates[0]
    c = min(
        candidates[1:],
        key=lambda r: (r["validation"]["log_loss"], abs(r["coefficient"]), r["half_life_years"]),
    )
    return {"B": b, "C": c}, candidates


def compare(rows, baseline):
    metrics = advancement_metrics(rows)
    original = advancement_metrics(baseline)
    gained = sum(
        r["predicted_winner"] == r["actual_winner"] and a["predicted_winner"] != a["actual_winner"]
        for r, a in zip(rows, baseline, strict=True)
    )
    lost = sum(
        r["predicted_winner"] != r["actual_winner"] and a["predicted_winner"] == a["actual_winner"]
        for r, a in zip(rows, baseline, strict=True)
    )
    n = gained + lost
    exact_p = min(1.0, 2 * sum(math.comb(n, k) for k in range(min(gained, lost) + 1)) / 2**n)
    return {
        "metrics": metrics,
        "delta_vs_A": {k: metrics[k] - original[k] for k in original},
        "gained": gained,
        "lost": lost,
        "paired_accuracy_exact_p": exact_p,
        "predictions": rows,
    }


def run_experiment(
    engine, coefficients=COEFFICIENTS, half_lives=HALF_LIVES, prior_matches=PRIOR_MATCHES
):
    seasons = [backtest_round_of_16(engine, s) for s in (*TRAIN, *VALIDATION, *EVALUATION)]
    features = {
        s["season"]: european_features(
            engine, date.fromisoformat(s["cutoff"]), half_lives, prior_matches
        )
        for s in seasons
    }
    groups = {
        "training": [s for s in seasons if s["season"] in TRAIN],
        "validation": [s for s in seasons if s["season"] in VALIDATION],
        "evaluation": [s for s in seasons if s["season"] in EVALUATION],
    }
    selected, candidates = select_parameters(
        groups["training"], groups["validation"], features, coefficients, half_lives
    )
    results = {}
    for name, group in groups.items():
        baseline = adjusted_rows(group, features)
        models = {"A": compare(baseline, baseline)}
        for model, params in selected.items():
            rows = adjusted_rows(group, features, params["coefficient"], params["half_life_years"])
            models[model] = compare(rows, baseline)
        # Decision-only comparator: it does not claim calibrated probabilities.
        correct = sum(
            (r["team_a_id"] if r["elo_a"] >= r["elo_b"] else r["team_b_id"]) == r["actual_winner"]
            for r in baseline
        )
        results[name] = {
            "models": models,
            "higher_elo_wins": {
                "correct": correct,
                "ties": len(baseline),
                "accuracy": correct / len(baseline),
                "brier_score": None,
                "log_loss": None,
                "note": "Decision rule only; no forecast probability to score.",
            },
        }
    reference = groups["evaluation"][0]
    effects = features[reference["season"]]
    return {
        "revision": "ucl-residual-offset-v1",
        "splits": {"training": TRAIN, "validation": VALIDATION, "evaluation": EVALUATION},
        "search": {
            "coefficients": coefficients,
            "half_lives_years": half_lives,
            "prior_matches": prior_matches,
            "objective": "natural-log loss",
        },
        "selected": selected,
        "candidates": candidates,
        "results": results,
        "baseline_seasons": seasons,
        "coverage": {
            s["season"]: {
                k: v
                for k, v in features[s["season"]].items()
                if k != "features" and k != "ucl_rating_effect"
            }
            for s in seasons
        },
        "existing_europe_effect_2020": [
            {
                "club": r[f"team_{side}"],
                "elo": r[f"elo_{side}"],
                "elo_minus_domestic_only": effects["ucl_rating_effect"][r[f"team_{side}_id"]],
            }
            for r in reference["predictions"]
            for side in ("a", "b")
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--half-lives", type=float, nargs="+", default=HALF_LIVES)
    parser.add_argument("--coefficients", type=float, nargs="+", default=COEFFICIENTS)
    parser.add_argument("--prior-matches", type=float, default=PRIOR_MATCHES)
    args = parser.parse_args()
    engine = get_engine()
    database = Path(engine.url.database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = run_experiment(engine, args.coefficients, args.half_lives, args.prior_matches)
    after = hashlib.sha256(database.read_bytes()).hexdigest()
    if before != after:
        raise RuntimeError("Database changed during experiment; rerun on a stable snapshot")
    result["database_sha256"] = before
    args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(
        json.dumps(
            {
                "selected": result["selected"],
                "evaluation": {
                    name: data["metrics"]
                    for name, data in result["results"]["evaluation"]["models"].items()
                },
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
