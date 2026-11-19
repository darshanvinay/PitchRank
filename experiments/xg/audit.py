"""Targeted sensitivity replay of frozen configurations."""

import json
from dataclasses import replace
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.model_search import metrics
from app.backtesting.search_data import build_data
from app.backtesting.search_engine import SearchConfig, batch_replay
from app.backtesting.xg_engine import XGConfig, batch_xg, snapshots
from app.backtesting.xg_search import EVAL, TRAIN
from app.db.models import MatchXG
from app.db.session import get_engine

out = Path(__file__).parent
engine = get_engine()
data = build_data(engine, TRAIN + EVAL)
with Session(engine) as session:
    observations = {
        x.match_id: (x.home_xg, x.away_xg) for x in session.scalars(select(MatchXG))
    }
base, _, ratings = batch_replay(data, [SearchConfig()], date(2013, 7, 1))
base, ratings = base[:, 0], ratings[:, 0]
saved = json.loads((out / "top-models.json").read_text())[0]
best = XGConfig(**saved["config"])
variants = {
    "frozen": best,
    "Elo leg only": replace(best, family="xg_elo"),
    "attack and defence only": replace(best, family="attack_defence"),
    "zero Elo xG share": replace(best, xg_share=0),
    "half Elo xG share": replace(best, xg_share=0.5),
    "K 20": replace(best, k=20),
    "25% offseason regression": replace(best, regression=0.25),
    "attack learning rate .05": replace(best, learning_rate=0.05),
    "goal prior 1.35": replace(best, prior_goals=1.35),
    "home log effect zero": replace(best, home_log=0),
    "50% baseline blend": replace(best, blend=0.5),
}
p = batch_xg(data, observations, list(variants.values()), base, ratings)
assert np.allclose(p[:, 0], saved["p"], atol=1e-12, rtol=0)
walk = json.loads((out / "walk-forward.json").read_text())["probability"]["folds"]
cache = snapshots(data, observations)
scores = {name: [] for name in ["Model A", *variants]}
rows = []
for i, fixture in enumerate(data.fixtures):
    if fixture["season"] not in EVAL:
        continue
    fold = next(f for f in walk if f["season"] == fixture["season"])
    for j, tie in enumerate(fixture["rows"]):
        xg = []
        for team in (tie["a"], tie["b"]):
            entries = cache[fixture["cutoff"]].get(team, [])
            xg.append(
                dict(
                    club=data.names[data.team_ids[team]],
                    count=len(entries),
                    latest=str(entries[-1][0]) if entries else None,
                    age=(fixture["cutoff"] - entries[-1][0]).days if entries else None,
                )
            )
        fallback = any(x["count"] < 5 or x["age"] > 90 for x in xg)
        rows.append(
            dict(
                season=fixture["season"],
                cutoff=str(fixture["cutoff"]),
                clubs=xg,
                fallback=fallback,
                actual_a=tie["actual_a"],
                baseline=float(base[i, j]),
                frozen=float(p[i, 0, j]),
                elo=float(p[i, 1, j]),
                attack=float(p[i, 2, j]),
                walk=fold["p"][j],
            )
        )
        for name, prob in zip(scores, [base[i, j], *p[i, :, j]], strict=True):
            scores[name].append((float(prob), tie["actual_a"]))
result = {"ablation": {k: metrics(*zip(*v)) for k, v in scores.items()}, "ties": rows}
(out / "targeted-audit.json").write_text(json.dumps(result, indent=2) + "\n")
