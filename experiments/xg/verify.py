"""Independent scalar check, matched goals-only ablation, and production-preservation audit."""

import hashlib
import json
import math
import sqlite3
from datetime import UTC, date, datetime

import numpy as np
from app.backtesting.knockout import backtest_seasons
from app.backtesting.model_search import metrics, season_indices
from app.backtesting.search_data import build_data, contract
from app.backtesting.search_engine import SearchConfig, batch_replay
from app.backtesting.xg_engine import XGConfig, batch_xg
from app.backtesting.xg_search import EVAL, TRAIN
from app.core.elo import EloConfig
from app.db.models import MatchXG
from app.db.session import ROOT, get_engine
from app.elo.engine import update_ratings
from app.predictions.model import PredictionConfig, probabilities
from sqlalchemy import select
from sqlalchemy.orm import Session


def poisson(home, away):
    h = [math.exp(-min(8, max(0, home)))]
    a = [math.exp(-min(8, max(0, away)))]
    for i in range(1, 41):
        h.append(h[-1] * min(8, max(0, home)) / i)
        a.append(a[-1] * min(8, max(0, away)) / i)
    p = [
        sum(hg * ag for hi, hg in enumerate(h) for ai, ag in enumerate(a) if hi > ai),
        sum(hg * ag for hg, ag in zip(h, a, strict=True)),
        sum(hg * ag for hi, hg in enumerate(h) for ai, ag in enumerate(a) if hi < ai),
    ]
    return np.array(p) / sum(p)


def scalar_best(data, observations, config, baseline):
    """Independent loops use production scalar updates + an explicit xG target correction."""
    if config.family != "ensemble":
        raise ValueError(
            "This scalar verifier supports the recorded best ensemble profile only"
        )
    ratings = dict.fromkeys(range(len(data.team_ids)), 1500.0)
    attack = dict.fromkeys(ratings, 0.0)
    defence = dict.fromkeys(ratings, 0.0)
    history = {t: [] for t in ratings}
    p = np.zeros_like(baseline)
    cutoffs = {f["cutoff"]: i for i, f in enumerate(data.fixtures)}
    emitted = set()
    soft = {
        mid: (q[0] + q[1] / 2)
        for mid, (h, a) in observations.items()
        if (q := poisson(h, a)) is not None
    }
    for block in data.blocks:
        if block.day in cutoffs and block.day not in emitted:
            emitted.add(block.day)
            fi = cutoffs[block.day]
            for ti, tie in enumerate(data.fixtures[fi]["rows"]):
                h, a = tie["a"], tie["b"]
                if any(
                    len(history[t]) < 5 or (block.day - history[t][-1]).days > 90
                    for t in (h, a)
                ):
                    p[fi, ti] = baseline[fi, ti]
                    continue
                first, second = [], []
                for home, away, neutral, target in (
                    (h, a, tie["neutral_first"], first),
                    (a, h, tie["neutral_second"], second),
                ):
                    ec = EloConfig(
                        k_factor=config.k, home_advantage=0 if neutral else 65
                    )
                    target.append(
                        probabilities(
                            ratings[home], ratings[away], PredictionConfig(elo=ec)
                        )
                    )
                    adv = 0 if neutral else config.home_log / 2
                    lh = config.prior_goals * math.exp(
                        max(-2, min(2, attack[home] - defence[away] + adv))
                    )
                    la = config.prior_goals * math.exp(
                        max(-2, min(2, attack[away] - defence[home] - adv))
                    )
                    target.append(poisson(lh, la))
                ep = float(contract(first[0], second[0], tie["tensor"]))
                ap = float(contract(first[1], second[1], tie["tensor"]))
                p[fi, ti] = (1 - config.blend) * baseline[fi, ti] + config.blend * (
                    ep + ap
                ) / 2
        for e in block.events:
            for t, gap in ((e.home, e.gap_home), (e.away, e.gap_away)):
                f = (1 - config.regression) ** gap
                ratings[t] = 1500 + (ratings[t] - 1500) * f
                attack[t] *= f
                defence[t] *= f
            importance = (1, 1.25, 1.5, 1.75)[e.stage]
            u = update_ratings(
                ratings[e.home],
                ratings[e.away],
                e.hg,
                e.ag,
                EloConfig(k_factor=config.k),
                importance,
                e.neutral,
            )
            correction = 0
            if e.mid in observations:
                correction = (
                    config.k
                    * importance
                    * u.multiplier
                    * config.xg_share
                    * (soft[e.mid] - u.actual_home)
                )
            ratings[e.home] = u.home_after + correction
            ratings[e.away] = u.away_after - correction
            if e.mid in observations:
                xh, xa = observations[e.mid]
                adv = 0 if e.neutral else config.home_log / 2
                lh = config.prior_goals * math.exp(
                    max(-2, min(2, attack[e.home] - defence[e.away] + adv))
                )
                la = config.prior_goals * math.exp(
                    max(-2, min(2, attack[e.away] - defence[e.home] - adv))
                )
                dh, da = (
                    config.learning_rate * (xh - lh) / (1 + lh),
                    config.learning_rate * (xa - la) / (1 + la),
                )
                for bank, t, delta in (
                    (attack, e.home, dh),
                    (defence, e.away, -dh),
                    (attack, e.away, da),
                    (defence, e.home, -da),
                ):
                    bank[t] = max(-1.5, min(1.5, bank[t] + delta))
                history[e.home].append(block.day)
                history[e.away].append(block.day)
    return p


def main():
    out = ROOT / "experiments/xg"
    engine = get_engine()
    data = build_data(engine, TRAIN + EVAL)
    with Session(engine) as session:
        obs = {
            x.match_id: (x.home_xg, x.away_xg) for x in session.scalars(select(MatchXG))
        }
    baseline = json.loads((out / "baseline-reference.json").read_text())
    a = np.array(baseline["A"])
    ix = season_indices(data, EVAL)
    original = backtest_seasons(engine, list(EVAL))
    by = {
        f["season"]: {p["tie_id"]: p["p_a"] for p in f["predictions"]}
        for f in original["seasons"]
    }
    expected = np.array(
        [
            [by[f["season"]][r["tie_id"]] for r in f["rows"]]
            for f in data.fixtures
            if f["season"] in EVAL
        ]
    )
    assert np.allclose(expected, a[ix], atol=1e-12, rtol=0)
    best = json.loads((out / "top-models.json").read_text())[0]
    scalar = scalar_best(data, obs, XGConfig(**best["config"]), a)
    scalar_error = float(np.max(np.abs(scalar - np.array(best["p"]))))
    assert scalar_error < 1e-12
    folds = json.loads((out / "walk-forward.json").read_text())["probability"]["folds"]
    configs = [XGConfig(**f["config"]) for f in folds]
    pp, _, rr = batch_replay(data, [SearchConfig()], date(2013, 7, 1))
    # Matched raw-goal control: same fixture availability, selected configurations and
    # forecasting code. It is NOT a substitute data source or a freshly tuned goal model.
    goalobs = {
        e.mid: (float(e.hg), float(e.ag))
        for b in data.blocks
        for e in b.events
        if e.mid in obs
    }
    goals = batch_xg(data, goalobs, configs, pp[:, 0, :], rr[:, 0, :])
    selected = np.array(
        [
            goals[season_indices(data, [f["season"]])[0], ci, :]
            for ci, f in enumerate(folds)
        ]
    )
    y = np.array(
        [[r["actual_a"] for r in f["rows"]] for f in data.fixtures], dtype=float
    )
    controls = {
        "description": "Same xG-selected fold configs and fixture availability; replace xG with goals only for this diagnostic",
        "goals_only": metrics(selected, y[ix]),
        "xg": metrics([f["p"] for f in folds], y[ix]),
    }
    (out / "goals-control.json").write_text(json.dumps(controls, indent=2) + "\n")
    before = json.loads((out / "production-before.json").read_text())
    c = sqlite3.connect(ROOT / "data/pitchrank.sqlite3")
    after = {
        t: hashlib.sha256(
            repr(
                c.execute('SELECT * FROM "' + t + '" ORDER BY rowid').fetchall()
            ).encode()
        ).hexdigest()
        for t in before
    }
    assert before == after
    columns = c.execute("SELECT COUNT(*) FROM match_xg").fetchone()[0]
    provenance = {
        "retrieved_on": "2026-11-12",
        "asset_id": 399247157,
        "asset_updated_at": "2026-04-18T08:01:32Z",
        "archive_url": baseline.get(
            "archive_url",
            "https://github.com/peteowen1/pannadata/releases/download/understat-latest/understat_metadata.parquet",
        ),
        "archive_sha256": hashlib.sha256(
            (ROOT / "data/raw/understat/metadata.parquet").read_bytes()
        ).hexdigest(),
        "independent_archive_sha256": hashlib.sha256(
            (ROOT / "data/raw/understat/archive.zip").read_bytes()
        ).hexdigest(),
        "direct_understat_status": "Maintenance HTML returned for EPL/2020 page and EPL + La_Liga getLeagueData endpoints",
        "archived_data_is_retrospective": True,
        "original_publication_timestamps_available": False,
    }
    (out / "provenance.json").write_text(json.dumps(provenance, indent=2) + "\n")
    verification = {
        "verified_at": datetime.now(UTC).isoformat(),
        "existing_tables_unchanged": before == after,
        "table_hashes": after,
        "xg_rows": columns,
        "canonical_baseline": original["overall"],
        "baseline_max_abs_error": float(np.max(np.abs(expected - a[ix]))),
        "scalar_best_ties": int(a.size),
        "scalar_best_max_abs_error": scalar_error,
        "goals_control": controls,
    }
    (out / "verification.json").write_text(json.dumps(verification, indent=2) + "\n")
    print(json.dumps(verification, indent=2))


if __name__ == "__main__":
    main()
