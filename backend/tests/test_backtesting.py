import json
from dataclasses import replace
from datetime import date, datetime
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.evaluation import (
    ChronologicalSplit,
    frequency_predictions,
    training_frequencies,
    walk_forward,
)
from app.backtesting.metrics import calibration, scores, summarize
from app.backtesting.optimization import FitResult, fit_parameters
from app.backtesting.report import run_experiment
from app.core.elo import EloConfig
from app.db.models import Base, Match, ModelVersion, RatingHistory, Team
from app.db.session import get_engine
from app.elo.replay import PlayedMatch, replay
from app.predictions.model import PredictionConfig, probabilities


@pytest.fixture(autouse=True)
def plot_cache(tmp_path, monkeypatch):
    monkeypatch.setenv("MPLCONFIGDIR", str(tmp_path / "matplotlib"))


def seasons():
    matches = []
    for year in (2022, 2023, 2024):
        for i in range(9):
            hg, ag = [(2, 0), (1, 1), (0, 1)][i % 3]
            matches.append(
                PlayedMatch(
                    len(matches) + 1,
                    f"{year}-{year + 1}",
                    date(year, 8, i + 1),
                    None,
                    1 if i % 2 else 2,
                    2 if i % 2 else 1,
                    hg,
                    ag,
                )
            )
    return matches


def split():
    return ChronologicalSplit(("2022-2023",), ("2023-2024",), ("2024-2025",))


def test_probability_distribution_symmetry_and_draw_relationship():
    config = PredictionConfig(elo=EloConfig(home_advantage=0))
    equal = probabilities(1500, 1500, config)
    assert equal[0] == equal[2]
    assert equal[1] == pytest.approx(0.7 / 2.7)
    strong = probabilities(1700, 1400, config)
    reverse = probabilities(1400, 1700, config)
    assert np.allclose(strong, reverse[::-1])
    assert strong[1] < equal[1]
    assert strong[0] > equal[0]
    assert probabilities(1500, 1500, PredictionConfig())[0] > equal[0]
    assert np.allclose(equal.sum(), 1)
    assert (equal >= 0).all() and (equal <= 1).all()
    assert np.isfinite(probabilities(1e9, -1e9, config)).all()


@pytest.mark.parametrize("value", [float("inf"), float("nan")])
def test_bad_probability_inputs(value):
    with pytest.raises(ValueError, match="finite"):
        probabilities(value, 1500, PredictionConfig())


def test_metrics_against_hand_calculation():
    frame = pd.DataFrame(
        {"p_home": [0.5, 0.1], "p_draw": [0.25, 0.2], "p_away": [0.25, 0.7], "actual": ["H", "D"]}
    )
    result = scores(frame)
    assert result["matches"] == 2
    assert result["accuracy"] == 0.5
    assert result["log_loss"] == pytest.approx(-(np.log(0.5) + np.log(0.2)) / 2)
    assert result["brier_score"] == pytest.approx((0.375 + 1.14) / 2)


@pytest.mark.parametrize(
    "values",
    [
        [0.5, 0.4, 0.4],
        [-0.1, 0.5, 0.6],
        [np.nan, 0.5, 0.5],
        [1.1, 0, -0.1],
    ],
)
def test_metrics_reject_invalid_probabilities(values):
    frame = pd.DataFrame([dict(zip(["p_home", "p_draw", "p_away"], values, strict=True))])
    frame["actual"] = "H"
    with pytest.raises(ValueError, match="Invalid probability"):
        scores(frame)


def test_metrics_reject_empty_or_invalid_outcomes():
    with pytest.raises(ValueError, match="empty"):
        scores(pd.DataFrame())
    frame = pd.DataFrame({"p_home": [0.5], "p_draw": [0.25], "p_away": [0.25], "actual": ["X"]})
    with pytest.raises(ValueError, match="Unknown actual"):
        scores(frame)


def test_calibration_counts_bins_and_empty_states():
    frame = pd.DataFrame(
        {
            "p_home": [1.0, 0.0],
            "p_draw": [0.0, 1.0],
            "p_away": [0.0, 0.0],
            "actual": ["H", "D"],
            "season": ["2023-2024", "2023-2024"],
        }
    )
    rows = calibration(frame)
    assert len(rows) == 30
    for outcome in ("H", "D", "A"):
        assert sum(row["count"] for row in rows if row["outcome"] == outcome) == 2
    high = next(row for row in rows if row["outcome"] == "H" and row["bin"] == 9)
    assert high["count"] == 1 and high["mean_probability"] == high["observed_frequency"] == 1
    assert all(row["observed_frequency"] is None for row in rows if row["count"] == 0)
    summary = summarize(frame)
    assert summary["by_predicted_outcome"]["A"]["matches"] == 0
    assert summary["by_predicted_outcome"]["A"]["accuracy"] is None


def test_future_results_cannot_change_past_predictions():
    matches = seasons()
    before = walk_forward(matches, PredictionConfig())
    changed = [replace(m, home_goals=9, away_goals=0) if m.id >= 20 else m for m in matches]
    after = walk_forward(changed, PredictionConfig())
    columns = ["home_rating", "away_rating", "p_home", "p_draw", "p_away"]
    pd.testing.assert_frame_equal(
        before[before.match_id <= 20][columns], after[after.match_id <= 20][columns]
    )
    assert not before[before.match_id > 20][columns].equals(after[after.match_id > 20][columns])


def test_same_day_results_and_own_result_do_not_enter_prediction():
    original = seasons()[0]
    other = replace(
        original, id=99, home_team_id=3, away_team_id=4, kickoff_at=datetime(2022, 8, 1, 18)
    )
    before = walk_forward([other, original], PredictionConfig())
    after = walk_forward([other, replace(original, home_goals=0, away_goals=9)], PredictionConfig())
    pd.testing.assert_frame_equal(before.drop(columns="actual"), after.drop(columns="actual"))
    assert (before.home_rating == 1500).all()


def test_callbacks_run_for_whole_group_before_updates(monkeypatch):
    import app.elo.replay as module

    events = []
    original = module.update_ratings

    def observe(*args):
        events.append("update")
        return original(*args)

    monkeypatch.setattr(module, "update_ratings", observe)
    first = seasons()[0]
    second = replace(first, id=99, home_team_id=3, away_team_id=4)
    replay([first, second], EloConfig(), before_match=lambda *_: events.append("predict"))
    assert events == ["predict", "predict", "update", "update"]


def test_walk_forward_order_is_reproducible():
    matches = seasons()
    pd.testing.assert_frame_equal(
        walk_forward(matches, PredictionConfig()),
        walk_forward(list(reversed(matches)), PredictionConfig()),
    )


def test_baseline_only_uses_training_frequencies():
    matches = seasons()
    train = [replace(m, home_goals=1, away_goals=0) for m in matches[:9]]
    frequency = training_frequencies(train)
    assert frequency.tolist() == pytest.approx([10 / 12, 1 / 12, 1 / 12])
    reference = walk_forward(matches, PredictionConfig())
    baseline = frequency_predictions(reference, frequency)
    assert np.allclose(baseline[["p_home", "p_draw", "p_away"]], frequency)
    assert (reference.home_rating == baseline.home_rating).all()


@pytest.mark.parametrize(
    "value",
    [
        ChronologicalSplit((), ("2023-2024",), ("2024-2025",)),
        ChronologicalSplit(("2023-2024",), ("2022-2023",), ("2024-2025",)),
        ChronologicalSplit(("2022-2023",), ("2022-2023",), ("2024-2025",)),
        ChronologicalSplit(("2022-2023",), ("2023-2024",), ("2025-2026",)),
    ],
)
def test_invalid_split_rejected(value):
    with pytest.raises(ValueError):
        value.validate(seasons())


def test_date_overlap_between_splits_rejected():
    matches = seasons()
    matches[-1] = replace(matches[-1], match_date=date(2022, 8, 1))
    with pytest.raises(ValueError, match="overlap"):
        split().validate(matches)


def test_optimizer_determinism_bounds_and_no_test_data():
    matches = seasons()
    first = fit_parameters(matches[:9], matches[9:18], starts=1, maxiter=100)
    second = fit_parameters(matches[:9], matches[9:18], starts=1, maxiter=100)
    assert first.config == second.config and first.candidates == second.candidates
    assert "season_regression" not in first.fitted_parameters
    assert first.config.elo.season_regression == 0.25
    assert len(first.candidates) == 2
    assert first.candidates[1]["success"], first.candidates[1]["message"]
    assert 5 <= first.config.elo.k_factor <= 60
    assert 0.05 <= first.config.draw_strength <= 2
    assert (
        first.selected
        == min(
            (c for c in first.candidates if c["success"]), key=lambda c: c["validation_log_loss"]
        )["id"]
    )


def test_optimizer_objective_cannot_see_validation_or_test(monkeypatch):
    import app.backtesting.optimization as module

    matches = seasons()
    calls = []
    original = module.walk_forward

    def record(selected, config):
        calls.append(tuple(m.id for m in selected))
        return original(selected, config)

    def fake_minimize(objective, initial, **kwargs):
        calls.clear()
        loss = objective(initial)
        assert calls == [tuple(m.id for m in matches[:9])]
        return SimpleNamespace(x=initial, success=True, message="test fit", nit=1, nfev=1, fun=loss)

    monkeypatch.setattr(module, "walk_forward", record)
    monkeypatch.setattr(module, "minimize", fake_minimize)
    fit_parameters(matches[:9], matches[9:18], starts=1)
    assert all(max(ids) <= 18 for ids in calls)


def test_failed_optimizer_is_reported_and_not_selected(monkeypatch):
    import app.backtesting.optimization as module

    def fail(objective, initial, **kwargs):
        return SimpleNamespace(
            x=initial,
            success=False,
            message="iteration limit",
            nit=1,
            nfev=1,
            fun=objective(initial),
        )

    monkeypatch.setattr(module, "minimize", fail)
    result = fit_parameters(seasons()[:9], seasons()[9:18], starts=1)
    assert result.selected == "default"
    assert result.candidates[1]["success"] is False
    assert result.candidates[1]["message"] == "iteration limit"


def test_regression_is_fitted_only_with_multiple_training_seasons(monkeypatch):
    import app.backtesting.optimization as module

    def skip(objective, initial, **kwargs):
        return SimpleNamespace(
            x=initial, success=True, message="test", nit=0, nfev=1, fun=objective(initial)
        )

    monkeypatch.setattr(module, "minimize", skip)
    result = fit_parameters(seasons()[:18], seasons()[18:], starts=1)
    assert "season_regression" in result.fitted_parameters


@pytest.fixture
def database(tmp_path):
    engine = get_engine(f"sqlite:///{tmp_path / 'report.sqlite3'}")
    Base.metadata.create_all(engine)
    with Session(engine) as session, session.begin():
        session.add_all(
            [
                Team(id=1, canonical_name="Arsenal", display_name="Arsenal"),
                Team(id=2, canonical_name="Chelsea", display_name="Chelsea"),
            ]
        )
        session.flush()
        for match in seasons():
            session.add(
                Match(
                    id=match.id,
                    source="synthetic-test",
                    season=match.season,
                    match_date=match.match_date,
                    home_team_id=match.home_team_id,
                    away_team_id=match.away_team_id,
                    home_goals=match.home_goals,
                    away_goals=match.away_goals,
                    status="finished",
                )
            )
    yield engine
    engine.dispose()


def fake_fit(*args, **kwargs):
    return FitResult(PredictionConfig(), [], "default", 42, ())


def test_report_exports_recomputable_metrics_and_never_writes_ratings(
    database, tmp_path, monkeypatch
):
    import app.backtesting.report as module

    monkeypatch.setattr(module, "fit_parameters", fake_fit)
    output = tmp_path / "report"
    result = run_experiment(database, split(), output, starts=1)
    assert result["selected_candidate"] == "default"
    assert result["test"]["selected_elo"]["matches"] == 9
    predictions = pd.read_csv(output / "predictions.csv")
    assert len(predictions) == 18 * 3
    for period in ("validation", "test"):
        reference_ids = None
        for model in ("selected_elo", "fixed_elo", "training_frequency"):
            group = predictions[(predictions.period == period) & (predictions.model == model)]
            if reference_ids is not None:
                assert group.match_id.tolist() == reference_ids
            reference_ids = group.match_id.tolist()
            saved = json.loads((output / "summary.json").read_text())[period][model]
            for name, value in scores(group).items():
                assert saved[name] == pytest.approx(value)
    assert (output / "calibration.png").stat().st_size > 1000
    assert (output / "performance-over-time.png").stat().st_size > 1000
    assert (output / "model-comparison.png").stat().st_size > 1000
    assert (output / "performance-by-season.png").stat().st_size > 1000
    manifest = json.loads((output / "manifest.json").read_text())
    assert len(manifest["dataset_hash"]) == 64
    assert manifest["split"]["test"] == ["2024-2025"]
    assert len(pd.read_csv(output / "dataset.csv")) == 27
    with Session(database) as session:
        assert session.scalars(select(ModelVersion)).all() == []
        assert session.scalars(select(RatingHistory)).all() == []
        assert not any(m.processed for m in session.scalars(select(Match)))
    with pytest.raises(ValueError, match="already exists"):
        run_experiment(database, split(), output)


def test_report_selection_does_not_receive_test_matches(database, tmp_path, monkeypatch):
    import app.backtesting.report as module

    def inspect_fit(train, validation, **kwargs):
        assert {m.season for m in train} == {"2022-2023"}
        assert {m.season for m in validation} == {"2023-2024"}
        return fake_fit()

    monkeypatch.setattr(module, "fit_parameters", inspect_fit)
    monkeypatch.setattr(module, "plots", lambda *_: None)
    run_experiment(database, split(), tmp_path / "report")


def test_failed_report_is_not_published(database, tmp_path, monkeypatch):
    import app.backtesting.report as module

    def fail(*_):
        raise RuntimeError("plot failure")

    monkeypatch.setattr(module, "fit_parameters", fake_fit)
    monkeypatch.setattr(module, "plots", fail)
    with pytest.raises(RuntimeError, match="plot failure"):
        run_experiment(database, split(), tmp_path / "report")
    assert not (tmp_path / "report").exists()
    assert not list(tmp_path.glob(".pitchrank-*"))
