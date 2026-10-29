"""Offline cross-league calibration audit. Never imported by production services.

Run: python -m app.backtesting.cross_league --output results.json
"""

import argparse
import hashlib
import json
import math
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import date
from functools import lru_cache
from itertools import groupby
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import (
    TieFixture,
    actual_winner,
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
from app.elo.engine import update_ratings
from app.elo.season import replay_season
from app.predictions.model import PredictionConfig, probabilities
from app.services.ratings import played

TRAIN = tuple(range(2012, 2017))
VALIDATION = tuple(range(2017, 2020))
TEST = tuple(range(2020, 2026))
KEYS = tuple(LEAGUES)
DATA_AS_OF = date(2026, 10, 29)


@dataclass(frozen=True)
class Variant:
    name: str = "A"
    offset_sd: float = 0
    half_life: float = 2
    newcomer_blend: float = 0
    margin_cap: float = math.inf

    def __post_init__(self):
        if (
            not math.isfinite(self.offset_sd)
            or self.offset_sd < 0
            or not math.isfinite(self.half_life)
            or self.half_life <= 0
            or not 0 <= self.newcomer_blend <= 1
            or math.isnan(self.margin_cap)
            or self.margin_cap < 1
        ):
            raise ValueError("Invalid experimental parameters")


def league_offsets(observations, cutoff, sd, half_life):
    """Ridge fractional-logistic residual fit, conditional on existing pre-match Elo.

    0-centered Gaussian prior, estimated only from previously observed cross-league
    UCL games. Country membership must have been observed in domestic results.
    """
    if sd == 0 or not observations:
        return dict.fromkeys(KEYS, 0.0)
    if sd < 0 or half_life <= 0:
        raise ValueError("Positive offset prior and half-life required")
    rows = [r for r in observations if r[0] < cutoff]
    if not rows:
        return dict.fromkeys(KEYS, 0.0)
    x = np.array([r[1] for r in rows])
    logits = np.array([r[2] for r in rows])
    y = np.array([r[3] for r in rows])
    weights = np.array([2 ** (-(cutoff - r[0]).days / (365.25 * half_life)) for r in rows])
    scale = math.log(10) / 400
    beta = np.zeros(len(KEYS))
    for _ in range(30):
        p = 1 / (1 + np.exp(-np.clip(logits + scale * x @ beta, -40, 40)))
        gradient = scale * x.T @ (weights * (y - p)) - beta / sd**2
        hessian = scale**2 * (x.T * (weights * p * (1 - p))) @ x + np.eye(len(KEYS)) / sd**2
        step = np.linalg.solve(hessian, gradient)
        beta += step
        if np.max(np.abs(step)) < 1e-7:
            break
    return dict(zip(KEYS, beta.tolist(), strict=True))


def match_prob(home, away, neutral=False):
    config = PredictionConfig()
    if neutral:
        config = config.model_copy(
            update={"elo": config.elo.model_copy(update={"home_advantage": 0})}
        )
    return probabilities(home, away, config).tolist()


def loss_record(p, actual):
    return dict(
        n=1,
        correct=int(int(np.argmax(p)) == actual),
        brier=sum((v - int(i == actual)) ** 2 for i, v in enumerate(p)),
        log_loss=-math.log(max(p[actual], 1e-15)),
    )


def sum_metrics(rows):
    n = sum(r["n"] for r in rows)
    if not n:
        return {"n": 0}
    return {
        "n": n,
        "correct": sum(r["correct"] for r in rows),
        "accuracy": sum(r["correct"] for r in rows) / n,
        "brier": sum(r["brier"] for r in rows) / n,
        "log_loss": sum(r["log_loss"] for r in rows) / n,
        **(
            {"higher_elo_correct": sum(r["higher_correct"] for r in rows)}
            if rows and "higher_correct" in rows[0]
            else {}
        ),
    }


def experimental_entries(matches, variant):
    """Small offline replay adapter; all mathematical Elo updates call existing update_ratings.

    A/B dispatch to the production historical replay. Only C/D need a different
    initialization/update policy. Chronological date/kickoff batching is identical.
    """
    config = SeasonConfig()
    members = dict.fromkeys(t for m in matches for t in (m.home_team_id, m.away_team_id))
    if variant.newcomer_blend == 0 and math.isinf(variant.margin_cap):
        replay, _ = replay_season(
            played(matches), members, config, offseason_regression=config.elo.season_regression
        )
        return [
            (
                e.match.id,
                e.update.home_before,
                e.update.away_before,
                e.update.home_change,
                e.update.away_change,
            )
            for e in replay.entries
        ]
    if len({m.id for m in matches}) != len(matches):
        raise ValueError("Duplicate match IDs")
    ratings = dict.fromkeys(members, 1500.0)
    last, domestic_last, starts = {}, {}, {}
    endings = defaultdict(dict)
    output = []
    ordered = sorted(matches, key=lambda m: (m.match_date, m.home_team_id, m.away_team_id))
    for _, day in groupby(ordered, key=lambda m: m.match_date):
        day = list(day)
        if any(m.kickoff_at is None for m in day):
            batches = [day]
        else:
            day.sort(key=lambda m: (m.kickoff_at, m.home_team_id, m.away_team_id))
            batches = [list(g) for _, g in groupby(day, key=lambda m: m.kickoff_at)]
        for batch in batches:
            seen = set()
            for m in batch:
                year = int(m.season[:4])
                for t in (m.home_team_id, m.away_team_id):
                    if t in seen:
                        raise ValueError("Club repeated in kickoff group")
                    seen.add(t)
                    if year < last.get(t, year):
                        raise ValueError("Overlapping club seasons")
                    if year > last.get(t, year):
                        ratings[t] = 1500 + (ratings[t] - 1500) * 0.75 ** (year - last[t])
                    starts.setdefault((t, year), ratings[t])
                    last[t] = year
                    if m.league in KEYS and domestic_last.get(t) != year:
                        if domestic_last.get(t) != year - 1:
                            prior_values = sorted(endings[(m.league, year - 1)].values())
                            if prior_values:
                                bottom = prior_values[: max(1, len(prior_values) // 4)]
                                prior = max(1350, min(1500, float(np.mean(bottom))))
                                # Shift the prior, retaining results already earned this season.
                                ratings[t] += variant.newcomer_blend * (prior - starts[t, year])
                        domestic_last[t] = year
                importance = {"domestic": 1, "league": 1.25, "knockout": 1.5, "finals": 1.75}[
                    m.stage
                ]
                u = update_ratings(
                    ratings[m.home_team_id],
                    ratings[m.away_team_id],
                    m.home_goals,
                    m.away_goals,
                    config.elo,
                    importance,
                    m.neutral,
                )
                factor = min(u.multiplier, variant.margin_cap) / u.multiplier
                dh, da = u.home_change * factor, u.away_change * factor
                output.append((m.id, u.home_before, u.away_before, dh, da))
                ratings[m.home_team_id] += dh
                ratings[m.away_team_id] += da
                if m.league in KEYS:
                    for t in (m.home_team_id, m.away_team_id):
                        endings[m.league, year][t] = ratings[t]
    return output


def replay_variant(matches, variant, cutoffs):
    by_id = {m.id: m for m in matches}
    entries = experimental_entries(matches, variant)
    by_day = defaultdict(list)
    for entry in entries:
        by_day[by_id[entry[0]].match_date].append(entry)
    ratings, membership = {}, {}
    observations, snapshots, scores = [], {}, defaultdict(list)
    net = defaultdict(float)
    adjustment_mass = 0.0
    month_offsets, previous_month = dict.fromkeys(KEYS, 0.0), None
    cutoff_set = set(cutoffs.values())
    for day in sorted(set(by_day) | cutoff_set):
        month = day.replace(day=1)
        if month != previous_month:
            month_offsets = league_offsets(
                observations, month, variant.offset_sd, variant.half_life
            )
            previous_month = month
        if day in cutoff_set:
            offset = league_offsets(observations, day, variant.offset_sd, variant.half_life)
            adjusted = {t: r + offset.get(membership.get(t), 0) for t, r in ratings.items()}
            snapshots[day] = {
                "ratings": adjusted,
                "base_ratings": ratings.copy(),
                "offsets": offset,
                "membership": membership.copy(),
                "ucl_net": dict(net),
                "pool_deviation": sum(r - 1500 for r in ratings.values()),
                "adjustment_mass": adjustment_mass,
                "seen_clubs": len(ratings),
            }
        for mid, home, away, dh, da in by_day[day]:
            m = by_id[mid]
            # Fixture competition identifies membership without future season lists.
            if m.league in KEYS:
                membership[m.home_team_id] = membership[m.away_team_id] = m.league
            lh, la = membership.get(m.home_team_id), membership.get(m.away_team_id)
            p = match_prob(
                home + month_offsets.get(lh, 0), away + month_offsets.get(la, 0), m.neutral
            )
            actual = 0 if m.home_goals > m.away_goals else 1 if m.home_goals == m.away_goals else 2
            scores[int(m.season[:4]), "ucl" if m.league == "ucl" else "domestic"].append(
                {
                    **loss_record(p, actual),
                    "higher_correct": int(
                        (
                            0
                            if home + month_offsets.get(lh, 0) >= away + month_offsets.get(la, 0)
                            else 2
                        )
                        == actual
                    ),
                }
            )
            for team, before in ((m.home_team_id, home), (m.away_team_id, away)):
                adjustment_mass += before - ratings.get(team, 1500)
            ratings[m.home_team_id], ratings[m.away_team_id] = home + dh, away + da
            if m.league == "ucl":
                net[lh or "outside_unknown"] += dh
                net[la or "outside_unknown"] += da
                if lh in KEYS and la in KEYS and lh != la:
                    x = [int(k == lh) - int(k == la) for k in KEYS]
                    baseline_logit = (home - away + (0 if m.neutral else 65)) * math.log(10) / 400
                    observations.append((day, x, baseline_logit, (1, 0.5, 0)[actual]))
    return {"snapshots": snapshots, "scores": scores}


def evaluate_season(matches, season, snapshot, r16_only=False):
    rounds = {
        r: grouped_ties([m for m in matches if m.league == "ucl" and m.season == season], r, n)
        for r, n in ([("round_of_16", 8)] if r16_only else zip(ROUNDS, (8, 4, 2, 1), strict=True))
    }
    if r16_only:
        cutoff = min(legs[0].match_date for _, legs in rounds["round_of_16"])
        conditionals = conditional_scores([m for m in matches if m.match_date < cutoff])
        ratings = snapshot["ratings"]
        rows = []
        higher = 0
        for _, (first, second) in rounds["round_of_16"]:
            a, b = first.home_team_id, first.away_team_id
            p = advancement_probability(
                TieFixture(a, b, first.neutral, second.neutral),
                ratings,
                conditionals,
                PredictionConfig(),
                int(season[:4]) <= 2020,
            )
            actual_a = actual_winner(first, second, int(season[:4]) <= 2020) == "A"
            success = p if actual_a else 1 - p
            rows.append(
                dict(
                    n=1,
                    correct=int((p >= 0.5) == actual_a),
                    brier=(1 - success) ** 2,
                    log_loss=-math.log(success),
                )
            )
            higher += int((ratings[a] >= ratings[b]) == actual_a)
        return {
            "season": season,
            "cutoff": str(cutoff),
            "stage_metrics": {
                "round_of_16": {
                    k: sum(r[k] for r in rows) for k in ("n", "correct", "brier", "log_loss")
                }
            },
            "higher_elo_wins": {"round_of_16": {"correct": higher, "total": 8}},
            "scope": "Validation R16 only; COVID 2019/20 later rounds excluded, not mis-modeled",
        }
    root = build_tree(rounds, "observed_draw")
    cutoff = min(legs[0].match_date for _, legs in rounds["round_of_16"])
    scores = conditional_scores([m for m in matches if m.match_date < cutoff])
    ratings = snapshot["ratings"]
    away_goals = int(season[:4]) <= 2020

    @lru_cache(maxsize=None)
    def probability(node, a, b):
        if node.round == "final":
            return final_probability(a, b, ratings, scores, PredictionConfig())
        return advancement_probability(
            TieFixture(a, b, node.neutral_first, node.neutral_second),
            ratings,
            scores,
            PredictionConfig(),
            away_goals,
        )

    forecasts = {
        method: solve_bracket(root, probability, method) for method in ("greedy", "global")
    }
    evaluation = evaluate_forecasts(root, rounds, forecasts, probability, away_goals)
    actual_rows = evaluation["actual_participants"]["predictions"]
    stage_metrics = {}
    for stage in ROUNDS:
        rows = [r for r in actual_rows if r["round"] == stage]
        p = [r["p_a"] if r["actual_winner_id"] == r["team_a_id"] else 1 - r["p_a"] for r in rows]
        stage_metrics[stage] = {
            "n": len(rows),
            "correct": sum(r["winner_id"] == r["actual_winner_id"] for r in rows),
            "brier": sum((1 - v) ** 2 for v in p),
            "log_loss": -sum(math.log(v) for v in p),
        }
    higher = {}
    for stage in ROUNDS:
        rows = [r for r in actual_rows if r["round"] == stage]
        higher[stage] = {
            "correct": sum(
                (
                    r["team_a_id"]
                    if ratings[r["team_a_id"]] >= ratings[r["team_b_id"]]
                    else r["team_b_id"]
                )
                == r["actual_winner_id"]
                for r in rows
            ),
            "total": len(rows),
        }
    return {
        "season": season,
        "cutoff": str(cutoff),
        "conditional_future_draws": True,
        "stage_metrics": stage_metrics,
        "evaluation": evaluation,
        "higher_elo_wins": higher,
        "forecasts": forecasts,
    }


def aggregate(replayed, years):
    return {
        scope: sum_metrics([r for y in years for r in replayed["scores"].get((y, scope), [])])
        for scope in ("ucl", "domestic")
    }


def wilson(correct, n):
    z = 1.96
    center = (correct / n + z * z / (2 * n)) / (1 + z * z / n)
    half = (
        z * math.sqrt(correct / n * (1 - correct / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    )
    return [center - half, center + half]


def summary(seasons):
    output = {}
    for stage in ROUNDS:
        rows = [s["stage_metrics"][stage] for s in seasons if stage in s["stage_metrics"]]
        if not rows:
            continue
        v = sum_metrics(rows)
        v["accuracy_wilson_95"] = wilson(v["correct"], v["n"])
        v["higher_elo_correct"] = sum(
            s["higher_elo_wins"][stage]["correct"] for s in seasons if stage in s["higher_elo_wins"]
        )
        output[stage] = v
    for method in ("greedy", "global"):
        rows = [
            s["evaluation"]["own_predicted_winners"][method] for s in seasons if "evaluation" in s
        ]
        if not rows:
            continue
        output[method] = {
            "correct": sum(r["correct"] for r in rows),
            "total": 15 * len(rows),
            "champions": sum(r["champion_correct"] for r in rows),
            "finalists": sum(r["correct_finalists"] for r in rows),
            "exact_brackets": sum(r["exact_bracket"] for r in rows),
            "seasons": len(rows),
        }
    return output


def run(engine):
    with Session(engine) as session:
        matches = session.scalars(
            select(Match).where(
                Match.league.in_([*KEYS, "ucl"]),
                Match.status == "finished",
                Match.match_date >= date(2010, 7, 1),
                Match.match_date <= DATA_AS_OF,
            )
        ).all()
        names = {t.id: t.display_name for t in session.scalars(select(Team))}
    cutoffs = {
        y: min(
            m.match_date
            for m in matches
            if m.league == "ucl"
            and int(m.season[:4]) == y
            and (m.ucl_detail or {}).get("round") == "round_of_16"
        )
        for y in (*TRAIN, *VALIDATION, *TEST)
    }
    candidates = [Variant()] + [
        Variant(f"B-sd{s}-h{h}", offset_sd=s, half_life=h) for s in (25, 75) for h in (1, 3)
    ]
    candidates += [Variant(f"C-blend{a}", newcomer_blend=a) for a in (0.5, 1)]
    candidates += [Variant(f"D-cap{c}", margin_cap=c) for c in (1.25, 1.75)]
    cache = {}
    for v in candidates:
        print(f"Replaying {v.name}", flush=True)
        cache[v.name] = replay_variant(matches, v, cutoffs)
    selected = {"A": candidates[0]}
    for family in ("B", "C", "D"):
        selected[family] = min(
            [v for v in candidates if v.name.startswith(family)],
            key=lambda v: aggregate(cache[v.name], TRAIN)["ucl"]["log_loss"],
        )
    # Individual experiments complete before combination; no test labels in this decision.
    base_val = aggregate(cache["A"], VALIDATION)["ucl"]["log_loss"]
    accepted = {
        k: v
        for k, v in selected.items()
        if k != "A" and aggregate(cache[v.name], VALIDATION)["ucl"]["log_loss"] < base_val
    }
    selected["E"] = Variant(
        "E",
        offset_sd=accepted.get("B", Variant()).offset_sd,
        half_life=accepted.get("B", Variant()).half_life,
        newcomer_blend=accepted.get("C", Variant()).newcomer_blend,
        margin_cap=accepted.get("D", Variant()).margin_cap,
    )
    cache["E"] = replay_variant(matches, selected["E"], cutoffs)
    # A combination must beat its constituent alternatives on validation, not just training.
    alternatives = [selected["A"], *accepted.values(), selected["E"]]
    best = min(alternatives, key=lambda v: aggregate(cache[v.name], VALIDATION)["ucl"]["log_loss"])
    if best.name != "E":
        selected["E"] = Variant(
            "E", best.offset_sd, best.half_life, best.newcomer_blend, best.margin_cap
        )
        cache["E"] = cache[best.name]
    output = {
        "splits": {"training": TRAIN, "validation": VALIDATION, "test": TEST},
        "test_status": "Historical test outcomes examined previously; no prospective-blind claim",
        "data_as_of": str(DATA_AS_OF),
        "latest_match": str(max(m.match_date for m in matches)),
        "current_holdout_status": "2026/27 match-only holdout, excluded from all selection; "
        "not previously scored in saved historical experiments",
        "candidates": [
            {
                **asdict(v),
                "margin_cap": None if math.isinf(v.margin_cap) else v.margin_cap,
                "training": aggregate(cache[v.name], TRAIN),
                "validation": aggregate(cache[v.name], VALIDATION),
            }
            for v in candidates
        ],
        "combination_components": [
            k
            for k, enabled in (
                ("B", selected["E"].offset_sd > 0),
                ("C", selected["E"].newcomer_blend > 0),
                ("D", not math.isinf(selected["E"].margin_cap)),
            )
            if enabled
        ],
        "models": {},
    }
    for model, v in selected.items():
        replay = cache[v.name]
        seasons = []
        for y in (*VALIDATION, *TEST):
            print(f"Evaluating {model} {y}", flush=True)
            seasons.append(
                evaluate_season(
                    matches,
                    f"{y}-{y + 1}",
                    replay["snapshots"][cutoffs[y]],
                    r16_only=y in VALIDATION,
                )
            )
        ranks = {}
        for y, cutoff in cutoffs.items():
            snap = replay["snapshots"][cutoff]
            active = {
                t
                for m in matches
                if m.league in KEYS and int(m.season[:4]) == y and m.match_date < cutoff
                for t in (m.home_team_id, m.away_team_id)
            }
            ordered = sorted(active, key=lambda t: (-snap["ratings"][t], t))
            top = [
                {
                    "rank": i + 1,
                    "team_id": t,
                    "club": names[t],
                    "league": snap["membership"][t],
                    "elo": snap["ratings"][t],
                    "gap_to_first": snap["ratings"][ordered[0]] - snap["ratings"][t],
                }
                for i, t in enumerate(ordered)
            ]
            bayern = next((r for r in top if r["club"] == "Bayern Munich"), None)
            means = {
                league: float(
                    np.mean([snap["ratings"][t] for t in active if snap["membership"][t] == league])
                )
                for league in KEYS
            }
            ranks[str(y)] = {
                "cutoff": str(cutoff),
                "top10": top[:10],
                "bayern": bayern,
                "league_mean": means,
                "offsets": snap["offsets"],
                "ucl_cumulative_net_points": snap["ucl_net"],
                "pool_deviation": snap["pool_deviation"],
                "non_match_adjustment_mass": snap["adjustment_mass"],
                "seen_clubs": snap["seen_clubs"],
            }
        output["models"][model] = {
            "parameters": {
                **asdict(v),
                "margin_cap": None if math.isinf(v.margin_cap) else v.margin_cap,
            },
            "match_training": aggregate(replay, TRAIN),
            "match_validation": aggregate(replay, VALIDATION),
            "match_test": aggregate(replay, TEST),
            "current_match_holdout": aggregate(replay, (2026,)),
            "match_test_by_season": {str(y): aggregate(replay, (y,)) for y in TEST},
            "validation": summary(seasons[: len(VALIDATION)]),
            "test": summary(seasons[len(VALIDATION) :]),
            "seasons": seasons,
            "rankings": ranks,
        }
    for model, data in output["models"].items():
        base = output["models"]["A"]
        uncertainty = {}
        for scope in ("ucl", "domestic", "round_of_16"):
            if scope == "round_of_16":
                a = [
                    s["stage_metrics"][scope]
                    for s in base["seasons"]
                    if int(s["season"][:4]) in TEST
                ]
                b = [
                    s["stage_metrics"][scope]
                    for s in data["seasons"]
                    if int(s["season"][:4]) in TEST
                ]
                counts = np.array([r["n"] for r in a])
                differences = np.array(
                    [v["log_loss"] - u["log_loss"] for u, v in zip(a, b, strict=True)]
                )
            else:
                a = [base["match_test_by_season"][str(y)][scope] for y in TEST]
                b = [data["match_test_by_season"][str(y)][scope] for y in TEST]
                counts = np.array([r["n"] for r in a])
                differences = np.array(
                    [
                        v["n"] * v["log_loss"] - u["n"] * u["log_loss"]
                        for u, v in zip(a, b, strict=True)
                    ]
                )
            delta = float(differences.sum() / counts.sum())
            se = float(np.sqrt(6 / 5 * np.sum((differences - counts * delta) ** 2)) / counts.sum())
            uncertainty[scope] = {
                "log_loss_delta_vs_A": delta,
                "season_cluster_approx_95": [delta - 2.571 * se, delta + 2.571 * se],
                "clusters": 6,
                "method": "Paired season-cluster SE; t(5) critical 2.571, descriptive",
            }
        data["paired_vs_A"] = uncertainty
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    engine = get_engine()
    database = Path(engine.url.database)
    before = hashlib.sha256(database.read_bytes()).hexdigest()
    result = run(engine)
    if before != hashlib.sha256(database.read_bytes()).hexdigest():
        raise RuntimeError("Database changed during experiment")
    result["database_sha256"] = before
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: v["test"] for k, v in result["models"].items()}, indent=2))


if __name__ == "__main__":
    main()
