"""Capture frozen Champions League advancement forecasts in a separate SQLite ledger."""

import argparse
import hashlib
import json
import sqlite3
from datetime import UTC, date, datetime
from itertools import groupby
from pathlib import Path

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import actual_winner, conditional_scores
from app.backtesting.model_search import metrics
from app.backtesting.search_data import Block, Event, SearchData, contract, tie_tensor
from app.backtesting.xg_engine import XGConfig, batch_xg, davidson, snapshots
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, MatchXG
from app.db.session import ROOT, get_engine
from app.elo.season import replay_season
from app.services.ratings import played
from app.services.season import fingerprint

FREEZE = ROOT / "experiments/xg/prospective-freeze.json"


def digest(data):
    return hashlib.sha256(data).hexdigest()


def registry():
    frozen = json.loads(FREEZE.read_text())
    for name, sha in frozen["sha256"].items():
        if digest((ROOT / name).read_bytes()) != sha:
            raise ValueError(f"Frozen artifact differs: {name}")
    return frozen


def utc(value):
    if value is None:
        raise ValueError("Both fixtures require verified kickoff times")
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def verify_pair(first, second):
    if (
        first is None
        or second is None
        or first.league != "ucl"
        or second.league != "ucl"
        or first.stage != "knockout"
        or second.stage != "knockout"
        or first.season != second.season
        or (first.home_team_id, first.away_team_id) != (second.away_team_id, second.home_team_id)
        or utc(first.kickoff_at) >= utc(second.kickoff_at)
    ):
        raise ValueError(
            "Expected two chronological Champions League knockout legs with reversed clubs"
        )


def forecast(matches, observations, first, second, cutoff, frozen):
    """Adapt past-only results to the existing xG engine without changing its replay."""
    config = SeasonConfig.model_validate(frozen["baseline"])
    ids = sorted({t for m in matches for t in (m.home_team_id, m.away_team_id)})
    index = {team: i for i, team in enumerate(ids)}
    replay, _ = replay_season(
        played(matches),
        dict.fromkeys(ids),
        config,
        offseason_regression=config.elo.season_regression,
    )
    a, b = index[first.home_team_id], index[first.away_team_id]
    ra, rb = replay.ratings[first.home_team_id], replay.ratings[first.away_team_id]
    tensor = tie_tensor(
        conditional_scores(matches), first.neutral, second.neutral, int(first.season[:4]) <= 2020
    )
    diff = ra - rb
    ha = config.elo.home_advantage
    baseline = float(
        contract(
            davidson(diff + (0 if first.neutral else ha)),
            davidson(-diff + (0 if second.neutral else ha)),
            tensor,
        )
    )
    blocks, years = [], {}

    # Within a day, known kickoff order matches the historical adapter. All inputs
    # still precede the cutoff day, and same-day unknown kickoffs stay one batch.
    def key(m):
        return (m.match_date, m.home_team_id, m.away_team_id)

    for day, group in groupby(sorted(matches, key=key), key=lambda m: m.match_date):
        events = []
        group = list(group)
        if all(m.kickoff_at is not None for m in group):
            group.sort(key=lambda m: (m.kickoff_at, m.home_team_id, m.away_team_id))
        for m in group:
            h, aw = index[m.home_team_id], index[m.away_team_id]
            year = int(m.season[:4])
            gaps = [year - years.get(t, year) for t in (h, aw)]
            years[h] = years[aw] = year
            stage = {"domestic": 0, "league": 1, "knockout": 2, "finals": 3}[m.stage]
            events.append(
                Event(
                    m.id,
                    h,
                    aw,
                    year,
                    m.home_goals,
                    m.away_goals,
                    stage,
                    m.neutral,
                    0,
                    0,
                    0,
                    *gaps,
                    0,
                    (),
                )
            )
        blocks.append(Block(day, tuple(events), (), (), ()))
    blocks.append(Block(cutoff, (), (), (), ()))
    row = dict(a=a, b=b, neutral_first=first.neutral, neutral_second=second.neutral, tensor=tensor)
    # The historical batch contract is eight ties per cohort. Repeating the
    # input fills the unused slots, and only the first forecast is recorded.
    data = SearchData(
        blocks,
        [dict(cutoff=cutoff, season=first.season, rows=[row] * 8)],
        ids,
        {},
        "",
        len(matches),
        {},
    )
    history = snapshots(data, observations)
    entries = [history[cutoff].get(t, []) for t in (a, b)]
    fallback = any(len(e) < 5 or (cutoff - e[-1][0]).days > 90 for e in entries)
    models = frozen["xg"]
    values = batch_xg(
        data,
        observations,
        [XGConfig(**v) for v in models.values()],
        np.full((1, 8), baseline),
        np.array([[ra, rb] * 8]),
        history,
    )
    return {
        "Model A": baseline,
        **dict(zip(models, values[0, :, 0].tolist(), strict=True)),
    }, fallback


def ledger(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.execute("""CREATE TABLE IF NOT EXISTS forecasts (
        first_id INTEGER PRIMARY KEY, second_id INTEGER NOT NULL UNIQUE,
        payload TEXT NOT NULL
    )""")
    for action in ("UPDATE", "DELETE"):
        conn.execute(f"""CREATE TRIGGER IF NOT EXISTS no_forecast_{action}
            BEFORE {action} ON forecasts BEGIN
            SELECT RAISE(ABORT, 'Forecasts are append-only'); END""")
    return conn


def capture(engine, path, first_id, second_id):
    frozen = registry()
    with engine.connect() as db:
        db.exec_driver_sql("BEGIN")
        with Session(db) as session:
            first, second = session.get(Match, first_id), session.get(Match, second_id)
            verify_pair(first, second)
            now = datetime.now(UTC)
            if (
                first.status != "scheduled"
                or second.status != "scheduled"
                or now >= utc(first.kickoff_at)
            ):
                raise ValueError("Capture requires two scheduled fixtures before first-leg kickoff")
            cutoff = now.date()
            matches = session.scalars(
                select(Match).where(
                    Match.status == "finished",
                    Match.league.in_([*LEAGUES, "ucl"]),
                    Match.match_date >= date(2010, 7, 1),
                    Match.match_date < cutoff,
                )
            ).all()
            ids = {m.id for m in matches}
            xg_rows = [
                x
                for x in session.scalars(select(MatchXG))
                if x.match_id in ids and x.source == "understat" and utc(x.retrieved_at) <= now
            ]
            raw = sorted(
                (
                    x.match_id,
                    x.home_xg,
                    x.away_xg,
                    x.archive_sha256,
                    utc(x.retrieved_at).isoformat(),
                )
                for x in xg_rows
            )
            forecasts, fallback = forecast(
                matches, {r[0]: r[1:3] for r in raw}, first, second, cutoff, frozen
            )
            stamp = datetime.now(UTC)
            if stamp >= utc(first.kickoff_at):
                raise ValueError("Kickoff passed while computing forecasts")
            payload = dict(
                captured_at=stamp.isoformat(),
                cutoff=cutoff.isoformat(),
                season=first.season,
                kickoff_first=utc(first.kickoff_at).isoformat(),
                kickoff_second=utc(second.kickoff_at).isoformat(),
                clubs=[first.home_team_id, first.away_team_id],
                forecasts=forecasts,
                xg_fallback=fallback,
                match_hash=fingerprint(matches, [], SeasonConfig()),
                xg_hash=digest(json.dumps(raw).encode()),
                xg_count=len(raw),
                registry_hash=digest(FREEZE.read_bytes()),
                model_configs={
                    "Model A": frozen["baseline"],
                    **frozen["xg"],
                },
            )
            with ledger(path) as conn:
                conn.execute(
                    "INSERT INTO forecasts VALUES (?, ?, ?)",
                    (first_id, second_id, json.dumps(payload)),
                )
    return payload


def evaluate(engine, path):
    resolved, pending, scores = [], [], {}
    with ledger(path) as conn, Session(engine) as session:
        for first_id, second_id, raw in conn.execute("SELECT * FROM forecasts ORDER BY first_id"):
            row = json.loads(raw)
            first, second = session.get(Match, first_id), session.get(Match, second_id)
            try:
                verify_pair(first, second)
                if (
                    first.season != row["season"]
                    or [first.home_team_id, first.away_team_id] != row["clubs"]
                ):
                    raise ValueError("Fixture identity changed")
                captured = datetime.fromisoformat(row["captured_at"])
                if (
                    not captured
                    < utc(first.kickoff_at)
                    < utc(second.kickoff_at)
                    < datetime.now(UTC)
                ):
                    raise ValueError("Kickoff verification pending or forecast was late")
                if first.status != "finished" or second.status != "finished":
                    raise ValueError("Both legs require completed results")
                actual_a = actual_winner(first, second, int(first.season[:4]) <= 2020) == "A"
            except ValueError as exc:
                pending.append(dict(first_id=first_id, second_id=second_id, reason=str(exc)))
                continue
            resolved.append(dict(first_id=first_id, second_id=second_id, actual_a=actual_a, **row))
            for name, p in row["forecasts"].items():
                scores.setdefault(name, []).append((p, actual_a))
    return dict(
        resolved=resolved,
        pending=pending,
        metrics={name: metrics(*zip(*values)) for name, values in scores.items()},
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=ROOT / "data/prospective.sqlite3")
    commands = parser.add_subparsers(dest="command", required=True)
    save = commands.add_parser("capture", help="Capture using two reviewed scheduled match IDs")
    save.add_argument("first_id", type=int)
    save.add_argument("second_id", type=int)
    commands.add_parser("evaluate", help="Score stored probabilities against reviewed results")
    args = parser.parse_args()
    engine = get_engine()
    result = (
        capture(engine, args.ledger, args.first_id, args.second_id)
        if args.command == "capture"
        else evaluate(engine, args.ledger)
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
