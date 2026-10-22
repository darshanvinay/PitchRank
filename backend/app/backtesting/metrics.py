import numpy as np
import pandas as pd

from app.predictions.model import OUTCOMES

PROBABILITY_COLUMNS = ["p_home", "p_draw", "p_away"]


def arrays(frame: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    if frame.empty:
        raise ValueError("Cannot evaluate an empty prediction set")
    probabilities = frame[PROBABILITY_COLUMNS].to_numpy(dtype=float)
    if (
        not np.isfinite(probabilities).all()
        or (probabilities < 0).any()
        or (probabilities > 1).any()
        or not np.allclose(probabilities.sum(axis=1), 1, atol=1e-10, rtol=0)
    ):
        raise ValueError("Invalid probability distribution")
    if not frame["actual"].isin(OUTCOMES).all():
        raise ValueError("Unknown actual outcome")
    actual = frame["actual"].map({outcome: i for i, outcome in enumerate(OUTCOMES)}).to_numpy()
    return probabilities, actual


def scores(frame: pd.DataFrame) -> dict:
    probabilities, actual = arrays(frame)
    one_hot = np.eye(3)[actual]
    predicted = np.argmax(probabilities, axis=1)  # deterministic H,D,A tie order
    return {
        "matches": len(frame),
        "accuracy": float(np.mean(predicted == actual)),
        # Unscaled multiclass Brier: sum across classes, mean across matches; range [0,2].
        "brier_score": float(np.mean(np.sum((probabilities - one_hot) ** 2, axis=1))),
        "log_loss": float(
            -np.mean(np.log(np.clip(probabilities[np.arange(len(frame)), actual], 1e-15, 1)))
        ),
    }


def calibration(frame: pd.DataFrame, bins: int = 10) -> list[dict]:
    if bins < 1 or bins > 100:
        raise ValueError("Calibration bins must be between 1 and 100")
    probabilities, actual = arrays(frame)
    rows = []
    for index, outcome in enumerate(OUTCOMES):
        assigned = np.minimum((probabilities[:, index] * bins).astype(int), bins - 1)
        for bucket in range(bins):
            mask = assigned == bucket
            rows.append(
                {
                    "outcome": outcome,
                    "bin": bucket,
                    "lower": bucket / bins,
                    "upper": (bucket + 1) / bins,
                    "count": int(mask.sum()),
                    "mean_probability": float(probabilities[mask, index].mean())
                    if mask.any()
                    else None,
                    "observed_frequency": float((actual[mask] == index).mean())
                    if mask.any()
                    else None,
                }
            )
    return rows


def summarize(frame: pd.DataFrame) -> dict:
    result = scores(frame)
    result["by_season"] = {
        str(season): scores(group) for season, group in frame.groupby("season", sort=True)
    }
    probabilities, _ = arrays(frame)
    labelled = frame.assign(predicted=[OUTCOMES[i] for i in np.argmax(probabilities, axis=1)])
    result["by_predicted_outcome"] = {
        outcome: scores(labelled[labelled.predicted == outcome])
        if (labelled.predicted == outcome).any()
        else {"matches": 0, "accuracy": None, "brier_score": None, "log_loss": None}
        for outcome in OUTCOMES
    }
    result["calibration"] = calibration(frame)
    return result
