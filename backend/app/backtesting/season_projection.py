"""Dated research projections using the frozen xG ensemble and Model A."""

import argparse
import json
import os
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from tempfile import NamedTemporaryFile

import numpy as np
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backtesting.knockout import conditional_scores, extra_time_distribution
from app.backtesting.prospective import registry, utc
from app.backtesting.search_data import contract, score_shapes, tie_tensor
from app.backtesting.xg_engine import XGConfig, davidson, poisson_outcomes, xg_scores
from app.core.leagues import LEAGUES
from app.core.season import SeasonConfig
from app.db.models import Match, MatchXG, Team
from app.db.session import ROOT, get_engine
from app.elo.engine import update_ratings
from app.elo.season import replay_season
from app.services.ratings import played

BUNDLED_DIRECTORY = ROOT / "data/projections"
DIRECTORY = Path(os.getenv("PITCHRANK_PROJECTION_DIR", str(BUNDLED_DIRECTORY)))
SEASON = "2026-2027"
ROUNDS = ("Play-offs", "Round of 16", "Quarter-finals", "Semi-finals", "Final")


def model_inputs(matches, xg, clubs, cutoff, frozen):
    config = SeasonConfig.model_validate(frozen["baseline"])
    model = XGConfig(**frozen["xg"]["4e8e9969e40e42c4"])
    ids = {t for m in matches for t in (m.home_team_id, m.away_team_id)}
    replay, _ = replay_season(
        played(matches),
        dict.fromkeys(ids),
        config,
        offseason_regression=config.elo.season_regression,
    )
    elo = np.array([replay.ratings.get(t, 1500) for t in clubs])
    baseline = [
        davidson(elo[:, None] - elo + advantage) for advantage in (config.elo.home_advantage, 0)
    ]
    rating = dict.fromkeys(ids, 1500.0)
    attack, defence = dict.fromkeys(ids, 0.0), dict.fromkeys(ids, 0.0)
    years, last, counts = {}, {}, Counter()
    soft = xg_scores(xg)
    ec = config.elo.model_copy(update={"k_factor": model.k})
    for entry in replay.entries:
        m = entry.match
        h, a = m.home_team_id, m.away_team_id
        year = int(m.season[:4])
        for t in (h, a):
            shrink = (1 - model.regression) ** (year - years.get(t, year))
            rating[t] = 1500 + (rating[t] - 1500) * shrink
            attack[t] *= shrink
            defence[t] *= shrink
            years[t] = year
        importance = {"domestic": 1, "league": 1.25, "knockout": 1.5, "finals": 1.75}[m.stage]
        update = update_ratings(
            rating[h], rating[a], m.home_goals, m.away_goals, ec, importance, m.neutral
        )
        correction = 0
        if m.id in xg:
            correction = (
                model.k
                * importance
                * update.multiplier
                * model.xg_share
                * (soft[m.id] - update.actual_home)
            )
            adv = 0 if m.neutral else model.home_log / 2
            lh = model.prior_goals * np.exp(np.clip(attack[h] - defence[a] + adv, -2, 2))
            la = model.prior_goals * np.exp(np.clip(attack[a] - defence[h] - adv, -2, 2))
            dh, da = (
                model.learning_rate * (np.asarray(xg[m.id]) - [lh, la]) / (1 + np.array([lh, la]))
            )
            for bank, t, delta in (
                (attack, h, dh),
                (defence, a, -dh),
                (attack, a, da),
                (defence, h, -da),
            ):
                bank[t] = float(np.clip(bank[t] + delta, -1.5, 1.5))
            for t in (h, a):
                counts[t] += 1
                last[t] = m.match_date
        rating[h], rating[a] = update.home_after + correction, update.away_after - correction
    eligible = np.array([counts[t] >= 5 and cutoff - last[t] <= timedelta(days=90) for t in clubs])
    strength = np.array([rating.get(t, 1500) for t in clubs])
    att = np.array([attack.get(t, 0) for t in clubs])
    df = np.array([defence.get(t, 0) for t in clubs])
    diff = strength[:, None] - strength
    xelo = [davidson(diff + adv) for adv in (65, 0)]
    ad = []
    for adv in (model.home_log / 2, 0):
        lh = model.prior_goals * np.exp(np.clip(att[:, None] - df + adv, -2, 2))
        la = model.prior_goals * np.exp(np.clip(att - df[:, None] - adv, -2, 2))
        ad.append(poisson_outcomes(lh, la))
    return dict(
        elo=elo.tolist(),
        eligible=eligible.tolist(),
        heads=np.asarray([baseline, xelo, ad]).tolist(),
        conditionals=[
            [[*pair, p] for pair, p in sorted(rows.items())] for rows in conditional_scores(matches)
        ],
        latest_xg=str(max(last.values())) if last else None,
    )


def probability_tables(inputs, experimental):
    heads = np.array(inputs["heads"])
    eligible = np.array(inputs["eligible"])
    use = (eligible[:, None] & eligible) if experimental else np.zeros((36, 36), dtype=bool)
    shapes = [{(h, a): p for h, a, p in rows} for rows in inputs["conditionals"]]
    tensor = tie_tensor(shapes)
    ties = contract(heads[:, 0], heads[:, 0].swapaxes(1, 2), tensor)
    neutral = score_shapes(shapes, True)
    et = np.array(
        [
            sum(
                p * (1 if h > a else 0.5 if h == a else 0)
                for (h, a), p in extra_time_distribution(rows).items()
            )
            for rows in neutral
        ]
    )
    finals = heads[:, 1, :, :, 0] + heads[:, 1, :, :, 1] * (heads[:, 1] @ et)

    def combine(values):
        return np.where(use, (values[1] + values[2]) / 2, values[0])

    league = np.where(use[..., None], (heads[1, 0] + heads[2, 0]) / 2, heads[0, 0])
    return league, combine(ties), combine(finals)


def league_table(fixtures, shapes, probabilities, rng, n):
    totals = np.zeros((6, n, 36), dtype=np.int16)
    opponents = np.zeros((36, 36), dtype=np.int16)
    for h, a, hg, ag in fixtures:
        opponents[h, a] += 1
        opponents[a, h] += 1
        if hg is None:
            scores = [(x, y) for rows in shapes for x, y, _ in rows]
            mass = np.concatenate(
                [
                    np.array(rows)[:, 2] * p
                    for rows, p in zip(shapes, probabilities[h, a], strict=True)
                ]
            )
            sampled = np.array(scores)[rng.choice(len(scores), n, p=mass / mass.sum())]
            hg, ag = sampled.T
        hg, ag = np.broadcast_arrays(hg, ag)
        win, loss, draw = hg > ag, hg < ag, hg == ag
        totals[0, :, h] += 3 * win + draw
        totals[0, :, a] += 3 * loss + draw
        totals[1, :, h] += hg - ag
        totals[1, :, a] += ag - hg
        totals[2, :, h] += hg
        totals[2, :, a] += ag
        totals[3, :, a] += ag
        totals[4, :, h] += win
        totals[4, :, a] += loss
        totals[5, :, a] += loss
    # Opponent aggregates for Article 18(f–h). Eight known opponents per club.
    aggregates = [(t[:, np.flatnonzero(row)].sum(axis=1) for row in opponents) for t in totals[:3]]
    keys = [*totals, *(np.column_stack(list(a)) for a in aggregates)]
    # The input feed contains no league-phase disciplinary totals / coefficient
    # snapshot. Randomize only the residual exact ties and count their frequency.
    order = np.lexsort((rng.random((n, 36)), *[-k for k in keys[::-1]]), axis=1)
    tied = np.logical_and.reduce(
        [np.diff(np.take_along_axis(k, order, axis=1), axis=1) == 0 for k in keys]
    )
    return order, totals[0], float(tied.any(axis=1).mean())


def knockout(draw, play, tie, final):
    # Index by R16 seeded pair (1/2, 3/4, 5/6, 7/8), then side.
    po, r16 = [], []
    for group in range(4):
        seeded = draw(14 - 2 * group)
        unseeded = draw(16 + 2 * group)
        direct = draw(2 * group)
        pair = [play(unseeded[s], seeded[s], tie, 0) for s in range(2)]
        po.extend(pair)
        r16.append([play(pair[s], direct[s], tie, 1) for s in range(2)])
    qf, sf = [], []
    for side in range(2):
        # Winners inherit their path's leg-order privilege even after an upset.
        q1 = play(r16[3][side], r16[0][side], tie, 2)
        q2 = play(r16[2][side], r16[1][side], tie, 2)
        qf.extend([q1, q2])
        sf.append(play(q2, q1, tie, 3))
    return play(*sf, final, 4), po, r16, qf, sf


def simulate(inputs, n, seed, experimental):
    rng = np.random.default_rng(seed)
    league, tie, final = probability_tables(inputs, experimental)
    order, points, tiebreak = league_table(
        inputs["fixtures"], inputs["conditionals"], league, rng, n
    )
    rank = np.argsort(order, axis=1) + 1
    recorded = []
    draws = []
    rows = np.arange(n)

    def play(a, b, matrix, round_index):
        p = matrix[a, b]
        winner = np.where(rng.random(n) < p, a, b)
        recorded.append((round_index, a, b, winner, p))
        return winner

    def draw(pair):
        flip = rng.integers(0, 2, n)
        slots = order[rows, pair + flip], order[rows, pair + 1 - flip]
        draws.append(slots)
        return slots

    champions, po, r16, qf, sf = knockout(draw, play, tie, final)
    counts = np.bincount(champions, minlength=36)
    favorite = int(np.argmax(counts))
    # A coherent sampled bracket won by the title favorite, chosen for standings
    # nearest the mean. Scenario match probabilities remain conditional.
    candidates = np.flatnonzero(champions == favorite)
    distance = np.abs(rank[candidates] - rank.mean(axis=0)).sum(axis=1)
    sample = int(candidates[np.argmin(distance)])

    def reach(winners):
        return np.bincount(np.concatenate(winners), minlength=36) / n

    r16_winners = [w for sides in r16 for w in sides]
    stage = [
        reach([*po, *[order[:, i] for i in range(8)]]),
        reach(r16_winners),
        reach(qf),
        reach(sf),
        counts / n,
    ]
    assert np.allclose([p.sum() for p in stage], [16, 8, 4, 2, 1])
    club_rows = [
        dict(
            id=inputs["clubs"][i]["id"],
            name=inputs["clubs"][i]["name"],
            crest=inputs["clubs"][i]["crest"],
            elo=inputs["elo"][i],
            xg=inputs["eligible"][i],
            rank=float(rank[:, i].mean()),
            points=float(points[:, i].mean()),
            top8=float((rank[:, i] <= 8).mean()),
            playoffs=float(((rank[:, i] > 8) & (rank[:, i] <= 24)).mean()),
            r16=stage[0][i],
            quarter=stage[1][i],
            semi=stage[2][i],
            final=stage[3][i],
            title=stage[4][i],
        )
        for i in range(36)
    ]

    def tie_row(round_index, a, b, winner, probability):
        return dict(
            round=ROUNDS[round_index],
            first=int(a),
            second=int(b),
            winner=int(winner),
            p_first=float(probability),
            fallback=bool(experimental and not (inputs["eligible"][a] and inputs["eligible"][b])),
        )

    def sampled_bracket(index):
        return [tie_row(r, a[index], b[index], w[index], p[index]) for r, a, b, w, p in recorded]

    # Select the shared standings/draw without considering knockout winners.
    shared = int(np.argmin(np.abs(rank - rank.mean(axis=0)).sum(axis=1)))
    slots = iter((a[shared], b[shared]) for a, b in draws)
    likely = []

    def favor(a, b, matrix, round_index):
        p = matrix[a, b]
        winner = a if p >= 0.5 else b
        likely.append(tie_row(round_index, a, b, winner, p))
        return winner

    likely_champion, _, _, _, likely_finalists = knockout(lambda _: next(slots), favor, tie, final)
    return dict(
        clubs=club_rows,
        champion=favorite,
        finalists=[int(w[sample]) for w in sf],
        bracket=sampled_bracket(sample),
        scenario_standings=order[sample].tolist(),
        bracket_modes={
            "likely": dict(
                champion=int(likely_champion),
                finalists=[int(w) for w in likely_finalists],
                bracket=likely,
            ),
            "simulated": dict(
                champion=int(champions[shared]),
                finalists=[int(w[shared]) for w in sf],
                bracket=sampled_bracket(shared),
            ),
        },
        residual_tiebreak_rate=tiebreak,
    )


def project(engine, season=SEASON, *, trials=50_000, seed=202627):
    now = datetime.now(UTC)
    frozen = registry()
    with engine.connect() as conn:
        conn.exec_driver_sql("BEGIN")
        with Session(conn) as session:
            all_ucl = session.scalars(
                select(Match)
                .where(Match.league == "ucl", Match.season == season)
                .order_by(Match.match_date, Match.id)
            ).all()
            group = [m for m in all_ucl if m.stage == "league"]
            if any(m.stage != "league" and m.status in ("scheduled", "finished") for m in all_ucl):
                raise ValueError(
                    "Projection requires a league-phase snapshot before confirmed knockout draws"
                )
            clubs = sorted({t for m in group for t in (m.home_team_id, m.away_team_id)})
            if (
                len(group) != 144
                or len(clubs) != 36
                or any(
                    count != 8
                    for count in Counter(
                        t for m in group for t in (m.home_team_id, m.away_team_id)
                    ).values()
                )
                or len({frozenset((m.home_team_id, m.away_team_id)) for m in group}) != 144
            ):
                raise ValueError("Need the full verified 36-club league-phase fixture list")
            index = {t: i for i, t in enumerate(clubs)}
            matches = [
                m
                for m in session.scalars(
                    select(Match)
                    .where(
                        Match.league.in_([*LEAGUES, "ucl"]),
                        Match.status == "finished",
                        Match.match_date >= "2010-07-01",
                        Match.match_date <= now.date(),
                    )
                    .order_by(Match.id)
                )
                if m.kickoff_at is None or utc(m.kickoff_at) <= now
            ]
            ids = {m.id for m in matches}
            if any(m.status == "finished" and m.id not in ids for m in group):
                raise ValueError("Fixture feed contains a future completed match")
            if any(
                m.status != "finished" and (m.kickoff_at is None or utc(m.kickoff_at) <= now)
                for m in group
            ):
                raise ValueError("Refresh results for elapsed fixtures before projecting")
            xg = {
                x.match_id: (x.home_xg, x.away_xg)
                for x in session.scalars(select(MatchXG))
                if x.source == "understat" and x.match_id in ids and utc(x.retrieved_at) <= now
            }
            inputs = model_inputs(matches, xg, clubs, now.date(), frozen)
            inputs["clubs"] = [
                dict(id=t, name=club.display_name, crest=club.crest_url)
                for t in clubs
                if (club := session.get(Team, t))
            ]
            inputs["fixtures"] = [
                [
                    index[m.home_team_id],
                    index[m.away_team_id],
                    m.home_goals if m.status == "finished" else None,
                    m.away_goals if m.status == "finished" else None,
                ]
                for m in group
            ]
            latest = {
                key: max((str(m.match_date) for m in matches if m.league == key), default=None)
                for key in (*LEAGUES, "ucl")
            }
    return dict(
        season=season,
        generated_at=now.isoformat(),
        seed=seed,
        trials=trials,
        latest=latest,
        inputs=inputs,
        model_configs={
            "baseline": frozen["baseline"],
            "experimental": frozen["xg"]["4e8e9969e40e42c4"],
        },
        models={
            "xg": simulate(inputs, trials, seed, True),
            "baseline": simulate(inputs, trials, seed, False),
        },
    )


def publish(engine, season=SEASON, directory=DIRECTORY):
    forecast = project(engine, season)
    folder = directory / season
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(forecast, allow_nan=False)
    with NamedTemporaryFile(mode="w", dir=folder, delete=False) as file:
        file.write(payload)
    path = folder / (forecast["generated_at"].replace(":", "-") + ".json")
    os.replace(file.name, path)
    return path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", default=SEASON)
    parser.add_argument("--replay", type=Path)
    args = parser.parse_args()
    if args.replay:
        saved = json.loads(args.replay.read_text())
        for name in ("xg", "baseline"):
            actual = simulate(saved["inputs"], saved["trials"], saved["seed"], name == "xg")
            expected = saved["models"][name]
            assert all(actual[key] == value for key, value in expected.items())
        print("Both forecasts reproduced exactly")
    else:
        print(publish(get_engine(), args.season))


if __name__ == "__main__":
    main()
