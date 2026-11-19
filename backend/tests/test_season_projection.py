import numpy as np

from app.backtesting.season_projection import simulate
from app.backtesting.xg_engine import davidson


def sample_inputs():
    # Eight distinct opponents in a circular schedule.
    fixtures = [[h, (h + delta) % 36, None, None] for delta in range(1, 5) for h in range(36)]
    elo = np.linspace(1300, 1800, 36)
    home = davidson(elo[:, None] - elo + 65)
    neutral = davidson(elo[:, None] - elo)
    heads = [[home.tolist(), neutral.tolist()]] * 3
    return {
        "fixtures": fixtures,
        "heads": heads,
        "conditionals": [[[1, 0, 1]], [[0, 0, 1]], [[0, 1, 1]]],
        "clubs": [{"id": i, "name": str(i), "crest": None} for i in range(36)],
        "eligible": [False] * 36,
        "elo": elo.tolist(),
    }


def test_projection_conserves_mass_and_obeys_uefa_path():
    inputs = sample_inputs()
    forecast = simulate(inputs, 1000, 2, True)
    baseline = simulate(inputs, 1000, 2, False)
    assert forecast["clubs"] == baseline["clubs"]
    assert forecast == simulate(inputs, 1000, 2, True)
    clubs = forecast["clubs"]
    np.testing.assert_allclose(
        [
            sum(c[key] for c in clubs)
            for key in ("top8", "playoffs", "r16", "quarter", "semi", "final", "title")
        ],
        [8, 16, 16, 8, 4, 2, 1],
    )
    assert all(c["title"] <= c["final"] <= c["semi"] <= c["quarter"] <= c["r16"] for c in clubs)
    bracket = forecast["bracket"]
    finals = [m for m in bracket if m["round"] == "Final"]
    assert finals[0]["winner"] == forecast["champion"]
    assert len(bracket) == 23 and all(m["fallback"] for m in bracket)
    sample = np.asarray(forecast["scenario_standings"])
    for m in bracket:
        if m["round"] == "Play-offs":
            h, a = [int(np.flatnonzero(sample == m[key])[0]) + 1 for key in ("first", "second")]
            assert (h - 1) // 2 + (a - 1) // 2 == 15
        assert 0 <= m["p_first"] <= 1


def test_bracket_modes_share_a_draw_and_recompute_every_successor():
    from app.backtesting.season_projection import ROUNDS, probability_tables

    inputs = sample_inputs()
    modes = simulate(inputs, 1000, 2, True)["bracket_modes"]
    _, two_leg, final = probability_tables(inputs, True)
    opening = []
    for name, mode in modes.items():
        po, r16, qf, sf, finals = [
            [m for m in mode["bracket"] if m["round"] == stage] for stage in ROUNDS
        ]
        opening.append(([(m["first"], m["second"]) for m in po], [m["second"] for m in r16]))
        assert [m["first"] for m in r16] == [m["winner"] for m in po]
        for side in range(2):
            assert (qf[2 * side]["first"], qf[2 * side]["second"]) == (
                r16[6 + side]["winner"],
                r16[side]["winner"],
            )
            assert (qf[2 * side + 1]["first"], qf[2 * side + 1]["second"]) == (
                r16[4 + side]["winner"],
                r16[2 + side]["winner"],
            )
            assert (sf[side]["first"], sf[side]["second"]) == (
                qf[2 * side + 1]["winner"],
                qf[2 * side]["winner"],
            )
        assert mode["finalists"] == [m["winner"] for m in sf]
        assert [finals[0]["first"], finals[0]["second"]] == mode["finalists"]
        assert finals[0]["winner"] == mode["champion"]
        for m in mode["bracket"]:
            a, b, p = m["first"], m["second"], m["p_first"]
            assert p == (final if m["round"] == "Final" else two_leg)[a, b]
            assert m["winner"] in (a, b)
            if name == "likely":
                assert m["winner"] == (a if p >= 0.5 else b)
    assert opening[0] == opening[1]
    assert any(
        m["winner"] != (m["first"] if m["p_first"] >= 0.5 else m["second"])
        for m in modes["simulated"]["bracket"]
    )
