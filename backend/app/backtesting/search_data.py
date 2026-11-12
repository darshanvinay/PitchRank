"""Immutable, cutoff-safe input cache and exact two-leg probability contraction."""

import hashlib
import json
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import date
from itertools import groupby

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import (
    actual_winner,
    conditional_scores,
    extra_time_distribution,
    extra_time_winner,
    regulation_winner,
)
from app.backtesting.tournament import grouped_ties
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, Team
from app.elo.season import replay_season
from app.services.ratings import played
from app.services.season import fingerprint

WINDOWS = (3, 5, 8, 10, 15, 20)
COUNTRIES = tuple(LEAGUES)


def score_shapes(conditionals, neutral):
    if not neutral:
        return conditionals
    wins = defaultdict(float)
    for pair, p in conditionals[0].items():
        wins[pair] += p / 2
    for (h, a), p in conditionals[2].items():
        wins[a, h] += p / 2
    return [dict(wins), conditionals[1], {(a, h): p for (h, a), p in wins.items()}]


def tie_tensor(conditionals, neutral_first=False, neutral_second=False, away_goals=False):
    """P(A advances)=F' W S + (F' T S)*(S' V), exactly the existing enumerator."""
    first = score_shapes(conditionals, neutral_first)
    second = score_shapes(conditionals, neutral_second)
    wins = np.zeros((3, 3))
    ties = np.zeros((3, 3))
    extra = np.zeros(3)
    for i in range(3):
        for j in range(3):
            for p1, m1 in first[i].items():
                for p2, m2 in second[j].items():
                    winner = regulation_winner(p1, p2, away_goals)
                    if winner == "A":
                        wins[i, j] += m1 * m2
                    elif winner is None:
                        ties[i, j] += m1 * m2
        for (h, a), p in extra_time_distribution(second[i]).items():
            winner = extra_time_winner(h, a, away_goals)
            extra[i] += p * (1 if winner == "A" else 0 if winner == "B" else 0.5)
    return wins, ties, extra


def contract(first, second, tensor):
    w, t, v = tensor
    return np.einsum("...i,ij,...j->...", first, w, second) + np.einsum(
        "...i,ij,...j->...", first, t, second
    ) * np.einsum("...i,i->...", second, v)


@dataclass(frozen=True)
class Event:
    mid: int
    home: int
    away: int
    year: int
    hg: int
    ag: int
    stage: int
    neutral: bool
    home_league: int
    away_league: int
    league: int
    gap_home: int
    gap_away: int
    progress: float
    x: tuple


@dataclass(frozen=True)
class Block:
    day: date
    events: tuple
    seen: tuple
    donors: tuple
    ha: tuple  # all-history and EW fractional home score, with effective counts


@dataclass
class SearchData:
    blocks: list
    fixtures: list
    team_ids: list
    names: dict
    signature: str
    matches: int
    audit: dict


def feature_snapshot(history, european, ratings, ids, day):
    """Feature axis: kind(residual/GD/opponent), window, EW, venue(all/home/away), club."""
    bank = np.zeros((3, 6, 2, 3, len(ids)))
    euro = np.zeros(len(ids))
    for t in range(len(ids)):
        for venue in range(3):
            entries = [r for r in history[t] if venue == 0 or r[3] == venue]
            for wi, n in enumerate(WINDOWS):
                subset = entries[-n:]
                if not subset:
                    continue
                values = np.array([r[:3] for r in subset])
                values[:, 2] -= ratings.get(ids[t], 1500)
                for ew in (0, 1):
                    weights = np.array(
                        [0.8 ** (len(subset) - 1 - i) if ew else 1 for i in range(len(subset))]
                    )
                    # Three zero-residual pseudo-matches regularize short recent histories.
                    bank[:, wi, ew, venue, t] = (values * weights[:, None]).sum(axis=0) / (
                        3 + weights.sum()
                    )
        entries = european[t]
        weights = np.array([2 ** (-(day - r[0]).days / (365.25 * 2)) for r in entries])
        if len(entries):
            euro[t] = sum(w * r[1] for w, r in zip(weights, entries, strict=True)) / (
                10 + weights.sum()
            )
    return bank, euro


def build_data(engine, requested_seasons):
    with Session(engine) as session:
        matches = session.scalars(
            select(Match).where(
                Match.league.in_([*COUNTRIES, "ucl"]),
                Match.status == "finished",
                Match.match_date >= date(2010, 7, 1),
                Match.match_date < date(2026, 7, 1),
            )
        ).all()
        names = {t.id: t.display_name for t in session.scalars(select(Team))}
    # Include earlier completed rounds only as calibration warmup, never future labels.
    seasons = sorted(
        {
            m.season
            for m in matches
            if m.league == "ucl"
            and (m.ucl_detail or {}).get("round") == "round_of_16"
            and m.season <= max(requested_seasons)
        }
    )
    if not set(requested_seasons) <= set(seasons):
        raise ValueError("Requested R16 season unavailable")
    ids = sorted({t for m in matches for t in (m.home_team_id, m.away_team_id)})
    index = {t: i for i, t in enumerate(ids)}
    fixtures = []
    for season in seasons:
        ties = grouped_ties(
            [m for m in matches if m.league == "ucl" and m.season == season], "round_of_16", 8
        )
        cutoff = min(legs[0].match_date for _, legs in ties)
        cond = conditional_scores([m for m in matches if m.match_date < cutoff])
        tensors = {}
        rows = []
        for tid, (first, second) in ties:
            nf, ns = first.neutral, second.neutral
            key = (nf, ns)
            if key not in tensors:
                tensors[key] = tie_tensor(cond, nf, ns, int(season[:4]) <= 2020)
            winner = actual_winner(first, second, int(season[:4]) <= 2020)
            rows.append(
                dict(
                    tie_id=tid,
                    a=index[first.home_team_id],
                    b=index[first.away_team_id],
                    team_a_id=first.home_team_id,
                    team_b_id=first.away_team_id,
                    neutral_first=nf,
                    neutral_second=ns,
                    actual_a=winner == "A",
                    available=second.match_date,
                    tensor=tensors[key],
                )
            )
        fixtures.append(dict(season=season, cutoff=cutoff, rows=rows, conditionals=cond))
    last_cutoff = max(f["cutoff"] for f in fixtures)
    matches = [m for m in matches if m.match_date <= last_cutoff]
    if len({m.id for m in matches}) != len(matches):
        raise ValueError("Duplicate match IDs")
    result, _ = replay_season(
        played(matches), dict.fromkeys(ids), SeasonConfig(), offseason_regression=0.25
    )
    updates = {e.match.id: e.update for e in result.entries}
    history = [deque(maxlen=80) for _ in ids]
    european = [deque(maxlen=80) for _ in ids]
    membership = np.full(len(ids), 5)
    last_year = {}
    domestic_year = {}
    seen = set()
    ratings = {}
    home_sum = np.zeros(6)
    home_n = np.zeros(6)
    ew_sum = np.zeros(6)
    ew_n = np.zeros(6)
    blocks = []
    previous = None
    by_cutoff = {f["cutoff"]: f for f in fixtures}
    ordered = sorted(matches, key=lambda m: (m.match_date, m.home_team_id, m.away_team_id))
    for day, day_matches in groupby(ordered, key=lambda m: m.match_date):
        day_matches = list(day_matches)
        if previous:
            decay = 2 ** (-(day - previous).days / 365.25)
            ew_sum *= decay
            ew_n *= decay
        previous = day
        if day in by_cutoff:
            f = by_cutoff[day]
            f["bank"], f["euro"] = feature_snapshot(history, european, ratings, ids, day)
            f["membership"] = membership.copy()
            f["ha"] = (home_sum.copy(), home_n.copy(), ew_sum.copy(), ew_n.copy())
        groups = (
            [day_matches]
            if any(m.kickoff_at is None for m in day_matches)
            else [
                list(g)
                for _, g in groupby(
                    sorted(
                        day_matches, key=lambda m: (m.kickoff_at, m.home_team_id, m.away_team_id)
                    ),
                    key=lambda m: m.kickoff_at,
                )
            ]
        )
        for group in groups:
            events = []
            used = set()
            group_year = min(int(m.season[:4]) for m in group)
            donors = tuple(
                tuple(
                    i
                    for i in sorted(seen)
                    if membership[i] == country and domestic_year.get(i, 0) >= group_year - 1
                )
                for country in range(5)
            )
            frozen_seen = tuple(sorted(seen))
            ha = (home_sum.copy(), home_n.copy(), ew_sum.copy(), ew_n.copy())
            pending = []
            for m in group:
                h, a = index[m.home_team_id], index[m.away_team_id]
                if h == a or h in used or a in used:
                    raise ValueError("Club repeated in kickoff batch")
                used.update((h, a))
                year = int(m.season[:4])
                league = COUNTRIES.index(m.league) if m.league in COUNTRIES else 5
                if league < 5:
                    membership[h] = membership[a] = league
                    domestic_year[h] = domestic_year[a] = year
                gaps = []
                for t in (h, a):
                    gap = year - last_year.get(t, year)
                    if gap < 0:
                        raise ValueError("Club season chronology reversed")
                    gaps.append(gap)
                    last_year[t] = year
                    seen.add(t)

                # Online logistic features use a fixed, physically scaled baseline feature bank.
                def recent(t, col):
                    z = list(history[t])[-5:]
                    return sum(r[col] for r in z) / (3 + len(z)) if z else 0

                def eu(t):
                    z = european[t]
                    w = [2 ** (-(day - d).days / (365.25 * 2)) for d, _ in z]
                    return (
                        sum(v * r[1] for v, r in zip(w, z, strict=True)) / (10 + sum(w)) if z else 0
                    )

                x = (
                    (recent(h, 0) - recent(a, 0)) / 400,
                    (recent(h, 1) - recent(a, 1)) / 400,
                    (eu(h) - eu(a)) / 400,
                )
                events.append(
                    Event(
                        m.id,
                        h,
                        a,
                        year,
                        m.home_goals,
                        m.away_goals,
                        {"domestic": 0, "league": 1, "knockout": 2, "finals": 3}[m.stage],
                        m.neutral,
                        int(membership[h]),
                        int(membership[a]),
                        league,
                        *gaps,
                        min(1, max(0, (day - date(year, 7, 1)).days / 365.25)),
                        x,
                    )
                )
                pending.append((m, h, a, updates[m.id], league))
            blocks.append(Block(day, tuple(events), frozen_seen, donors, ha))
            # Publish shared features only AFTER the entire kickoff group.
            for m, h, a, u, league in pending:
                score = (
                    1 if m.home_goals > m.away_goals else 0 if m.home_goals < m.away_goals else 0.5
                )
                residual = 400 * (u.actual_home - u.expected_home)
                adv = 0 if m.neutral else 65
                history[h].append(
                    (
                        residual,
                        50 * (m.home_goals - m.away_goals),
                        u.away_before + 400 * (score - 0.5) - adv,
                        1,
                    )
                )
                history[a].append(
                    (
                        -residual,
                        50 * (m.away_goals - m.home_goals),
                        u.home_before + 400 * (0.5 - score) + adv,
                        2,
                    )
                )
                if league == 5:
                    european[h].append((day, residual))
                    european[a].append((day, -residual))
                ratings[m.home_team_id] = u.home_after
                ratings[m.away_team_id] = u.away_after
                home_sum[league] += score
                home_n[league] += 1
                ew_sum[league] += score
                ew_n[league] += 1
    for f in fixtures:
        if "bank" not in f:
            raise ValueError("Cutoff not encountered")
    audit = {
        "domestic_matches": sum(m.league != "ucl" for m in matches),
        "ucl_matches": sum(m.league == "ucl" for m in matches),
        "clubs": len(ids),
        "source_start": str(min(m.match_date for m in matches)),
        "latest_replay_match": str(max(m.match_date for m in matches)),
        "chronology": "Date batches if any kickoff unknown; cutoff excludes its entire day",
        "valuation_prior": "None; neutral 1500",
        "limitations": [
            "UCL main draw starts 2011/12; outside-five domestic games unavailable",
            "Historical results/venue metadata are retrospective, not publication-time snapshots",
            "Earlier test seasons have already been examined in PitchRank experiments",
        ],
    }
    signature = hashlib.sha256(
        json.dumps(
            {
                "matches": fingerprint(matches, [], SeasonConfig()),
                "labels": [
                    (
                        f["season"],
                        [(r["tie_id"], r["actual_a"], str(r["available"])) for r in f["rows"]],
                    )
                    for f in fixtures
                ],
            },
            sort_keys=True,
        ).encode()
    ).hexdigest()
    return SearchData(blocks, fixtures, ids, names, signature, len(matches), audit)
