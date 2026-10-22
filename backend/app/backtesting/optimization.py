from dataclasses import dataclass

import numpy as np
from scipy.optimize import minimize

from app.backtesting.evaluation import walk_forward
from app.backtesting.metrics import scores
from app.elo.replay import PlayedMatch
from app.predictions.model import PredictionConfig

BOUNDS = {
    "k_factor": (5.0, 60.0),
    "home_advantage": (0.0, 150.0),
    "goal_multiplier_scale": (0.5, 2.0),
    "draw_strength": (0.05, 2.0),
    "season_regression": (0.0, 0.75),
}


@dataclass(frozen=True)
class FitResult:
    config: PredictionConfig
    candidates: list[dict]
    selected: str
    seed: int
    fitted_parameters: tuple[str, ...]


def fit_parameters(
    train: list[PlayedMatch],
    validation: list[PlayedMatch],
    starts: int = 3,
    maxiter: int = 150,
    seed: int = 42,
) -> FitResult:
    """Only training outcomes reach the objective; validation selects a frozen candidate."""
    if not train or not validation:
        raise ValueError("Optimization needs training and validation matches")
    if not max(m.match_date for m in train) < min(m.match_date for m in validation):
        raise ValueError("Training must end before validation begins")
    if starts < 1 or starts > 10 or maxiter < 1 or maxiter > 1000:
        raise ValueError("Use 1-10 optimizer starts and 1-1000 iterations")
    names = tuple(
        name
        for name in BOUNDS
        if name != "season_regression" or len({m.season for m in train}) >= 2
    )
    bounds = np.array([BOUNDS[name] for name in names])
    lower, width = bounds[:, 0], bounds[:, 1] - bounds[:, 0]
    base = PredictionConfig()

    def decode(normalized: np.ndarray) -> PredictionConfig:
        values = dict(zip(names, lower + normalized * width, strict=True))
        draw = float(values.pop("draw_strength"))
        return PredictionConfig(
            elo=base.elo.model_copy(update={k: float(v) for k, v in values.items()}),
            draw_strength=draw,
        )

    def objective(normalized: np.ndarray) -> float:
        # Every evaluation replays training from initial ratings with candidate Elo parameters.
        return scores(walk_forward(train, decode(normalized)))["log_loss"]

    def validation_loss(config: PredictionConfig) -> float:
        frame = walk_forward(train + validation, config)
        validation_ids = {m.id for m in validation}
        return scores(frame[frame.match_id.isin(validation_ids)])["log_loss"]

    base_values = {**base.elo.model_dump(), "draw_strength": base.draw_strength}
    initial = (np.array([base_values[n] for n in names]) - lower) / width
    candidates = [
        {
            "id": "default",
            "config": base.model_dump(),
            "success": True,
            "message": "Untuned reference candidate",
            "iterations": 0,
            "train_log_loss": scores(walk_forward(train, base))["log_loss"],
            "validation_log_loss": validation_loss(base),
        }
    ]
    rng = np.random.default_rng(seed)
    for index in range(starts):
        start = initial if index == 0 else rng.uniform(0.1, 0.9, size=len(names))
        result = minimize(
            objective,
            start,
            method="L-BFGS-B",
            bounds=[(0, 1)] * len(names),
            options={"maxiter": maxiter, "ftol": 1e-10, "maxls": 30},
        )
        config = decode(result.x)
        candidates.append(
            {
                "id": f"fit-{index + 1}",
                "config": config.model_dump(),
                "success": bool(result.success),
                "message": str(result.message),
                "iterations": int(result.nit),
                "evaluations": int(result.nfev),
                "train_log_loss": float(result.fun),
                "validation_log_loss": validation_loss(config),
            }
        )
    successful = [c for c in candidates if c["success"]]
    chosen = min(successful, key=lambda c: c["validation_log_loss"])
    return FitResult(
        PredictionConfig.model_validate(chosen["config"]), candidates, chosen["id"], seed, names
    )
