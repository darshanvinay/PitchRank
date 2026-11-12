"""Independent scalar check for this run's simple highest-scoring diagnostic candidate.

Run from repo root with PYTHONPATH=backend .venv/bin/python experiments/verify_selected.py.
Requires local checkpoints; assertions deliberately reject unsupported candidate profiles.
"""

import json
import math
from pathlib import Path

import numpy as np
from app.backtesting.knockout import (
    extra_time_distribution,
    extra_time_winner,
    regulation_winner,
)
from app.backtesting.search_data import build_data, score_shapes
from app.core.elo import EloConfig
from app.db.session import get_engine
from app.elo.engine import goal_multiplier, update_ratings

root = Path("experiments")
top = json.loads((root / "top_models.json").read_text())[
    "all_trials_top5_including_diagnostics"
][0]
c = top["config"]
assert c["head"] == "expected" and c["margin"] == "linear" and c["offsets"] == "none"
assert (
    c["regression_target"] == "initial"
    and c["k_gap"]
    == c["k_stage"]
    == c["margin_adjust"]
    == c["form_weight"]
    == c["european_weight"]
    == 0
)
record = next(
    json.loads(line)
    for line in (root / "diagnostics.jsonl").open()
    if json.loads(line)["id"] == top["id"]
)
data = build_data(get_engine(), [f"{y}-{y + 1}" for y in range(2013, 2026)])
r = np.full(len(data.team_ids), 1500.0)
games = draws = 0
done = set()
preds = []


def ha(stats, league, neutral):
    total, n, _, _ = stats
    mean = total[league] / max(1, n[league])
    mean = min(0.95, max(0.05, mean))
    empirical = 400 / math.log(10) * math.log(mean / (1 - mean))
    value = (c["home"] * 200 + n[league] * min(150, max(0, empirical))) / (
        200 + n[league]
    )
    return value * (c["neutral_factor"] if neutral else 1)


def outcomes(diff, d):
    e = 1 / (1 + math.exp(-diff / 400 * math.log(10)))
    draw = min(d, 1.9 * min(e, 1 - e))
    return [e - draw / 2, draw, 1 - e - draw / 2]


def enumerate_tie(first, second, conditions, nf, ns, rule):
    f = {
        pair: first[i] * w
        for i, rows in enumerate(score_shapes(conditions, nf))
        for pair, w in rows.items()
    }
    s = {
        pair: second[i] * w
        for i, rows in enumerate(score_shapes(conditions, ns))
        for pair, w in rows.items()
    }
    et = sum(
        p
        * (
            1
            if extra_time_winner(h, a, rule) == "A"
            else 0
            if extra_time_winner(h, a, rule) == "B"
            else 0.5
        )
        for (h, a), p in extra_time_distribution(s).items()
    )
    answer = 0
    for p1, w1 in f.items():
        for p2, w2 in s.items():
            winner = regulation_winner(p1, p2, rule)
            answer += w1 * w2 * (1 if winner == "A" else 0 if winner == "B" else et)
    return answer


for block in data.blocks:
    fixture = next((f for f in data.fixtures if f["cutoff"] == block.day), None)
    if fixture and block.day not in done:
        done.add(block.day)
        ps = []
        d = (draws + 25) / (games + 100)
        for t in fixture["rows"]:
            diff = r[t["a"]] - r[t["b"]]
            f = outcomes(diff + ha(fixture["ha"], 5, t["neutral_first"]), d)
            s = outcomes(-diff + ha(fixture["ha"], 5, t["neutral_second"]), d)
            ps.append(
                enumerate_tie(
                    f,
                    s,
                    fixture["conditionals"],
                    t["neutral_first"],
                    t["neutral_second"],
                    int(fixture["season"][:4]) <= 2020,
                )
            )
        preds.append(ps)
    for e in block.events:
        for team, gap in ((e.home, e.gap_home), (e.away, e.gap_away)):
            if gap:
                r[team] = 1500 + (r[team] - 1500) * (1 - c["regression"]) ** gap
        config = EloConfig(
            k_factor=c["k_domestic"] if e.stage == 0 else c["k_ucl"],
            home_advantage=ha(block.ha, e.league, e.neutral),
        )
        importance = (
            1
            if not e.stage
            else (c["ucl_group"], c["ucl_knockout"], c["ucl_finals"])[e.stage - 1]
        )
        g = max(1, min(abs(e.hg - e.ag), c["margin_cap"]))
        importance *= g / goal_multiplier(e.hg, e.ag, config)
        u = update_ratings(
            float(r[e.home]),
            float(r[e.away]),
            e.hg,
            e.ag,
            config,
            importance,
            e.neutral,
        )
        r[e.home] = u.home_after
        r[e.away] = u.away_after
        games += 1
        draws += e.hg == e.ag
error = float(np.max(np.abs(np.array(preds) - np.array(record["p"]))))
assert error < 1e-12, error
print(
    json.dumps(
        {
            "best_id": top["id"],
            "scalar_reference_max_error": error,
            "ties_checked": len(preds) * 8,
            "method": "Existing scalar update_ratings with multiplier adapter + direct goal-score enumeration",
        }
    )
)
(root / "scalar-verification.json").write_text(
    json.dumps(
        {
            "best_id": top["id"],
            "scalar_reference_max_error": error,
            "ties_checked": len(preds) * 8,
        },
        indent=2,
    )
    + "\n"
)
