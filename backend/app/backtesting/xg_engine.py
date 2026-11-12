"""Isolated past-only xG experiments using the existing R16 probability contraction."""

import hashlib
import json
from collections import defaultdict
from dataclasses import asdict, dataclass

import numpy as np

from app.backtesting.search_data import contract
from app.backtesting.search_engine import sigmoid


@dataclass(frozen=True)
class XGConfig:
    family: str = "recent"
    window: int = 10  # 0 = all xG in this domestic season
    half_life: float = 60
    shrink: float = 5
    feature_scale: float = 100  # Elo units per one xG/game differential
    k: float = 20
    xg_share: float = 1
    regression: float = 0.25
    learning_rate: float = 0.05
    prior_goals: float = 1.35
    home_log: float = 0.25
    blend: float = 0.5  # probability-level weight of xG component vs Model A

    def __post_init__(self):
        if self.family not in ("differential", "recent", "xg_elo", "attack_defence", "ensemble"):
            raise ValueError("Unknown xG family")
        if self.family not in ("differential", "recent"):
            for key, value in (
                ("window", 10),
                ("half_life", 60),
                ("shrink", 5),
                ("feature_scale", 100),
            ):
                object.__setattr__(self, key, value)
        elif self.family == "differential":
            object.__setattr__(self, "window", 0)
        if self.family not in ("xg_elo", "ensemble"):
            object.__setattr__(self, "k", 20)
            object.__setattr__(self, "xg_share", 1)
        if self.family in ("differential", "recent"):
            object.__setattr__(self, "regression", 0.25)
        if self.family not in ("attack_defence", "ensemble"):
            for key, value in (("learning_rate", 0.05), ("prior_goals", 1.35), ("home_log", 0.25)):
                object.__setattr__(self, key, value)
        values = list(asdict(self).values())[1:]
        if not all(np.isfinite(v) for v in values):
            raise ValueError("Nonfinite xG configuration")
        if (
            self.window not in (0, 3, 5, 8, 10, 15, 20, 40)
            or self.half_life <= 0
            or self.shrink < 0
            or self.feature_scale < 0
            or not 0 < self.k <= 100
            or not 0 <= self.xg_share <= 1
            or not 0 <= self.regression <= 1
            or not 0 < self.learning_rate <= 0.3
            or not 0 < self.prior_goals <= 3
            or not 0 <= self.blend <= 1
        ):
            raise ValueError("Invalid xG configuration")

    @property
    def identity(self):
        return hashlib.sha256(json.dumps(asdict(self), sort_keys=True).encode()).hexdigest()[:16]


def poisson_outcomes(home, away):
    """Independent Poisson H/D/A; rates clipped for numerical stability, not observations.

    At maximum rate 8, mass above 40 goals is < 1e-15. Same past-trained goal-shape
    conditional distributions as production resolve the two-legged ties afterwards.
    """
    h, a = np.broadcast_arrays(np.clip(home, 0, 8), np.clip(away, 0, 8))
    hp, ap = [np.exp(-h)], [np.exp(-a)]
    for k in range(1, 41):
        hp.append(hp[-1] * h / k)
        ap.append(ap[-1] * a / k)
    hp, ap = np.stack(hp, axis=-1), np.stack(ap, axis=-1)
    draw = (hp * ap).sum(axis=-1)
    win = (hp * (np.cumsum(ap, axis=-1) - ap)).sum(axis=-1)
    loss = (ap * (np.cumsum(hp, axis=-1) - hp)).sum(axis=-1)
    p = np.stack((win, draw, loss), axis=-1)
    return p / p.sum(axis=-1, keepdims=True)


def davidson(diff):
    z = np.asarray(diff) * np.log(10) / 400
    logits = np.stack((z / 2, np.full_like(z, np.log(0.7)), -z / 2), axis=-1)
    logits -= logits.max(axis=-1, keepdims=True)
    p = np.exp(logits)
    return p / p.sum(axis=-1, keepdims=True)


def snapshots(data, observations):
    """One shared xG feature cache, produced before the entire prediction cutoff day."""
    history = defaultdict(list)
    cache = {}
    cutoffs = {f["cutoff"]: i for i, f in enumerate(data.fixtures)}
    for block in data.blocks:
        if block.day in cutoffs and block.day not in cache:
            cache[block.day] = {t: list(entries) for t, entries in history.items()}
        for e in block.events:
            if e.mid in observations:
                h, a = observations[e.mid]
                history[e.home].append((block.day, e.year, h - a))
                history[e.away].append((block.day, e.year, a - h))
    return cache


def feature(entries, day, year, config):
    eligible = [v for v in entries if (day - v[0]).days <= 365]
    if config.window:
        eligible = eligible[-config.window :]
    else:
        eligible = [v for v in eligible if v[1] == year]
    if not eligible:
        return 0.0
    weights = np.array([2 ** (-(day - v[0]).days / config.half_life) for v in eligible])
    return sum(w * v[2] for w, v in zip(weights, eligible, strict=True)) / (
        config.shrink + weights.sum()
    )


def xg_scores(observations):
    ids = list(observations)
    if not ids:
        return {}
    values = np.array([observations[mid] for mid in ids])
    p = poisson_outcomes(values[:, 0], values[:, 1])
    return dict(zip(ids, (p[:, 0] + 0.5 * p[:, 1]).tolist(), strict=True))


def batch_xg(
    data, observations, configs, baseline_p, baseline_ratings, cache=None, soft_scores=None
):
    """Neutral initial ratings, chronological independent state, no squad-value priors.

    Missing xG uses ordinary result updates for xG-Elo, skips attack/defence training.
    Forecasts fall back to A if either club lacks 5 observed xG matches, or its latest
    observation is >90 days old. No zero-xG imputation and no stale season totals.
    """
    cache = snapshots(data, observations) if cache is None else cache
    n, teams = len(configs), len(data.team_ids)
    if not n:
        raise ValueError("Empty xG batch")
    arr = {k: np.array([getattr(c, k) for c in configs]) for k in asdict(configs[0])}
    ratings = np.full((n, teams), 1500.0)
    attack, defence = np.zeros_like(ratings), np.zeros_like(ratings)
    result = np.zeros((len(data.fixtures), n, 8))
    a = arr.__getitem__
    cutoffs = {f["cutoff"]: i for i, f in enumerate(data.fixtures)}
    emitted = set()
    # Quasi-Poisson xG-Elo scores are computed from genuine observed xG only.
    soft = xg_scores(observations) if soft_scores is None else soft_scores
    for block in data.blocks:
        if block.day in cutoffs and block.day not in emitted:
            emitted.add(block.day)
            fi = cutoffs[block.day]
            f = data.fixtures[fi]
            history = cache[block.day]
            for ti, tie in enumerate(f["rows"]):
                h, aw = tie["a"], tie["b"]
                eh, ea = history.get(h, []), history.get(aw, [])
                eligible = (
                    len(eh) >= 5
                    and len(ea) >= 5
                    and (block.day - eh[-1][0]).days <= 90
                    and (block.day - ea[-1][0]).days <= 90
                )
                if not eligible:
                    result[fi, :, ti] = baseline_p[fi, ti]
                    continue
                base = baseline_ratings[fi, 2 * ti] - baseline_ratings[fi, 2 * ti + 1]
                fd = np.array(
                    [
                        feature(eh, block.day, int(f["season"][:4]), c)
                        - feature(ea, block.day, int(f["season"][:4]), c)
                        for c in configs
                    ]
                )
                nf, ns = tie["neutral_first"], tie["neutral_second"]
                fp = contract(
                    davidson(base + a("feature_scale") * fd + (0 if nf else 65)),
                    davidson(-base - a("feature_scale") * fd + (0 if ns else 65)),
                    tie["tensor"],
                )
                ed = ratings[:, h] - ratings[:, aw]
                ep = contract(
                    davidson(ed + (0 if nf else 65)),
                    davidson(-ed + (0 if ns else 65)),
                    tie["tensor"],
                )

                def attack_probs(home, away, neutral):
                    adv = 0 if neutral else a("home_log") / 2
                    lh = a("prior_goals") * np.exp(
                        np.clip(attack[:, home] - defence[:, away] + adv, -2, 2)
                    )
                    la = a("prior_goals") * np.exp(
                        np.clip(attack[:, away] - defence[:, home] - adv, -2, 2)
                    )
                    return poisson_outcomes(lh, la)

                ap = contract(attack_probs(h, aw, nf), attack_probs(aw, h, ns), tie["tensor"])
                component = np.where(np.isin(a("family"), ("differential", "recent")), fp, ep)
                component = np.where(a("family") == "attack_defence", ap, component)
                component = np.where(a("family") == "ensemble", (ep + ap) / 2, component)
                result[fi, :, ti] = (1 - a("blend")) * baseline_p[fi, ti] + a("blend") * component
        for e in block.events:
            for t, gap in ((e.home, e.gap_home), (e.away, e.gap_away)):
                if gap:
                    factor = (1 - a("regression")) ** gap
                    ratings[:, t] = 1500 + (ratings[:, t] - 1500) * factor
                    attack[:, t] *= factor
                    defence[:, t] *= factor
            advantage = 0 if e.neutral else 65
            expected = sigmoid(
                (ratings[:, e.home] - ratings[:, e.away] + advantage) * np.log(10) / 400
            )
            actual = 1 if e.hg > e.ag else 0 if e.hg < e.ag else 0.5
            target = (
                (1 - a("xg_share")) * actual + a("xg_share") * soft[e.mid]
                if e.mid in soft
                else actual
            )
            importance = (1, 1.25, 1.5, 1.75)[e.stage]
            # No changes to production formula; this experimental target is a convex
            # blend of realized outcome and expected outcome under observed xG.
            delta = a("k") * importance * max(1, np.log1p(abs(e.hg - e.ag))) * (target - expected)
            ratings[:, e.home] += delta
            ratings[:, e.away] -= delta
            if e.mid in observations:
                xh, xa = observations[e.mid]
                adv = 0 if e.neutral else a("home_log") / 2
                lh = a("prior_goals") * np.exp(
                    np.clip(attack[:, e.home] - defence[:, e.away] + adv, -2, 2)
                )
                la = a("prior_goals") * np.exp(
                    np.clip(attack[:, e.away] - defence[:, e.home] - adv, -2, 2)
                )
                dh = a("learning_rate") * (xh - lh) / (1 + lh)
                da = a("learning_rate") * (xa - la) / (1 + la)
                attack[:, e.home] = np.clip(attack[:, e.home] + dh, -1.5, 1.5)
                defence[:, e.away] = np.clip(defence[:, e.away] - dh, -1.5, 1.5)
                attack[:, e.away] = np.clip(attack[:, e.away] + da, -1.5, 1.5)
                defence[:, e.home] = np.clip(defence[:, e.home] - da, -1.5, 1.5)
    if not np.isfinite(result).all() or (result <= 0).any():
        raise ValueError("Invalid xG probabilities")
    return np.clip(result, 1e-8, 1 - 1e-8)


def sample_configs(trials, seed):
    if not 1 <= trials <= 2250:
        raise ValueError("Balanced search supports 1–2250 unique configurations")
    rng = np.random.default_rng(seed)
    found = {}
    families = ("differential", "recent", "xg_elo", "attack_defence", "ensemble")
    while len(found) < trials:
        family = families[len(found) % len(families)]
        c = XGConfig(
            family=family,
            window=int(rng.choice((3, 5, 8, 10, 15, 20, 40))),
            half_life=float(rng.choice((14, 30, 60, 120, 365))),
            shrink=float(rng.choice((2, 5, 10))),
            feature_scale=float(rng.choice((25, 50, 100, 150, 200, 300))),
            k=float(rng.choice((10, 15, 20, 30, 40, 60))),
            xg_share=float(rng.choice((0.25, 0.5, 0.75, 1))),
            regression=float(rng.choice((0, 0.1, 0.25, 0.4))),
            learning_rate=float(rng.choice((0.02, 0.05, 0.1, 0.2))),
            prior_goals=float(rng.choice((1.2, 1.35, 1.5))),
            home_log=float(rng.choice((0, 0.15, 0.25, 0.4))),
            blend=float(rng.choice((0.1, 0.25, 0.5, 0.75, 1))),
        )
        found[c.identity] = c
    return list(found.values())
