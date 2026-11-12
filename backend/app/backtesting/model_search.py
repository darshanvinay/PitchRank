"""Resumable offline Elo search; production models/APIs/database are never modified.

PYTHONPATH=backend .venv/bin/python -m app.backtesting.model_search --trials 1000 --seed 20261111
"""

# Long generated Markdown tables retain their natural structure.
# ruff: noqa: E501

import argparse
import csv
import hashlib
import importlib.util
import json
import math
import time
from dataclasses import asdict, replace
from datetime import date
from pathlib import Path

import numpy as np

from app.backtesting.knockout import backtest_seasons
from app.backtesting.search_data import build_data
from app.backtesting.search_engine import SearchConfig, anchors, batch_replay, sample_config
from app.db.session import ROOT, get_engine

REVISION = "search-v1"
DEFAULT_TRAIN = tuple(f"{y}-{y + 1}" for y in range(2013, 2020))
DEFAULT_EVAL = tuple(f"{y}-{y + 1}" for y in range(2020, 2026))


def metrics(p, y):
    p = np.clip(np.asarray(p), 1e-8, 1 - 1e-8)
    y = np.asarray(y, dtype=float)
    return {
        "ties": int(p.size),
        "correct": int(np.sum((p >= 0.5) == y)),
        "accuracy": float(np.mean((p >= 0.5) == y)),
        "brier": float(np.mean((p - y) ** 2)),
        "log_loss": float(np.mean(-y * np.log(p) - (1 - y) * np.log1p(-p))),
        "confidence": float(np.mean(np.maximum(p, 1 - p))),
    }


def season_indices(data, seasons):
    indices = [i for i, f in enumerate(data.fixtures) if f["season"] in seasons]
    if len(indices) != len(seasons):
        raise ValueError("Unknown or duplicate season selection")
    return indices


def development_key(record, indices, y):
    p = np.asarray(record["p"])[indices]
    m = metrics(p, y[indices])
    losses = np.array([metrics(v, t)["log_loss"] for v, t in zip(p, y[indices], strict=True)])
    return (
        m["log_loss"] + 0.1 * float(losses.std()),
        -m["correct"],
        SearchConfig(**record["config"]).complexity,
        record["id"],
    )


def fold_select(records, data, train_seasons, eval_seasons, strategy="probability"):
    """Re-rank only resolved earlier seasons. This function never reads a future score."""
    y = np.array([[r["actual_a"] for r in f["rows"]] for f in data.fixtures], dtype=float)
    output = []
    for season in sorted(eval_seasons):
        eligible = sorted(set(train_seasons) | {s for s in eval_seasons if s < season})
        eligible = [s for s in eligible if s < season]
        if len(eligible) < 4:
            raise ValueError("At least four earlier R16 seasons required")
        validation = eligible[-3:]
        indices = season_indices(data, validation)
        cutoff = next(f["cutoff"] for f in data.fixtures if f["season"] == season)
        if any(
            max(r["available"] for r in f["rows"]) >= cutoff
            for f in data.fixtures
            if f["season"] in validation
        ):
            raise ValueError("Earlier validation labels were not yet available")
        if strategy == "probability":
            winner = min(records, key=lambda r: development_key(r, indices, y))
        elif strategy == "accuracy":
            winner = min(
                records,
                key=lambda r: (
                    -metrics(np.asarray(r["p"])[indices], y[indices])["correct"],
                    *development_key(r, indices, y),
                ),
            )
        else:
            raise ValueError("Unknown selection strategy")
        fi = season_indices(data, [season])[0]
        output.append(
            {
                "season": season,
                "selected_id": winner["id"],
                "config": winner["config"],
                "past_validation": validation,
                "p": winner["p"][fi],
                "validation_metrics": metrics(np.asarray(winner["p"])[indices], y[indices]),
                "metrics": metrics(winner["p"][fi], y[fi]),
            }
        )
    return {
        "strategy": strategy,
        "folds": output,
        "overall": metrics([f["p"] for f in output], y[season_indices(data, sorted(eval_seasons))]),
    }


def perturb(config, scale, field=None):
    fields = (field,) if field else ("k_domestic", "k_ucl", "home", "regression", "draw_strength")
    changes = {}
    for k in fields:
        value = getattr(config, k) * (1 + scale)
        if k == "regression":
            value = np.clip(value, 0, 1)
        changes[k] = float(value)
    return replace(config, **changes)


def ablations(c):
    return {
        "K": replace(c, k_domestic=20, k_ucl=20, k_gap=0, k_stage=0),
        "home": replace(c, home=65, home_mode="fixed", neutral_factor=0),
        "regression": replace(
            c,
            regression=0.25,
            regression_target="initial",
            regression_asymmetry=0,
            regression_league=0,
        ),
        "margin": replace(c, margin="log", margin_cap=99, margin_adjust=0),
        "recent": replace(
            c,
            form_weight=0,
            form_venue=False,
            form_ew=False,
            logistic_features=c.logistic_features & ~1,
        ),
        "Europe": replace(
            c,
            ucl_group=1.25,
            ucl_knockout=1.5,
            ucl_finals=1.75,
            european_weight=0,
            opponent_league=0,
            logistic_features=c.logistic_features & ~4,
        ),
        "goal_feature": replace(c, logistic_features=c.logistic_features & ~2),
        "offsets": replace(c, offsets="none", regression_league=0, opponent_league=0),
        "head": replace(
            c, head="davidson", draw_strength=0.7, logistic_rate=0.05, logistic_ridge=0.1
        ),
        "calibration": replace(c, calibration="none"),
    }


def json_write(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def load_records(path):
    if not path.exists():
        return []
    lines = path.read_text().splitlines()
    records = []
    for i, line in enumerate(lines):
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            if i != len(lines) - 1:
                raise
            # A crash during append can leave one partial final record; safely truncate it.
            path.write_text("\n".join(lines[:i]) + "\n")
    ids = [r["id"] for r in records]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate checkpoint configuration IDs")
    return records


def record_for(c, p, raw, elapsed, phase):
    return {
        "id": c.identity,
        "config": asdict(c),
        "p": p.tolist(),
        "raw": raw.tolist(),
        "seconds": elapsed,
        "phase": phase,
    }


def export_csv(output, records, data, train, evaluation, baseline):
    ti = season_indices(data, train)
    ei = season_indices(data, evaluation)
    y = np.array([[r["actual_a"] for r in f["rows"]] for f in data.fixtures], dtype=float)
    fields = [
        "id",
        "phase",
        "seconds",
        *asdict(SearchConfig()),
        "correct",
        "ties",
        "accuracy",
        "log_loss",
        "brier",
        "confidence",
        "train_correct",
        "train_log_loss",
        "changed",
        "improved",
        "regressed",
        "per_season",
    ]
    with (output / "results.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        bp = np.asarray(baseline["p"])[ei]
        by = (bp >= 0.5) == y[ei]
        for r in records:
            p = np.asarray(r["p"])
            m = metrics(p[ei], y[ei])
            tm = metrics(p[ti], y[ti])
            correct = (p[ei] >= 0.5) == y[ei]
            writer.writerow(
                {
                    "id": r["id"],
                    "phase": r["phase"],
                    "seconds": r["seconds"],
                    **r["config"],
                    **m,
                    "train_correct": tm["correct"],
                    "train_log_loss": tm["log_loss"],
                    "changed": int(np.sum((p[ei] >= 0.5) != (bp >= 0.5))),
                    "improved": int(np.sum(correct & ~by)),
                    "regressed": int(np.sum(~correct & by)),
                    "per_season": json.dumps(
                        {data.fixtures[i]["season"]: metrics(p[i], y[i]) for i in ei}
                    ),
                }
            )


def diagnostic_changes(candidate, baseline, data, evaluation):
    output = []
    for i in season_indices(data, evaluation):
        f = data.fixtures[i]
        for j, t in enumerate(f["rows"]):
            p = candidate["p"][i][j]
            bp = baseline["p"][i][j]
            if (p >= 0.5) == (bp >= 0.5):
                continue
            output.append(
                {
                    "season": f["season"],
                    "tie_id": t["tie_id"],
                    "team_a": data.names[t["team_a_id"]],
                    "team_b": data.names[t["team_b_id"]],
                    "actual": data.names[t["team_a_id"] if t["actual_a"] else t["team_b_id"]],
                    "baseline_p_a": bp,
                    "candidate_p_a": p,
                    "distance_from_50pct": abs(p - 0.5),
                    "improved": bool((p >= 0.5) == t["actual_a"]),
                }
            )
    return output


def robustness(output, records, data, train, evaluation, batch_size, deadline):
    y = np.array([[t["actual_a"] for t in f["rows"]] for f in data.fixtures], dtype=float)
    ei = season_indices(data, evaluation)
    exploratory = sorted(
        records,
        key=lambda r: (
            -metrics(np.asarray(r["p"])[ei], y[ei])["correct"],
            metrics(np.asarray(r["p"])[ei], y[ei])["log_loss"],
            r["id"],
        ),
    )[:20]
    known = {r["id"]: r for r in records}
    path = output / "diagnostics.jsonl"
    diagnostics = load_records(path)
    known.update({r["id"]: r for r in diagnostics})
    requests = []
    links = []
    for parent in exploratory:
        c = SearchConfig(**parent["config"])
        for field in (None, "k_domestic", "k_ucl", "home", "regression", "draw_strength"):
            for scale in (-0.1, -0.05, 0.05, 0.1):
                pc = perturb(c, scale, field)
                links.append(
                    {
                        "parent": c.identity,
                        "kind": "perturbation",
                        "field": field or "joint",
                        "scale": scale,
                        "id": pc.identity,
                    }
                )
                if pc.identity not in known:
                    known[pc.identity] = None
                    requests.append(pc)
        for name, ac in ablations(c).items():
            links.append(
                {"parent": c.identity, "kind": "ablation", "field": name, "id": ac.identity}
            )
            if ac.identity not in known:
                known[ac.identity] = None
                requests.append(ac)
    for start in range(0, len(requests), batch_size):
        if time.monotonic() >= deadline:
            break
        batch = requests[start : start + batch_size]
        now = time.perf_counter()
        p, raw, _ = batch_replay(data, batch, date(int(min(train)[:4]), 7, 1))
        elapsed = (time.perf_counter() - now) / len(batch)
        with path.open("a") as handle:
            for i, c in enumerate(batch):
                r = record_for(c, p[:, i], raw[:, i], elapsed, "robustness")
                diagnostics.append(r)
                known[c.identity] = r
                handle.write(json.dumps(r) + "\n")
        print(
            f"Robustness {min(start + len(batch), len(requests))}/{len(requests)} new configurations",
            flush=True,
        )
    summary = []
    for parent in exploratory:
        selected = [link for link in links if link["parent"] == parent["id"]]
        valid = [(link, known[link["id"]]) for link in selected if known.get(link["id"])]
        row = {"id": parent["id"], "complete": len(valid) == len(selected), "variants": []}
        for link, r in valid:
            row["variants"].append({**link, "metrics": metrics(np.asarray(r["p"])[ei], y[ei])})
        summary.append(row)
    json_write(output / "robustness.json", summary)
    return diagnostics, summary


def write_report(output, records, data, train, evaluation, baseline, walks, robust, complete, args):
    y = np.array([[t["actual_a"] for t in f["rows"]] for f in data.fixtures], dtype=float)
    ei = season_indices(data, evaluation)
    sorted_models = sorted(
        records,
        key=lambda r: (
            -metrics(np.asarray(r["p"])[ei], y[ei])["correct"],
            metrics(np.asarray(r["p"])[ei], y[ei])["log_loss"],
            r["id"],
        ),
    )
    early = season_indices(data, train[:-3] if len(train) > 3 else train)
    development = sorted(records, key=lambda r: development_key(r, early, y))[:20]
    top = []
    for r in sorted_models[:20]:
        top.append(
            {
                "id": r["id"],
                "config": r["config"],
                "metrics": metrics(np.asarray(r["p"])[ei], y[ei]),
                "changes": diagnostic_changes(r, baseline, data, evaluation),
            }
        )
    json_write(
        output / "top_models.json",
        {
            "selection": "Exploratory evaluation-selected; not independent evidence",
            "exploratory_top20": top,
            "development_top20": [{"id": r["id"], "config": r["config"]} for r in development],
        },
    )
    best = sorted_models[0]
    bm = metrics(np.asarray(baseline["p"])[ei], y[ei])
    m = top[0]["metrics"]
    text = f"""# PitchRank large-scale Elo search

## Recommendation and status

Production Model A was preserved. This is a retrospective study on seasons already examined in
previous PitchRank experiments. Exploratory selection on the original evaluation ties is explicitly
in-sample selection. Walk-forward selection uses only resolved earlier seasons, but does not restore
a prospectively blind benchmark. A score of 40+/48 alone is insufficient for promotion.

Search status: **{"complete" if complete else "partial; resume command below"}**.
Evaluated **{len(records)} distinct search configurations**, plus saved robustness configurations.
Method: {args.search_method}; seed {args.seed}. Optuna available: {importlib.util.find_spec("optuna") is not None}.
The implementation adds no dependency and makes no database, API, UI or production-parameter change.

## Architecture and baseline audit

Historical forecasts replay domestic + UCL games chronologically from July 2010; club IDs are shared
across competitions. Initial ratings are 1500 with no current squad values. Default K=20, H=65,
scale=400, offseason regression=25%, log margin, UCL importance 1.25/1.5/1.75. A's update is zero-sum.
Unknown kickoff times make the whole day a simultaneous batch. Every R16 forecast excludes the entire
cutoff day and freezes before the earliest first leg. The two-leg scorer retains historical away goals,
extra time and penalties. Current squad priors used by the live leaderboard are not used in this search.
The older membership-precomputing research replay is not used.

Fresh canonical baseline: **{bm["correct"]}/{bm["ties"]} ({bm["accuracy"]:.2%})**,
Brier {bm["brier"]:.6f}, log loss {bm["log_loss"]:.6f}.
The optimized contraction was checked against the original enumerator; Model A itself uses the original
backtester probabilities in artifacts, rather than replacing production mathematics.

Data audit: {json.dumps(data.audit, indent=2)}

Training seasons: {", ".join(train)}. Evaluation seasons: {", ".join(evaluation)}.
The last three available earlier seasons form each walk-forward validation fold; a minimum of four
earlier seasons is required. Each fold validates that the earlier tie outcomes resolved before cutoff.
Candidate local refinement uses only the early part of the initial training period, never the evaluation
sample. Probability calibration receives only resolved prior R16 probabilities/outcomes. Platt needs
32 ties and both classes; isotonic needs 64, with 50% shrinkage toward identity. Sparse folds use identity.
Online match-head/offset/HA learning publishes changes only after a complete kickoff batch. Features
are fixed-scale pre-match quantities; no full-data normalization or future membership is used.

## Models actually searched

- Independent domestic/UCL K, K gap/stage modifiers and UCL phase importance.
- Fixed, past-league and recent empirical home advantage; recorded neutral-venue handling.
- Initial/global/observed-domestic regression targets, strong/weak and league adjustments.
- Binary, linear, logarithmic and square-root margins; caps and rating-gap adjustment.
- Last 3/5/8/10/15/20 match residual, goal or opponent-performance features; exponential and venue
  variants; 0–50% feature blends. Features come from pre-match baseline innovations, not trophies.
- European residual features; fixed warmup-fitted or online/shrunk league offsets. Fixed offsets freeze
  before the first initial training season; no hand-entered country bonuses exist.
- Davidson, score-preserving Elo H/D/A, conditional logistic H/D/A and regularized symmetric match
  logistic heads. The learned head trains online on prior games with physical feature scaling.
- Optional past-only Platt/isotonic advancement calibration. These modify predictions, not rating updates.

These are proposed experimental rules, not proven optimal formulas. Home-strength estimates from
fractional past home results may retain schedule bias. The initial/global/league means use only
already observed clubs. League offsets condition on existing Elo and may re-use correlated information;
they do not add a second UCL result update. A different bias/variance trade-off is not automatically better.

## Baseline by season

| Season | Correct | Brier | Log loss |
|---|---:|---:|---:|
"""
    for i in ei:
        z = metrics(baseline["p"][i], y[i])
        text += f"| {data.fixtures[i]['season']} | {z['correct']}/8 | {z['brier']:.6f} | {z['log_loss']:.6f} |\n"
    text += "\n## Best exploratory model — selected on the evaluation sample\n\n"
    text += f"**{m['correct']}/{m['ties']} ({m['accuracy']:.2%})**, Brier {m['brier']:.6f}, log loss {m['log_loss']:.6f}.\n\n```json\n{json.dumps(best['config'], indent=2)}\n```\n\n"
    text += (
        "This is the maximum observed among many configurations, not out-of-sample evidence.\n\n"
    )
    text += "### Top five exploratory configurations\n\n| ID | Correct | Brier | Log loss | Key settings |\n|---|---:|---:|---:|---|\n"
    for r in top[:5]:
        z = r["metrics"]
        c = r["config"]
        text += f"| {r['id']} | {z['correct']}/{z['ties']} | {z['brier']:.6f} | {z['log_loss']:.6f} | K={c['k_domestic']}/{c['k_ucl']}, H={c['home']}, regression={c['regression']}, margin={c['margin']}, head={c['head']}, calibration={c['calibration']} |\n"
    text += "\nComplete configurations are in top_models.json; every trial and per-season score is in results.csv.\n\n### Changed exploratory picks\n\n| Season | Tie | Actual | A P(first) | Candidate P(first) | Change | Margin from 50% |\n|---|---|---|---:|---:|---|---:|\n"
    for r in top[0]["changes"]:
        text += f"| {r['season']} | {r['team_a']} – {r['team_b']} | {r['actual']} | {r['baseline_p_a']:.3%} | {r['candidate_p_a']:.3%} | {'corrected' if r['improved'] else 'new error'} | {r['distance_from_50pct']:.3%} |\n"
    text += "\n## Walk-forward — past-selected configurations\n\nTwo strategies were declared before the search. Primary ranks past validation log loss plus 0.1 times\nits season standard deviation, then accuracy and simplicity; secondary prioritizes past-validation\naccuracy before the same probability/stability ranking. The highest observed secondary strategy is\nnot silently substituted for the primary. Earlier evaluation seasons may train later folds only after\ntheir outcomes are resolved. No fold selects on its own or a future outcome.\n\n"
    for name, w in walks.items():
        z = w["overall"]
        text += f"### {name}: {z['correct']}/{z['ties']} ({z['accuracy']:.2%})\n\nBrier {z['brier']:.6f}; log loss {z['log_loss']:.6f}.\n\n| Evaluation season | Past validation seasons | Selected ID | Correct | Log loss |\n|---|---|---|---:|---:|\n"
        for f in w["folds"]:
            text += f"| {f['season']} | {', '.join(f['past_validation'])} | {f['selected_id']} | {f['metrics']['correct']}/8 | {f['metrics']['log_loss']:.6f} |\n"
    text += "\nFull past-selection configurations, probabilities and fold metrics are saved in walk_forward.json.\n\n## Robustness and ablations\n\nThe evaluation-selected top 20 receive joint and one-at-a-time ±5%/±10% perturbations of K, home,\nregression and draw strength, plus grouped parameter ablations. These diagnostics are post-selection\nexploration, not additional independent validation or an input to walk-forward selection.\n\n| Model | Diagnostics complete | Perturbed correct range | Median perturbed correct |\n|---|---|---|---|\n"
    for row in robust:
        vals = [v["metrics"]["correct"] for v in row["variants"] if v["kind"] == "perturbation"]
        text += f"| {row['id']} | {row['complete']} | {min(vals) if vals else '—'}–{max(vals) if vals else '—'} | {float(np.median(vals)) if vals else '—'} |\n"
    text += "\nDetailed perturbation/ablation metrics are in robustness.json. Leave-one-season-out and per-season\nchanges should be interpreted as diagnostics, not a new search objective. Small-margin flips, isolated\nseason gains and wide perturbation ranges are warning signs of selection noise.\n\n"
    primary = walks["probability"]["overall"]
    text += f"The primary walk-forward result changes accuracy by {100 * (primary['accuracy'] - bm['accuracy']):+.2f} percentage points, Brier by {primary['brier'] - bm['brier']:+.6f}, and log loss by {primary['log_loss'] - bm['log_loss']:+.6f}.\n\n"
    text += "Production recommendation: **retain A pending a fresh prospectively specified evaluation**.\n"
    text += "A higher exploratory score is not a promotion criterion. Even a past-only algorithm evaluated\nafter many research iterations on these same six seasons has limited independent evidence. There\nare only six seasonal clusters and 48 correlated ties; selection over thousands of models inflates\nthe exploratory maximum. Missing outside-five domestic evidence and retrospective corrections/venue\nmetadata remain limitations. Draw outcomes themselves are not averaged here: this study scores R16\nknown ties, not unconditional later tournament draws.\n\n## Rerun / resume\n\n```sh\n"
    cmd = f"PYTHONPATH=backend .venv/bin/python -m app.backtesting.model_search --trials {args.trials} --seed {args.seed} --search-method {args.search_method} --batch-size {args.batch_size} --max-seconds {args.max_seconds} --output-dir {output}"
    cmd += (
        " --training-seasons " + " ".join(train) + " --evaluation-seasons " + " ".join(evaluation)
    )
    if args.skip_robustness:
        cmd += " --skip-robustness"
    text += cmd + " --resume\n```\n\n"
    text += "Configuration/data/source-code manifests are checked before resume. A completed trial is never\nreplayed unnecessarily; a partially appended final record is repaired. Runtime caps stop between\nbatches, saving all completed results. Increase --max-seconds when resuming if necessary. Custom\n--training-seasons and --evaluation-seasons accept space-separated YYYY-YYYY season strings.\n"
    (output / "report.md").write_text(text)


def analysis_extras(output, records, diagnostics, data, train, evaluation, baseline, walks):
    """Post-selection diagnostics never enter the candidate pool or fold selection."""
    y = np.array([[t["actual_a"] for t in f["rows"]] for f in data.fixtures], dtype=float)
    ei = season_indices(data, evaluation)
    vi = season_indices(data, train[-3:])
    all_records = {r["id"]: r for r in records + diagnostics}
    ordered = sorted(
        all_records.values(),
        key=lambda r: (
            -metrics(np.asarray(r["p"])[ei], y[ei])["correct"],
            metrics(np.asarray(r["p"])[ei], y[ei])["log_loss"],
            r["id"],
        ),
    )
    top = [
        {
            "id": r["id"],
            "phase": r["phase"],
            "config": r["config"],
            "metrics": metrics(np.asarray(r["p"])[ei], y[ei]),
            "changes": diagnostic_changes(r, baseline, data, evaluation),
        }
        for r in ordered[:5]
    ]
    basep = np.asarray(baseline["p"])[ei]
    uncertainty = {}
    for kind, walk in walks.items():
        p = np.array([f["p"] for f in walk["folds"]])
        losses = -y[ei] * np.log(p) - (1 - y[ei]) * np.log1p(-p)
        base_losses = -y[ei] * np.log(basep) - (1 - y[ei]) * np.log1p(-basep)
        diff = (losses - base_losses).mean(axis=1)
        n = len(diff)
        critical = {2: 12.706, 3: 4.303, 4: 3.182, 5: 2.776, 6: 2.571, 7: 2.447, 8: 2.365}.get(
            n, 1.96
        )
        se = float(diff.std(ddof=1) / math.sqrt(n)) if n > 1 else 0
        good = (p >= 0.5) == y[ei]
        base_good = (basep >= 0.5) == y[ei]
        gains = int(np.sum(good & ~base_good))
        losses_n = int(np.sum(~good & base_good))
        discord = gains + losses_n
        correct = int(good.sum())
        total = good.size
        z = 1.96
        rate = correct / total
        center = (rate + z * z / (2 * total)) / (1 + z * z / total)
        half = (
            z
            * math.sqrt(rate * (1 - rate) / total + z * z / (4 * total * total))
            / (1 + z * z / total)
        )
        uncertainty[kind] = {
            "accuracy_wilson_95": [center - half, center + half],
            "paired_log_loss_delta": float(diff.mean()),
            "paired_season_approx_95": [
                float(diff.mean() - critical * se),
                float(diff.mean() + critical * se),
            ],
            "gains": gains,
            "losses": losses_n,
            "paired_accuracy_exact_p": min(
                1,
                2
                * sum(math.comb(discord, i) for i in range(min(gains, losses_n) + 1))
                / 2**discord,
            ),
        }
    robustness_rows = (
        json.loads((output / "robustness.json").read_text())
        if (output / "robustness.json").exists()
        else []
    )
    ablations_by = {}
    for parent in robustness_rows:
        r = all_records[parent["id"]]
        for v in parent["variants"]:
            if v["kind"] != "ablation" or v["id"] == parent["id"]:
                continue
            child = all_records[v["id"]]
            entry = ablations_by.setdefault(v["field"], [])
            entry.append(
                {
                    "validation_delta": metrics(np.asarray(child["p"])[vi], y[vi])["log_loss"]
                    - metrics(np.asarray(r["p"])[vi], y[vi])["log_loss"],
                    "evaluation_delta": v["metrics"]["log_loss"]
                    - metrics(np.asarray(r["p"])[ei], y[ei])["log_loss"],
                }
            )
    insights = {
        k: {
            "active_parents": len(v),
            "median_validation_ablation_loss": float(np.median([q["validation_delta"] for q in v])),
            "median_evaluation_ablation_loss": float(np.median([q["evaluation_delta"] for q in v])),
        }
        for k, v in ablations_by.items()
    }
    json_write(
        output / "analysis.json",
        {
            "all_trials_top5": top,
            "walk_forward_uncertainty": uncertainty,
            "ablation_insights": insights,
            "search_trials_ge40": sum(
                metrics(np.asarray(r["p"])[ei], y[ei])["correct"] >= 40 for r in records
            ),
        },
    )
    top_file = json.loads((output / "top_models.json").read_text())
    top_file["all_trials_top5_including_diagnostics"] = top
    json_write(output / "top_models.json", top_file)
    text = "\n## Additional statistical and robustness analysis\n\n"
    text += f"The search pool contains {len(records)} configurations; diagnostics add {len(diagnostics)} distinct configurations. Diagnostics are excluded from every walk-forward selection, since their proposal uses evaluation-selected parents. Execution time per trial is amortized batch wall time; cache and reporting time are in summary.json.\n\n"
    text += f"Highest exploratory score including diagnostics: **{top[0]['metrics']['correct']}/{top[0]['metrics']['ties']}**, configuration {top[0]['id']} ({top[0]['phase']}). This is further hindsight-selected evidence. Full settings and changed ties are in top_models.json/analysis.json.\n\n"
    text += (
        "| All-trial top five ID | Phase | Correct | Brier | Log loss |\n|---|---|---:|---:|---:|\n"
    )
    for r in top:
        m = r["metrics"]
        text += f"| {r['id']} | {r['phase']} | {m['correct']}/{m['ties']} | {m['brier']:.6f} | {m['log_loss']:.6f} |\n"
    text += "\n### Primary/secondary uncertainty\n\n| Strategy | Accuracy Wilson 95% | Paired log-loss delta [approx 95%] | Corrections/new errors | Paired accuracy exact p |\n|---|---|---|---|---:|\n"
    for k, u in uncertainty.items():
        lo, hi = u["accuracy_wilson_95"]
        dl, dh = u["paired_season_approx_95"]
        text += f"| {k} | {lo:.1%}–{hi:.1%} | {u['paired_log_loss_delta']:+.6f} [{dl:+.6f}, {dh:+.6f}] | {u['gains']}/{u['losses']} | {u['paired_accuracy_exact_p']:.4f} |\n"
    text += "\nWilson and exact-discordance intervals/tests assume independent ties, which repeated clubs violate. Paired loss intervals use seasonal clusters and a t critical value; six clusters give only descriptive uncertainty. Multiple searches and two declared strategies add selection uncertainty. These are not claims of statistically proven superiority.\n\n### Best-model seasonal stability\n\n| Season | A correct | Candidate correct | Difference |\n|---|---:|---:|---:|\n"
    best = ordered[0]
    net = []
    for i in ei:
        a = metrics(baseline["p"][i], y[i])
        b = metrics(best["p"][i], y[i])
        net.append(b["correct"] - a["correct"])
        text += f"| {data.fixtures[i]['season']} | {a['correct']}/8 | {b['correct']}/8 | {net[-1]:+d} |\n"
    text += f"\nNet gains by season: {net}. Leaving out the single strongest gain season removes {max(net)} of the net {sum(net)} extra correct picks. This check is descriptive and does not constitute a new independent sample.\n\n"
    text += "### Paired parameter ablations\n\nPositive loss delta means removing that parameter group worsens predictions; negative means the ablation helps. Parents were selected using evaluation outcomes, so this diagnoses those parents rather than establishing a general causal parameter effect.\n\n| Removed group | Active parents | Median validation log-loss delta | Median evaluation log-loss delta |\n|---|---:|---:|---:|\n"
    for k, v in insights.items():
        text += f"| {k} | {v['active_parents']} | {v['median_validation_ablation_loss']:+.6f} | {v['median_evaluation_ablation_loss']:+.6f} |\n"
    with (output / "report.md").open("a") as handle:
        handle.write(text)
    return top


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=20261111)
    parser.add_argument("--search-method", choices=("random", "hybrid", "tpe"), default="hybrid")
    parser.add_argument("--training-seasons", nargs="+", default=DEFAULT_TRAIN)
    parser.add_argument("--evaluation-seasons", nargs="+", default=DEFAULT_EVAL)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments")
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--max-seconds", type=float, default=900)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--skip-robustness", action="store_true")
    args = parser.parse_args()
    if args.trials < 1 or args.batch_size < 1 or args.max_seconds <= 0:
        parser.error("Positive trial/batch/time limits required")
    train = sorted(args.training_seasons)
    evaluation = sorted(args.evaluation_seasons)
    if (
        len(set(train)) != len(train)
        or len(set(evaluation)) != len(evaluation)
        or max(train) >= min(evaluation)
    ):
        parser.error("Distinct chronological training seasons must precede evaluation")
    if len(train) < 4:
        parser.error("At least four training seasons required")
    if args.search_method == "tpe" and importlib.util.find_spec("optuna") is None:
        parser.error(
            "Optuna is not installed. Use hybrid: seeded random search + local refinement."
        )
    if args.search_method == "tpe":
        parser.error("Use hybrid in this dependency-free installation; no Optuna backend is active")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=True)
    prior_seconds = 0.0
    if args.resume and (output / "timing.json").exists():
        prior_seconds = json.loads((output / "timing.json").read_text())["cumulative_seconds"]
    engine = get_engine()
    database = Path(engine.url.database)
    signature = hashlib.sha256(database.read_bytes()).hexdigest()
    started = time.monotonic()
    deadline = started + args.max_seconds
    print("Caching immutable match data...", flush=True)
    data = build_data(engine, train + evaluation)
    canonical = backtest_seasons(engine, evaluation)
    print("Canonical baseline " + json.dumps(canonical["overall"]), flush=True)
    canonical_by = {
        s["season"]: {r["tie_id"]: r["p_a"] for r in s["predictions"]} for s in canonical["seasons"]
    }
    source_hash = hashlib.sha256(
        b"".join(
            (Path(__file__).with_name(p)).read_bytes()
            for p in ("model_search.py", "search_engine.py", "search_data.py")
        )
    ).hexdigest()
    manifest = {
        "revision": REVISION,
        "seed": args.seed,
        "method": args.search_method,
        "trials": args.trials,
        "training": train,
        "evaluation": evaluation,
        "data_hash": data.signature,
        "source_hash": source_hash,
        "batch_size": args.batch_size,
    }
    if (output / "manifest.json").exists():
        if not args.resume:
            parser.error("Output already has a run; pass --resume or choose another folder")
        if json.loads((output / "manifest.json").read_text()) != manifest:
            parser.error("Resume manifest differs")
    else:
        json_write(output / "manifest.json", manifest)
    path = output / "trials.jsonl"
    records = load_records(path)
    known = {r["id"]: r for r in records}
    rng = np.random.default_rng(args.seed)
    pool = []
    pool_ids = set()

    def add(c):
        if c.identity not in pool_ids:
            pool.append(c)
            pool_ids.add(c.identity)

    for c in anchors()[: args.trials]:
        add(c)
    broad = (
        args.trials if args.search_method == "random" else max(len(pool), int(args.trials * 0.8))
    )
    while len(pool) < broad:
        add(sample_config(rng))
    early = season_indices(data, train[:-3])
    y = np.array([[r["actual_a"] for r in f["rows"]] for f in data.fixtures], dtype=float)
    for phase, target in [("broad", broad), ("local", args.trials)]:
        if phase == "local" and len(pool) < target:
            available = [r for r in records if r["phase"] == "broad"]
            if len(available) < broad:
                break
            centers = sorted(available, key=lambda r: development_key(r, early, y))[:20]
            fields = [
                "k_domestic",
                "k_ucl",
                "home",
                "regression",
                "draw_strength",
                "ucl_group",
                "ucl_knockout",
                "ucl_finals",
            ]
            attempts = 0
            while len(pool) < target:
                c = SearchConfig(**centers[int(rng.integers(len(centers)))]["config"])
                field = fields[int(rng.integers(len(fields)))]
                value = getattr(c, field)
                factor = float(rng.uniform(0.85, 1.15))
                value = (
                    float(np.clip(value * factor, 0, 1))
                    if field == "regression"
                    else float(np.clip(value * factor, 0, 180))
                    if field == "home"
                    else value * factor
                )
                add(replace(c, **{field: value}))
                attempts += 1
                if attempts > args.trials * 100:
                    add(sample_config(rng))
        pending = [c for c in pool[:target] if c.identity not in known]
        for start in range(0, len(pending), args.batch_size):
            if time.monotonic() >= deadline:
                break
            batch = pending[start : start + args.batch_size]
            now = time.perf_counter()
            p, raw, _ = batch_replay(data, batch, date(int(min(train)[:4]), 7, 1))
            elapsed = time.perf_counter() - now
            with path.open("a") as handle:
                for j, c in enumerate(batch):
                    # Preserve the original baseline values, and verify optimized baseline agreement.
                    if c == SearchConfig():
                        for i, f in enumerate(data.fixtures):
                            if f["season"] in canonical_by:
                                expected = np.array(
                                    [canonical_by[f["season"]][t["tie_id"]] for t in f["rows"]]
                                )
                                if not np.allclose(p[i, j], expected, atol=1e-12, rtol=0):
                                    raise RuntimeError("Fast baseline mismatch")
                                p[i, j] = expected
                    r = record_for(c, p[:, j], raw[:, j], elapsed / len(batch), phase)
                    records.append(r)
                    known[c.identity] = r
                    handle.write(json.dumps(r) + "\n")
            remain = args.trials - len(records)
            eta = elapsed / len(batch) * remain
            print(
                f"{len(records)}/{args.trials} trials; batch {elapsed:.2f}s; ETA {eta:.1f}s",
                flush=True,
            )
            base = next(r for r in records if r["id"] == SearchConfig().identity)
            export_csv(output, records, data, train, evaluation, base)
        if len(records) < broad or time.monotonic() >= deadline:
            break
    baseline = known.get(SearchConfig().identity)
    if not baseline:
        raise RuntimeError("Time budget ended before baseline completed; resume")
    walks = {
        kind: fold_select(records, data, train, evaluation, kind)
        for kind in ("probability", "accuracy")
    }
    json_write(output / "walk_forward.json", walks)
    diagnostics = []
    robust = []
    if not args.skip_robustness:
        diagnostics, robust = robustness(
            output, records, data, train, evaluation, args.batch_size, deadline
        )
    export_csv(output, records + diagnostics, data, train, evaluation, baseline)
    complete = len(records) == args.trials and (
        args.skip_robustness or all(r["complete"] for r in robust)
    )
    write_report(output, records, data, train, evaluation, baseline, walks, robust, complete, args)
    all_top = analysis_extras(
        output, records, diagnostics, data, train, evaluation, baseline, walks
    )
    if signature != hashlib.sha256(database.read_bytes()).hexdigest():
        raise RuntimeError("Database changed; results invalid")
    ei = season_indices(data, evaluation)
    best = max(metrics(np.asarray(r["p"])[ei], y[ei])["correct"] for r in records)
    summary = {
        "complete": complete,
        "search_trials": len(records),
        "diagnostic_trials": len(diagnostics),
        "exploratory_best_correct": best,
        "exploratory_best_including_diagnostics": all_top[0]["metrics"]["correct"],
        "ties": 8 * len(evaluation),
        "walk_forward": {k: w["overall"] for k, w in walks.items()},
        "seconds": prior_seconds + time.monotonic() - started,
        "last_invocation_seconds": time.monotonic() - started,
        "database_sha256": signature,
    }
    json_write(output / "timing.json", {"cumulative_seconds": summary["seconds"]})
    json_write(output / "summary.json", summary)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    main()
