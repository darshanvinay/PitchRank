"""NumPy batch adapter for OFFLINE model search; production Elo is never patched."""

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace

import numpy as np

from app.backtesting.search_data import contract


@dataclass(frozen=True)
class SearchConfig:
    k_domestic: float = 20
    k_ucl: float = 20
    home: float = 65
    home_mode: str = "fixed"  # fixed, league, time (past observed fractional home results)
    neutral_factor: float = 0
    regression: float = 0.25
    regression_target: str = "initial"  # initial=1500, observed global mean, observed league mean
    regression_asymmetry: float = 0
    regression_league: float = 0
    margin: str = "log"  # binary, linear, log, sqrt
    margin_cap: float = 99
    margin_adjust: float = 0
    k_gap: float = 0
    k_stage: float = 0
    ucl_group: float = 1.25
    ucl_knockout: float = 1.5
    ucl_finals: float = 1.75
    opponent_league: float = 0
    form_window: int = 10
    form_weight: float = 0
    form_kind: str = "residual"  # residual, goal, opponent
    form_ew: bool = False
    form_venue: bool = False
    european_weight: float = 0
    offsets: str = "none"  # none, fixed warmup fit, learned online
    offset_sd: float = 50
    head: str = "davidson"  # davidson, expected, logistic, regularized
    draw_strength: float = 0.7
    logistic_rate: float = 0.05
    logistic_ridge: float = 0.1
    logistic_features: int = 7  # bits: recent residual, goals, European residual
    calibration: str = "none"  # none, platt, isotonic (past R16 labels only)

    def __post_init__(self):
        # Canonical numeric types prevent 20 and 20.0 from becoming duplicate identities.
        for field, kind in self.__annotations__.items():
            if kind is float:
                object.__setattr__(self, field, float(getattr(self, field)))
        if self.head == "regularized":
            object.__setattr__(self, "form_weight", 0.0)
            object.__setattr__(self, "european_weight", 0.0)
        else:
            object.__setattr__(self, "logistic_rate", 0.05)
            object.__setattr__(self, "logistic_ridge", 0.1)
            object.__setattr__(self, "logistic_features", 7)
        if self.form_weight == 0:
            for field, value in (
                ("form_window", 10),
                ("form_kind", "residual"),
                ("form_ew", False),
                ("form_venue", False),
            ):
                object.__setattr__(self, field, value)
        if self.offsets == "none":
            object.__setattr__(self, "offset_sd", 50.0)
            object.__setattr__(self, "opponent_league", 0.0)
            object.__setattr__(self, "regression_league", 0.0)
        if self.regression == 0:
            object.__setattr__(self, "regression_target", "initial")
            object.__setattr__(self, "regression_asymmetry", 0.0)
            object.__setattr__(self, "regression_league", 0.0)
        if self.margin == "binary":
            object.__setattr__(self, "margin_cap", 99.0)
        if self.head in ("expected", "logistic"):
            object.__setattr__(self, "draw_strength", 0.7)
        if self.home_mode == "fixed" and self.home == 0:
            object.__setattr__(self, "neutral_factor", 0.0)
        if not 0 <= self.logistic_features <= 7:
            raise ValueError("Invalid logistic feature mask")
        numbers = [v for v in asdict(self).values() if isinstance(v, (int, float))]
        if not all(math.isfinite(v) for v in numbers):
            raise ValueError("Nonfinite configuration")
        if not (0 < self.k_domestic <= 150 and 0 < self.k_ucl <= 150 and 0 <= self.home <= 200):
            raise ValueError("K/home outside experiment limits")
        if not 0 <= self.regression <= 1 or not -0.75 <= self.regression_asymmetry <= 0.75:
            raise ValueError("Invalid regression")
        if self.margin_cap < 1 or self.offset_sd <= 0 or self.draw_strength <= 0:
            raise ValueError("Invalid scale/cap")
        if not 0 <= self.form_weight <= 0.5 or not 0 <= self.european_weight <= 0.5:
            raise ValueError("Feature weight outside limits")
        if self.form_window not in (3, 5, 8, 10, 15, 20):
            raise ValueError("Unknown form window")
        for value, allowed in [
            (self.home_mode, ("fixed", "league", "time")),
            (self.regression_target, ("initial", "global", "league")),
            (self.margin, ("binary", "linear", "log", "sqrt")),
            (self.form_kind, ("residual", "goal", "opponent")),
            (self.offsets, ("none", "fixed", "learned")),
            (self.head, ("davidson", "expected", "logistic", "regularized")),
            (self.calibration, ("none", "platt", "isotonic")),
        ]:
            if value not in allowed:
                raise ValueError("Unknown experimental policy " + str(value))

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]

    @property
    def complexity(self):
        return sum(v != getattr(SearchConfig(), k) for k, v in asdict(self).items())


def sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -700, 700)))


def calibrate(p, old_p, old_y, kind):
    """Fit only passed-in, already resolved earlier ties. No normalization from future rows."""
    if kind == "none":
        return p.copy()
    if kind == "platt":
        if len(old_y) < 32 or len(set(old_y.tolist())) < 2:
            return p.copy()
        x = np.column_stack(
            (
                np.log(np.clip(old_p, 1e-8, 1 - 1e-8) / (1 - np.clip(old_p, 1e-8, 1 - 1e-8))),
                np.ones(len(old_y)),
            )
        )
        beta = np.array([1.0, 0.0])
        prior = beta.copy()
        for _ in range(15):
            q = sigmoid(x @ beta)
            h = (x.T * (q * (1 - q))) @ x + 5 * np.eye(2)
            step = np.linalg.solve(h, x.T @ (old_y - q) - 5 * (beta - prior))
            beta += step
            beta[0] = np.clip(beta[0], 0.25, 3)
            beta[1] = np.clip(beta[1], -2, 2)
            if np.max(np.abs(step)) < 1e-7:
                break
        return np.clip(sigmoid(beta[0] * np.log(p / (1 - p)) + beta[1]), 1e-6, 1 - 1e-6)
    if kind != "isotonic":
        raise ValueError("Unknown calibrator")
    if len(old_y) < 64 or len(set(old_y.tolist())) < 2:
        return p.copy()
    order = np.argsort(old_p, kind="stable")
    xp = old_p[order]
    yp = old_y[order]
    unique, inverse = np.unique(xp, return_inverse=True)
    counts = np.bincount(inverse)
    totals = np.bincount(inverse, weights=yp)
    blocks = []
    for i, (total, n) in enumerate(zip(totals, counts, strict=True)):
        blocks.append([i, i, float(total), int(n)])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] > blocks[-1][2] / blocks[-1][3]:
            b = blocks.pop()
            a = blocks.pop()
            blocks.append([a[0], b[1], a[2] + b[2], a[3] + b[3]])
    fitted = np.zeros(len(unique))
    for a, b, total, n in blocks:
        fitted[a : b + 1] = total / n
    # Conservative identity shrinkage, fixed before all optimization.
    return np.clip(0.5 * p + 0.5 * np.interp(p, unique, fitted), 1e-6, 1 - 1e-6)


def batch_replay(data, configs, freeze_offsets_before):
    """Independent model states; symmetric, zero-sum array updates mirror existing Elo-v1.

    Global learned states update only AFTER a kickoff batch. Data features and HA
    statistics are likewise pre-batch. Test labels never enter replay/feature fitting.
    """
    n = len(configs)
    teams = len(data.team_ids)
    if not n:
        raise ValueError("No configurations")
    arrays = {field: np.array([getattr(c, field) for c in configs]) for field in asdict(configs[0])}
    a = arrays.__getitem__
    r = np.full((n, teams), 1500.0)
    offset = np.zeros((n, 6))
    beta = np.tile([math.log(10), 0.0, 0.0, 0.0], (n, 1))
    prior_beta = beta.copy()
    intercept = np.log(a("draw_strength"))
    prior_intercept = intercept.copy()
    learned = a("offsets") == "learned"
    fixed = a("offsets") == "fixed"
    regularized = a("head") == "regularized"
    home_mode = a("home_mode")
    target_mode = a("regression_target")
    margin_mode = a("margin")
    scale = math.log(10) / 400
    probabilities = np.zeros((len(data.fixtures), n, 8))
    raw = probabilities.copy()
    ratings_at = np.zeros((len(data.fixtures), n, 16))
    cutoffs = {f["cutoff"]: i for i, f in enumerate(data.fixtures)}
    previous = None
    cross_n = 0.0
    games = 0
    draws = 0
    emitted = set()

    def home_value(ha, league, neutral=False):
        total, count, ewtotal, ewcount = ha
        mean = total[league] / max(1, count[league])
        ewmean = ewtotal[league] / max(1e-15, ewcount[league])
        empirical = (
            400
            / math.log(10)
            * math.log(np.clip(mean, 0.05, 0.95) / (1 - np.clip(mean, 0.05, 0.95)))
        )
        empirical_ew = (
            400
            / math.log(10)
            * math.log(np.clip(ewmean, 0.05, 0.95) / (1 - np.clip(ewmean, 0.05, 0.95)))
        )
        h = np.where(
            home_mode == "league",
            (a("home") * 200 + count[league] * np.clip(empirical, 0, 150)) / (200 + count[league]),
            a("home"),
        )
        h = np.where(
            home_mode == "time",
            (a("home") * 100 + ewcount[league] * np.clip(empirical_ew, 0, 150))
            / (100 + ewcount[league]),
            h,
        )
        return h * (a("neutral_factor") if neutral else 1)

    def outcome(diff, x, draw_rate):
        z = diff * scale
        x = np.column_stack((diff / 400, np.tile(x, (n, 1))))
        x[:, 1:] *= (a("logistic_features")[:, None] >> np.arange(3)) & 1
        z = np.where(regularized, np.sum(x * beta, axis=1), z)
        logits = np.column_stack(
            (z / 2, np.where(regularized, intercept, np.log(a("draw_strength"))), -z / 2)
        )
        logits -= np.max(logits, axis=1)[:, None]
        p = np.exp(logits)
        p /= p.sum(axis=1)[:, None]
        expected = sigmoid(diff * scale)
        draw = np.minimum(draw_rate, 1.9 * np.minimum(expected, 1 - expected))
        standard = np.column_stack((expected - draw / 2, draw, 1 - expected - draw / 2))
        logistic = sigmoid(diff * scale)
        alt = np.column_stack(
            ((1 - draw_rate) * logistic, np.full(n, draw_rate), (1 - draw_rate) * (1 - logistic))
        )
        p = np.where((a("head") == "expected")[:, None], standard, p)
        p = np.where((a("head") == "logistic")[:, None], alt, p)
        return p, x

    for block in data.blocks:
        if previous:
            decay = 2 ** (-(block.day - previous).days / (365.25 * 3))
            active = learned | (fixed & (block.day < freeze_offsets_before))
            offset[active] *= decay
            cross_n *= decay
        previous = block.day
        total, count, _, _ = block.ha
        # Smoothed observed draw frequency; raw scores are supplied by earlier events only.
        # Maintain separately below; no finished-season/global-frequency fit.
        draw_rate = (draws + 25) / (games + 100) if games else 0.25
        if block.day in cutoffs and block.day not in emitted:
            emitted.add(block.day)
            fi = cutoffs[block.day]
            f = data.fixtures[fi]
            for ti, tie in enumerate(f["rows"]):
                h, aw = tie["a"], tie["b"]
                lh, la = f["membership"][h], f["membership"][aw]
                base = r[:, h] - r[:, aw] + offset[:, lh] - offset[:, la]
                wi = np.array([(3, 5, 8, 10, 15, 20).index(c.form_window) for c in configs])
                ki = np.array(
                    [("residual", "goal", "opponent").index(c.form_kind) for c in configs]
                )
                ew = a("form_ew").astype(int)
                venue = a("form_venue")

                def feature(t, home):
                    vi = np.where(venue, 1 if home else 2, 0)
                    return f["bank"][ki, wi, ew, vi, t]

                form_first = feature(h, True) - feature(aw, False)
                form_second = feature(aw, True) - feature(h, False)
                manual = np.where(regularized, 0, a("form_weight"))
                euw = np.where(regularized, 0, a("european_weight"))
                eu = f["euro"][h] - f["euro"][aw]
                x = (
                    (f["bank"][0, 1, 0, 0, h] - f["bank"][0, 1, 0, 0, aw]) / 400,
                    (f["bank"][1, 1, 0, 0, h] - f["bank"][1, 1, 0, 0, aw]) / 400,
                    eu / 400,
                )
                first, _ = outcome(
                    base
                    + manual * form_first
                    + euw * eu
                    + home_value(f["ha"], 5, tie["neutral_first"]),
                    x,
                    draw_rate,
                )
                second, _ = outcome(
                    -base
                    + manual * form_second
                    - euw * eu
                    + home_value(f["ha"], 5, tie["neutral_second"]),
                    tuple(-v for v in x),
                    draw_rate,
                )
                value = np.clip(contract(first, second, tie["tensor"]), 1e-8, 1 - 1e-8)
                # Prevent the optimizer exploiting roundoff at mathematically tied probabilities.
                raw[fi, :, ti] = np.where(np.abs(value - 0.5) < 1e-12, 0.5, value)
                ratings_at[fi, :, 2 * ti] = r[:, h] + offset[:, lh]
                ratings_at[fi, :, 2 * ti + 1] = r[:, aw] + offset[:, la]
            past = [
                j
                for j, g in enumerate(data.fixtures[:fi])
                if max(t["available"] for t in g["rows"]) < f["cutoff"]
            ]
            y = np.array(
                [t["actual_a"] for j in past for t in data.fixtures[j]["rows"]], dtype=float
            )
            for ci, c in enumerate(configs):
                old = np.array([v for j in past for v in raw[j, ci]])
                value = calibrate(raw[fi, ci], old, y, c.calibration)
                probabilities[fi, ci] = np.where(np.abs(value - 0.5) < 1e-12, 0.5, value)
        # Freeze global targets before ANY result in this kickoff batch.
        reg = any(e.gap_home or e.gap_away for e in block.events)
        global_target = r[:, block.seen].mean(axis=1) if reg and block.seen else np.full(n, 1500.0)
        league_targets = [
            r[:, ix].mean(axis=1) if reg and ix else np.full(n, 1500.0) for ix in block.donors
        ]
        pending_offset = np.zeros_like(offset)
        pending_beta = np.zeros_like(beta)
        pending_intercept = np.zeros_like(intercept)
        extra_cross = 0.0
        new_draws = 0
        for e in block.events:
            for team, gap, league in (
                (e.home, e.gap_home, e.home_league),
                (e.away, e.gap_away, e.away_league),
            ):
                if gap:
                    target = np.where(target_mode == "global", global_target, 1500.0)
                    if league < 5:
                        target = np.where(target_mode == "league", league_targets[league], target)
                    rate = a("regression") * (
                        1
                        + np.where(
                            r[:, team] >= target,
                            a("regression_asymmetry"),
                            -a("regression_asymmetry"),
                        )
                    )
                    rate *= 1 + a("regression_league") * np.tanh(-offset[:, league] / 100)
                    r[:, team] = target + (r[:, team] - target) * (1 - np.clip(rate, 0, 1)) ** gap
            ha = home_value(block.ha, e.league, e.neutral)
            diff = r[:, e.home] - r[:, e.away]
            expected = sigmoid((diff + ha) * scale)
            actual = 1 if e.hg > e.ag else 0 if e.hg < e.ag else 0.5
            gd = np.minimum(abs(e.hg - e.ag), a("margin_cap"))
            g = np.where(
                margin_mode == "binary",
                1,
                np.where(
                    margin_mode == "linear",
                    np.maximum(1, gd),
                    np.where(
                        margin_mode == "sqrt",
                        np.sqrt(np.maximum(1, gd)),
                        np.maximum(1, np.log1p(gd)),
                    ),
                ),
            )
            g /= 1 + a("margin_adjust") * np.abs(diff) / 400
            k = a("k_domestic") if e.stage == 0 else a("k_ucl")
            importance = (
                1 if e.stage == 0 else a(("ucl_group", "ucl_knockout", "ucl_finals")[e.stage - 1])
            )
            k = (
                k
                / (1 + a("k_gap") * np.abs(diff) / 400)
                * (1 + a("k_stage") * (1 - 2 * e.progress))
            )
            if e.stage:
                k *= 1 + a("opponent_league") * np.minimum(
                    np.abs(offset[:, e.home_league] - offset[:, e.away_league]) / 100, 1
                )
            delta = k * importance * g * (actual - expected)
            # Train regularized match head on pre-update features, publishing after the batch.
            if regularized.any():
                ix = np.flatnonzero(regularized)
                rx = np.column_stack(
                    (
                        (diff[ix] + ha[ix] + offset[ix, e.home_league] - offset[ix, e.away_league])
                        / 400,
                        np.tile(e.x, (len(ix), 1)),
                    )
                )
                rx[:, 1:] *= (a("logistic_features")[ix, None] >> np.arange(3)) & 1
                rz = np.sum(rx * beta[ix], axis=1)
                logits = np.column_stack((rz / 2, intercept[ix], -rz / 2))
                logits -= np.max(logits, axis=1)[:, None]
                rp = np.exp(logits)
                rp /= rp.sum(axis=1)[:, None]
                step = a("logistic_rate")[ix] / math.sqrt(1 + games / 500)
                pending_beta[ix] += step[:, None] * (
                    (2 * actual - 1 - (rp[:, 0] - rp[:, 2]))[:, None] * rx / 2
                    - a("logistic_ridge")[ix, None] * (beta[ix] - prior_beta[ix])
                )
                pending_intercept[ix] += step * (
                    (actual == 0.5)
                    - rp[:, 1]
                    - a("logistic_ridge")[ix] * (intercept[ix] - prior_intercept[ix])
                )
            if (
                e.stage
                and e.home_league < 5
                and e.away_league < 5
                and e.home_league != e.away_league
            ):
                active = learned | (fixed & (block.day < freeze_offsets_before))
                q = sigmoid(
                    (diff + ha + offset[:, e.home_league] - offset[:, e.away_league]) * scale
                )
                rate = (
                    a("offset_sd") ** 2
                    * scale
                    / (1 + cross_n * a("offset_sd") ** 2 * scale**2 * 0.25)
                )
                change = active * rate * (actual - q)
                pending_offset[:, e.home_league] += change
                pending_offset[:, e.away_league] -= change
                extra_cross += 1
            r[:, e.home] += delta
            r[:, e.away] -= delta
            new_draws += actual == 0.5
        offset = np.clip(offset + pending_offset, -150, 150)
        cross_n += extra_cross
        beta = np.clip(beta + pending_beta, -6, 6)
        intercept = np.clip(intercept + pending_intercept, -3, 1.5)
        games += len(block.events)
        draws += new_draws
    if not np.isfinite(probabilities).all() or (probabilities <= 0).any():
        raise ValueError("Invalid predictions")
    return probabilities, raw, ratings_at


def sample_config(rng):
    """Sparse random policies avoid a meaningless full Cartesian product."""
    choose = rng.choice
    c = SearchConfig(
        k_domestic=float(choose((10, 15, 20, 25, 30, 35, 40, 50, 60, 75))),
        home=float(choose((0, 25, 50, 65, 75, 100, 125))),
        regression=float(choose((0, 0.1, 0.15, 0.2, 0.25, 0.3, 0.4, 0.5))),
    )
    c = replace(
        c,
        k_ucl=c.k_domestic
        if rng.random() < 0.6
        else float(choose((10, 15, 20, 25, 30, 35, 40, 50, 60, 75))),
    )
    if rng.random() < 0.6:
        c = replace(
            c,
            margin=str(choose(("binary", "log", "linear", "sqrt"))),
            margin_cap=float(choose((2, 3, 4, 5, 99))),
        )
    if rng.random() < 0.35:
        c = replace(
            c,
            ucl_group=float(choose((1, 1.25, 1.5, 1.75, 2, 2.5, 3))),
            ucl_knockout=float(choose((1, 1.25, 1.5, 1.75, 2, 2.5, 3))),
            ucl_finals=float(choose((1, 1.5, 1.75, 2, 2.5, 3))),
        )
    if rng.random() < 0.3:
        c = replace(
            c, home_mode=str(choose(("league", "time"))), neutral_factor=float(choose((0, 0.25)))
        )
    if rng.random() < 0.25:
        c = replace(
            c,
            regression_target=str(choose(("global", "league"))),
            regression_asymmetry=float(choose((-0.25, 0, 0.25))),
            regression_league=float(choose((0, 0.25))),
        )
    if rng.random() < 0.2:
        c = replace(
            c,
            k_gap=float(choose((0, 0.5, 1))),
            k_stage=float(choose((-0.25, 0.25, 0.5))),
            margin_adjust=float(choose((0, 0.5, 1))),
        )
    if rng.random() < 0.35:
        c = replace(
            c,
            form_window=int(choose((3, 5, 8, 10, 15, 20))),
            form_weight=float(choose((0.1, 0.2, 0.3, 0.4, 0.5))),
            form_kind=str(choose(("residual", "goal", "opponent"))),
            form_ew=bool(choose((False, True))),
            form_venue=bool(choose((False, True))),
        )
    if rng.random() < 0.2:
        c = replace(c, european_weight=float(choose((0.1, 0.2, 0.3, 0.5))))
    if rng.random() < 0.25:
        c = replace(
            c,
            offsets=str(choose(("fixed", "learned"))),
            offset_sd=float(choose((20, 50, 100))),
            opponent_league=float(choose((0, 0.25, 0.5))),
            regression_league=float(choose((0, 0.25, 0.5))),
        )
    if rng.random() < 0.3:
        c = replace(
            c,
            head=str(choose(("expected", "logistic", "regularized"))),
            logistic_rate=float(choose((0.02, 0.05, 0.1))),
            logistic_ridge=float(choose((0.01, 0.1, 1))),
            logistic_features=int(choose((0, 1, 2, 3, 4, 5, 6, 7))),
        )
    if rng.random() < 0.2:
        c = replace(c, draw_strength=float(choose((0.4, 0.7, 1, 1.3))))
    if rng.random() < 0.3:
        c = replace(c, calibration=str(choose(("platt", "isotonic"))))
    return c


def anchors():
    base = SearchConfig()
    items = [
        base,
        replace(base, home=0),
        replace(base, k_domestic=30, k_ucl=30),
        replace(base, regression_target="league", regression_asymmetry=0.25),
        replace(base, margin="sqrt", margin_cap=3),
        replace(base, form_weight=0.3, form_window=5, form_ew=True, form_venue=True),
        replace(base, offsets="learned", european_weight=0.2),
        replace(base, head="regularized", calibration="platt"),
    ]
    items += [replace(base, k_domestic=k, k_ucl=k) for k in (10, 15, 25, 35, 40, 50, 60, 75)]
    items += [replace(base, home=h) for h in (25, 50, 75, 100, 125)]
    items += [replace(base, regression=v) for v in (0, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5)]
    items += [replace(base, calibration=v) for v in ("platt", "isotonic")]
    items += [replace(base, form_weight=0.3, form_window=n) for n in (3, 5, 8, 10, 15, 20)]
    items += [replace(base, head=h) for h in ("expected", "logistic", "regularized")]
    return list({c.identity: c for c in items}.values())
