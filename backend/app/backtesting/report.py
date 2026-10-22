"""Reproducible file-based experiment reports; no changes to production Elo history."""

import importlib.metadata
import json
import platform
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from app.backtesting.evaluation import (
    ChronologicalSplit,
    frequency_predictions,
    training_frequencies,
    walk_forward,
)
from app.backtesting.metrics import summarize
from app.backtesting.optimization import BOUNDS, fit_parameters
from app.core.elo import ENGINE_REVISION
from app.db.models import ImportRun, Match, Team
from app.predictions.model import PREDICTION_REVISION, PredictionConfig
from app.services.ratings import input_hash, played

REPORT_REVISION = "walk-forward-v1"


def plots(predictions: pd.DataFrame, summary: dict, directory: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    colors = {"selected_elo": "#087f70", "fixed_elo": "#333333", "training_frequency": "#a66318"}
    labels = {
        "selected_elo": "Selected Elo",
        "fixed_elo": "Fixed Elo",
        "training_frequency": "Training frequency",
    }
    test = predictions[predictions.period == "test"]
    with plt.rc_context(
        {
            "axes.spines.top": False,
            "axes.spines.right": False,
            "axes.titleweight": "bold",
            "figure.dpi": 130,
        }
    ):
        fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
        for ax, outcome in zip(axes, ("H", "D", "A"), strict=True):
            ax.plot([0, 1], [0, 1], color="#aaaaaa", linewidth=1, linestyle="--")
            for model, values in summary["test"].items():
                rows = [r for r in values["calibration"] if r["outcome"] == outcome and r["count"]]
                ax.plot(
                    [r["mean_probability"] for r in rows],
                    [r["observed_frequency"] for r in rows],
                    marker="o",
                    markersize=3,
                    color=colors[model],
                    label=labels[model],
                )
            ax.set(
                title={"H": "Home win", "D": "Draw", "A": "Away win"}[outcome],
                xlabel="Mean predicted probability",
                ylabel="Observed frequency",
                xlim=(0, 1),
                ylim=(0, 1),
            )
        axes[-1].legend(fontsize=8, loc="lower right")
        fig.suptitle("Final test calibration · equal-width bins; sparse bins are noisy")
        fig.savefig(directory / "calibration.png", bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
        for model, group in test.groupby("model", sort=True):
            p = group[["p_home", "p_draw", "p_away"]].to_numpy()
            actual = group.actual.map({"H": 0, "D": 1, "A": 2}).to_numpy()
            losses = -np.log(np.clip(p[np.arange(len(p)), actual], 1e-15, 1))
            ax.plot(
                pd.to_datetime(group.match_date),
                np.cumsum(losses) / np.arange(1, len(p) + 1),
                label=labels[model],
                color=colors[model],
                linewidth=1.5,
            )
        ax.set(
            title="Final test · cumulative multiclass log loss", ylabel="Log loss (lower is better)"
        )
        ax.legend(fontsize=8)
        fig.savefig(directory / "performance-over-time.png", bbox_inches="tight")
        plt.close(fig)

        fig, axes = plt.subplots(1, 3, figsize=(13, 4), layout="constrained")
        for ax, metric, title in zip(
            axes,
            ("accuracy", "brier_score", "log_loss"),
            ("Accuracy ↑", "Brier score ↓", "Log loss ↓"),
            strict=True,
        ):
            models = list(summary["test"])
            ax.barh(
                [labels[m] for m in models],
                [summary["test"][m][metric] for m in models],
                color=[colors[m] for m in models],
                height=0.5,
            )
            ax.set(title=title, xlim=(0, None))
            for i, model in enumerate(models):
                value = summary["test"][model][metric]
                ax.text(value, i, f" {value:.3f}", va="center", fontsize=9)
            ax.margins(x=0.18)
        fig.suptitle("Final test model comparison · identical matches")
        fig.savefig(directory / "model-comparison.png", bbox_inches="tight")
        plt.close(fig)

        fig, ax = plt.subplots(figsize=(10, 4), layout="constrained")
        seasons = sorted(predictions.season.unique())
        roles = predictions.groupby("season").period.first().to_dict()
        positions = np.arange(len(seasons))
        for i, model in enumerate(colors):
            values = [
                summary[period][model]["by_season"][season]["log_loss"]
                for period in ("validation", "test")
                for season in seasons
                if season in summary[period][model]["by_season"]
            ]
            ax.bar(
                positions + (i - 1) * 0.24,
                values,
                width=0.24,
                label=labels[model],
                color=colors[model],
            )
        ax.set(
            xticks=positions,
            xticklabels=[f"{season}\n{roles[season].capitalize()}" for season in seasons],
            ylabel="Log loss (lower is better)",
            title="Season performance · log loss (lower is better)",
        )
        ax.legend(fontsize=8)
        fig.savefig(directory / "performance-by-season.png", bbox_inches="tight")
        plt.close(fig)


def run_experiment(
    engine: Engine,
    split: ChronologicalSplit,
    output: Path,
    starts: int = 3,
    maxiter: int = 150,
    seed: int = 42,
) -> dict:
    if output.exists():
        raise ValueError(f"Report destination already exists: {output}; choose a new directory")
    with Session(engine) as session:
        session.execute(text("BEGIN"))
        matches = session.scalars(
            select(Match).where(Match.league == "epl").order_by(Match.id)
        ).all()
        teams = {t.id: t.display_name for t in session.scalars(select(Team))}
        sources = [
            {
                "id": r.id,
                "source": r.source,
                "location": r.location,
                "sha256": r.sha256,
                "season": r.season,
            }
            for r in session.scalars(select(ImportRun).order_by(ImportRun.id))
        ]
        # Materialize the complete source snapshot in one transaction, before CPU work.
        completed = played(matches)
        fingerprint = input_hash([m for m in matches if m.status == "finished"])
    split.validate(completed)
    train = [m for m in completed if m.season in split.train]
    validation = [m for m in completed if m.season in split.validation]
    fit = fit_parameters(train, validation, starts=starts, maxiter=maxiter, seed=seed)
    # Final test outcomes are never passed into fit_parameters or candidate selection.
    selected = walk_forward(completed, fit.config)
    fixed = walk_forward(completed, PredictionConfig())
    frequencies = training_frequencies(train)
    frames = []
    for model, frame in (
        ("selected_elo", selected),
        ("fixed_elo", fixed),
        ("training_frequency", frequency_predictions(selected, frequencies)),
    ):
        frame = frame[frame.season.isin(split.validation + split.test)].copy()
        frame["period"] = np.where(frame.season.isin(split.test), "test", "validation")
        frame["model"] = model
        frame["home_team"] = frame.home_team_id.map(teams)
        frame["away_team"] = frame.away_team_id.map(teams)
        frames.append(frame)
    predictions = pd.concat(frames, ignore_index=True)
    summary = {
        period: {
            model: summarize(group)
            for model, group in predictions[predictions.period == period].groupby(
                "model", sort=True
            )
        }
        for period in ("validation", "test")
    }
    manifest = {
        "report_revision": REPORT_REVISION,
        "elo_revision": ENGINE_REVISION,
        "prediction_revision": PREDICTION_REVISION,
        "dataset_hash": fingerprint,
        "split": asdict(split),
        "seed": seed,
        "starts": starts,
        "maxiter": maxiter,
        "optimizer": "L-BFGS-B; normalized bounds; training log loss objective",
        "bounds": BOUNDS,
        "fitted_parameters": fit.fitted_parameters,
        "selected_candidate": fit.selected,
        "candidates": fit.candidates,
        "training_frequency": dict(zip(("H", "D", "A"), frequencies.tolist(), strict=True)),
        "fixed_config": PredictionConfig().model_dump(),
        "selected_config": fit.config.model_dump(),
        "source_imports": sources,
        "python": platform.python_version(),
        "packages": {
            name: importlib.metadata.version(name)
            for name in ("numpy", "pandas", "scipy", "matplotlib", "pitchrank")
        },
        "limitations": [
            "Validation was used for selection; only the final test is held out.",
            "Historical same-day/kickoff grouping prevents within-group outcome leakage.",
            "Season membership is inferred from completed datasets; use complete EPL seasons.",
            "No confidence intervals or betting-profit claims; one held-out season is limited.",
            "Do not retune after inspecting the final test; new experiments need a fresh holdout.",
            "When training has only one season, regression stays at its untuned default.",
        ],
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".pitchrank-", dir=output.parent))
    try:
        (temporary / "manifest.json").write_text(
            json.dumps(manifest, indent=2, allow_nan=False) + "\n"
        )
        (temporary / "summary.json").write_text(
            json.dumps(summary, indent=2, allow_nan=False) + "\n"
        )
        (temporary / "selected-config.json").write_text(fit.config.model_dump_json(indent=2) + "\n")
        # Directly reusable by the Phase 2 versioned Elo CLI.
        (temporary / "selected-elo-config.json").write_text(
            fit.config.elo.model_dump_json(indent=2) + "\n"
        )
        predictions.to_csv(temporary / "predictions.csv", index=False, float_format="%.17g")
        pd.DataFrame([asdict(match) for match in completed]).to_csv(
            temporary / "dataset.csv", index=False
        )
        for period in ("validation", "test"):
            rows = [
                dict(model=model, **row)
                for model, values in summary[period].items()
                for row in values["calibration"]
            ]
            pd.DataFrame(rows).to_csv(temporary / f"calibration-{period}.csv", index=False)
        plots(predictions, summary, temporary)
        temporary.rename(output)
    except Exception:
        shutil.rmtree(temporary)
        raise
    return {
        "output": str(output.resolve()),
        "selected_candidate": fit.selected,
        "optimizer_warnings": [
            c["id"] + ": " + c["message"] for c in fit.candidates if not c["success"]
        ],
        "test": {
            model: {key: values[key] for key in ("matches", "accuracy", "brier_score", "log_loss")}
            for model, values in summary["test"].items()
        },
    }
