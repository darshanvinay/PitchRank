"""Seeded xG search. No production prediction/model updates; existing xG table is read-only."""

# Generated Markdown tables intentionally retain their natural line lengths.
# ruff: noqa: E501

import argparse
import csv
import hashlib
import json
import time
from dataclasses import asdict
from datetime import date
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.model_search import fold_select, metrics, season_indices
from app.backtesting.search_data import build_data
from app.backtesting.search_engine import SearchConfig, batch_replay
from app.backtesting.xg_engine import batch_xg, sample_configs, snapshots, xg_scores
from app.db.models import MatchXG
from app.db.session import ROOT, get_engine

TRAIN = tuple(f"{y}-{y + 1}" for y in range(2015, 2020))
EVAL = tuple(f"{y}-{y + 1}" for y in range(2020, 2026))


def changes(data, p, baseline, seasons=EVAL):
    rows = []
    for i, f in enumerate(data.fixtures):
        if f["season"] not in seasons:
            continue
        for j, t in enumerate(f["rows"]):
            if (p[i, j] >= 0.5) == (baseline[i, j] >= 0.5):
                continue
            rows.append(
                dict(
                    season=f["season"],
                    tie_id=t["tie_id"],
                    team_a=data.names[t["team_a_id"]],
                    team_b=data.names[t["team_b_id"]],
                    actual=data.names[t["team_a_id"] if t["actual_a"] else t["team_b_id"]],
                    baseline_p_a=float(baseline[i, j]),
                    candidate_p_a=float(p[i, j]),
                    effect="corrected" if (p[i, j] >= 0.5) == t["actual_a"] else "new_error",
                )
            )
    return rows


def select_walk_forward(records, data, strategy):
    """Reuse the existing fold selector with xG configuration complexity excluded.

    Mapping a record to a fixed empty SearchConfig only affects the complexity tie-break;
    selected IDs retain the real xG configuration in the exported fold report.
    """
    selection = [dict(r, config={}) for r in records]
    output = fold_select(selection, data, TRAIN, EVAL, strategy)
    lookup = {r["id"]: r["config"] for r in records}
    for fold in output["folds"]:
        fold["config"] = lookup[fold["selected_id"]]
    return output


def uncertainty(p, baseline, y):
    p, baseline, y = map(np.asarray, (p, baseline, y))

    def loss(q):
        return -y * np.log(q) - (1 - y) * np.log1p(-q)

    delta = (loss(p) - loss(baseline)).mean(axis=1)
    # Six seasonal clusters: t(5), descriptive interval, not independent-tie significance.
    mean = float(delta.mean())
    se = float(delta.std(ddof=1) / np.sqrt(len(delta)))
    k = int(((p >= 0.5) == y).sum())
    n = int(y.size)
    z = 1.96
    center = (k / n + z * z / (2 * n)) / (1 + z * z / n)
    radius = z * np.sqrt(k / n * (1 - k / n) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return dict(
        accuracy_wilson95=[float(center - radius), float(center + radius)],
        paired_log_loss_delta=mean,
        paired_log_loss_seasonal95=[mean - 2.571 * se, mean + 2.571 * se],
    )


def report(output, summary, best, data, base, reference, folds):
    lines = [
        "# PitchRank: historical Understat xG experiment",
        "",
        "**Recommendation: retain production Model A pending genuinely new prospective matches.**",
        "All 48 evaluation ties have been examined previously. Walk-forward selection uses only earlier",
        "resolved seasons, but this is a retrospective re-evaluation, not an untouched test set.",
        "The fixed 42/48 model is an evaluation-selected comparator only; it cannot enter fold selection.",
        "",
        "## Measured results",
        "",
        "| Model/protocol | Correct | Accuracy | Brier | Log loss |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, m in summary["comparisons"].items():
        lines.append(
            f"| {name} | {m['correct']}/{m['ties']} | {m['accuracy']:.2%} | {m['brier']:.6f} | {m['log_loss']:.6f} |"
        )
    lines += [
        "",
        f"Tested **{summary['trials']} unique xG configurations**, seed {summary['seed']}.",
        "Search is fixed seeded random sampling, not adapted using evaluation labels.",
        "",
        "## Best exploratory xG model",
        "",
        "```json",
        json.dumps(best["config"], indent=2),
        "```",
        "",
        "This configuration was selected using the original 48 ties. Its historical score is exploratory.",
        "",
        "| Season | Tie | Actual advancing team | A P(team A) | xG P(team A) | Change |",
        "|---|---|---|---:|---:|---|",
    ]
    for r in summary["best_changes"]:
        lines.append(
            f"| {r['season']} | {r['team_a']} – {r['team_b']} | {r['actual']} | {r['baseline_p_a']:.3%} | {r['candidate_p_a']:.3%} | {r['effect']} |"
        )
    lines += [
        "",
        "## Family comparisons",
        "",
        "| Family | Exploratory correct | Log loss | Walk-forward correct | Walk-forward log loss |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, f in summary["families"].items():
        lines.append(
            f"| {name} | {f['exploratory']['correct']}/48 | {f['exploratory']['log_loss']:.6f} | {f['walk_forward']['correct']}/48 | {f['walk_forward']['log_loss']:.6f} |"
        )
    lines += [
        "",
        "## Walk-forward methodology",
        "",
        "Initial xG development/validation seasons: 2015/16–2019/20; evaluation: 2020/21–2025/26.",
        "For each evaluation fold select among the fixed candidate pool and Model A using only the last",
        "three completed earlier R16 seasons. Primary objective: mean log loss + 0.1 × seasonal log-loss",
        "standard deviation; accuracy breaks ties. A separately declared accuracy-first strategy is secondary.",
        "Four or more earlier seasons are required. Earlier evaluation seasons become available only after",
        "their ties resolve. Neither the 42/48 reference nor evaluation-selected perturbations are eligible.",
        "All teams are forecast before the first R16 match day, stricter than forecasting separately before each tie.",
        "Ratings, xG features and score-shape distributions are frozen at that cutoff; both legs use those ratings.",
        "The existing away-goals/extra-time/penalty resolution and past-only conditional goal shapes are reused.",
        "",
        "| Strategy | Season | Selected ID | Correct | Log loss |",
        "|---|---|---|---:|---:|",
    ]
    for strategy, fd in folds.items():
        for f in fd["folds"]:
            m = f["metrics"]
            lines.append(
                f"| {strategy} | {f['season']} | {f['selected_id']} | {m['correct']}/8 | {m['log_loss']:.6f} |"
            )
    lines += [
        "",
        "## Uncertainty",
        "",
        "```json",
        json.dumps(summary["uncertainty"], indent=2),
        "```",
        "Wilson intervals treat ties as independent, which repeated clubs violate. Paired loss intervals",
        "cluster by season, with only six clusters. Many candidate tests and previously examined seasons",
        "add selection uncertainty; nominal intervals do not account for all researcher choices.",
        "",
        "## Models and interpretation",
        "",
        "- **Differential:** exponentially weighted domestic-season xG for minus xG against, shrunk by",
        "  zero-differential pseudo-games. Add scale × the difference of the two club features to Model A Elo difference.",
        "- **Recent:** the same feature using the last 3/5/8/10/15/20/40 xG matches within 365 days.",
        "- **xG Elo:** use Sx = P(Poisson(xGh)>Poisson(xGa)) + 0.5P(draw); blend Sx with realized S.",
        "  Apply existing chronological K × importance × goal-margin × (blended S − E) updates.",
        "  K, xG share and offseason regression are experimental. UCL and other missing-xG matches",
        "  use actual results; all clubs start at 1500 without current squad-value priors.",
        "- **Attack/defence:** log expected xG = log(prior goal rate) + attack_home − defence_away + home_log/2",
        "  (away sign reversed). Online quasi-Poisson residual updates train separate attack and defence",
        "  strengths only after observing each match; offseason regression shrinks toward zero.",
        "  Predicted Poisson H/D/A feed the existing two-leg conditional-score machinery.",
        "- **Ensemble:** average xG-Elo and attack/defence advancement probabilities; blend that component",
        "  with A. All families test probability blends of 10/25/50/75/100% xG weight.",
        "- Fallback to A for a tie if either club has fewer than five prior xG matches or its latest xG is",
        "  more than 90 days old. Missing xG is never treated as zero. Outside-five opponents have no xG.",
        "- xG differential is domestic-league-relative; it does not by itself solve cross-league strength.",
        "",
        "## Data provenance and limitations",
        "",
        "Understat.com league pages and getLeagueData endpoints returned a maintenance HTML page.",
        "Used the explicitly documented frozen Understat archive, not Opta/FBref or invented xG:",
        "[archive repository](https://github.com/peteowen1/pannadata),",
        "[metadata asset](https://github.com/peteowen1/pannadata/releases/download/understat-latest/understat_metadata.parquet).",
        "Release asset ID 399247157, updated 2026-04-18. See provenance.json for retrieval date, hashes,",
        "source inspection and an independent older Understat scrape cross-check.",
        "21,120 existing fixtures received xG. Exact league/season, resolved home/away IDs, date and scores",
        "must agree. No fuzzy mapping or ±day guessing: 152 rows quarantined, 189 duplicate source rows removed.",
        "Full league-season counts and every rejected row are in coverage.json. No unknown top-five names.",
        "No xG before 2014/15, no UCL xG, incomplete 2025/26 and historical gaps. No new matches were added.",
        "Archived xG was retrieved retrospectively; provider model revisions and original publication delays",
        "cannot be audited. Match-date cutoff protection does not prove point-in-time publication availability.",
        "See cutoff-coverage.json for xG freshness/fallbacks in every prediction cohort.",
        "",
        "## Rerun",
        "",
        "```sh",
        "PYTHONPATH=backend .venv/bin/python -m app.backtesting.xg_search --trials 2000 --seed 20261112 --output-dir experiments/xg",
        "```",
        "Use --resume to retain completed batches with matching data/config/source hashes. Source acquisition",
        "and additive database migration are documented in README.md. Existing production tables and rating",
        "predictions were checked unchanged after the import. No experimental model is deployed.",
    ]
    (output / "report.md").write_text("\n".join(lines) + "\n")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--trials", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=20261112)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "experiments/xg")
    parser.add_argument("--resume", action="store_true")
    args = parser.parse_args()
    if args.trials < 1 or args.batch_size < 1:
        parser.error("Positive trials/batch required")
    out = args.output_dir
    out.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    engine = get_engine()
    data = build_data(engine, TRAIN + EVAL)
    with Session(engine) as s:
        observations = {x.match_id: (x.home_xg, x.away_xg) for x in s.scalars(select(MatchXG))}
    configs = sample_configs(args.trials, args.seed)
    manifest = dict(
        seed=args.seed,
        trials=args.trials,
        data=data.signature,
        observations=hashlib.sha256(json.dumps(sorted(observations.items())).encode()).hexdigest(),
        sources={
            name: hashlib.sha256((Path(__file__).parent / name).read_bytes()).hexdigest()
            for name in ("xg_search.py", "xg_engine.py", "search_engine.py", "search_data.py")
        },
    )
    mp = out / "search-manifest.json"
    cp = out / "trials.jsonl"
    records = []
    if args.resume:
        if not mp.exists() or json.loads(mp.read_text()) != manifest:
            raise ValueError("Resume manifest differs")
        if cp.exists():
            for line in cp.read_text().splitlines():
                records.append(json.loads(line))
        if [r["id"] for r in records] != [c.identity for c in configs[: len(records)]]:
            raise ValueError("Checkpoint/configuration order differs")
    else:
        if cp.exists():
            raise ValueError("Checkpoint exists; use --resume or a new directory")
        mp.write_text(json.dumps(manifest, indent=2) + "\n")
    top = json.loads((ROOT / "experiments/top_models.json").read_text())
    reference_config = top["all_trials_top5_including_diagnostics"][0]["config"]
    p, _, r = batch_replay(
        data, [SearchConfig(), SearchConfig(**reference_config)], date(2013, 7, 1)
    )
    base, reference = p[:, 0, :], p[:, 1, :]
    cache = snapshots(data, observations)
    soft = xg_scores(observations)
    print(
        f"Cached {data.matches} matches, {len(observations)} xG fixtures, {len(configs)} configs; resume {len(records)}",
        flush=True,
    )
    for start in range(len(records), len(configs), args.batch_size):
        batch = configs[start : start + args.batch_size]
        begin = time.perf_counter()
        values = batch_xg(data, observations, batch, base, r[:, 0, :], cache, soft)
        elapsed = time.perf_counter() - begin
        new = [
            dict(
                id=c.identity,
                config=asdict(c),
                p=values[:, i, :].tolist(),
                seconds=elapsed / len(batch),
            )
            for i, c in enumerate(batch)
        ]
        with cp.open("a") as f:
            for row in new:
                f.write(json.dumps(row) + "\n")
        records.extend(new)
        eta = elapsed / len(batch) * (len(configs) - len(records))
        print(f"{len(records)}/{len(configs)} batch {elapsed:.2f}s ETA {eta:.1f}s", flush=True)
    y = np.array([[t["actual_a"] for t in f["rows"]] for f in data.fixtures], dtype=float)
    ix = season_indices(data, EVAL)
    base_record = dict(id="Model A", config={}, p=base.tolist())
    eligible = [base_record, *records]
    folds = {s: select_walk_forward(eligible, data, s) for s in ("probability", "accuracy")}

    def key(row):
        return (
            -metrics(np.asarray(row["p"])[ix], y[ix])["correct"],
            metrics(np.asarray(row["p"])[ix], y[ix])["log_loss"],
            row["id"],
        )

    best = min(records, key=key)
    summary = dict(
        trials=len(records),
        seed=args.seed,
        seconds=time.perf_counter() - started,
        comparisons={
            "Model A": metrics(base[ix], y[ix]),
            "Fixed exploratory 42/48 reference": metrics(reference[ix], y[ix]),
            "Best exploratory xG": metrics(np.asarray(best["p"])[ix], y[ix]),
            **{f"Walk-forward {s}": f["overall"] for s, f in folds.items()},
        },
        best_id=best["id"],
        best_changes=changes(data, np.asarray(best["p"]), base),
        best_changes_vs_42=changes(data, np.asarray(best["p"]), reference),
        families={},
        uncertainty={},
    )
    for family in sorted({c.family for c in configs}):
        subset = [r for r in records if r["config"]["family"] == family]
        b = min(subset, key=key)
        wf = select_walk_forward([base_record, *subset], data, "probability")
        summary["families"][family] = dict(
            trials=len(subset),
            best_id=b["id"],
            config=b["config"],
            exploratory=metrics(np.asarray(b["p"])[ix], y[ix]),
            walk_forward=wf["overall"],
        )
    for name, fd in folds.items():
        pp = np.array([f["p"] for f in fd["folds"]])
        summary["uncertainty"][name] = uncertainty(pp, base[ix], y[ix])
        full = base.copy()
        for f in fd["folds"]:
            full[season_indices(data, [f["season"]])[0]] = f["p"]
        fd["changes_vs_A"] = changes(data, full, base)
    coverage = []
    for f in data.fixtures:
        clubs = []
        for t in sorted({t for row in f["rows"] for t in (row["a"], row["b"])}):
            h = cache[f["cutoff"]].get(t, [])
            age = (f["cutoff"] - h[-1][0]).days if h else None
            clubs.append(
                dict(
                    team_id=data.team_ids[t],
                    club=data.names[data.team_ids[t]],
                    count=len(h),
                    latest=str(h[-1][0]) if h else None,
                    age_days=age,
                    eligible=len(h) >= 5 and age <= 90,
                )
            )
        coverage.append(
            dict(
                season=f["season"],
                cutoff=str(f["cutoff"]),
                clubs=clubs,
                fallback_ties=sum(
                    not all(
                        next(c["eligible"] for c in clubs if c["team_id"] == row[k])
                        for k in ("team_a_id", "team_b_id")
                    )
                    for row in f["rows"]
                ),
            )
        )
    (out / "cutoff-coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    with (out / "results.csv").open("w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "id",
                *asdict(configs[0]),
                "correct",
                "accuracy",
                "brier",
                "log_loss",
                "seconds",
            ],
        )
        writer.writeheader()
        for row in records:
            m = metrics(np.asarray(row["p"])[ix], y[ix])
            writer.writerow(
                dict(
                    id=row["id"],
                    **row["config"],
                    **{k: m[k] for k in ("correct", "accuracy", "brier", "log_loss")},
                    seconds=row["seconds"],
                )
            )
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "walk-forward.json").write_text(json.dumps(folds, indent=2) + "\n")
    (out / "top-models.json").write_text(json.dumps(sorted(records, key=key)[:20], indent=2) + "\n")
    (out / "baseline-reference.json").write_text(
        json.dumps(
            dict(
                A=base.tolist(),
                reference=reference.tolist(),
                seasons=[f["season"] for f in data.fixtures],
                reference_config=reference_config,
            ),
            indent=2,
        )
        + "\n"
    )
    report(out, summary, best, data, base, reference, folds)
    print(json.dumps(summary["comparisons"], indent=2), flush=True)


if __name__ == "__main__":
    main()
