import { apiFetch } from "./api";
import SeasonProjection from "./SeasonProjection";
import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

type Club = { id: number; name: string; crest: string | null; elo: number };
type Matchup = {
  id: string; round: string; team_a_id: number; team_b_id: number;
  winner_id: number; p_a: number; p_b: number; single_match: boolean;
  neutral_first: boolean; neutral_second: boolean;
};
type Forecast = { champion_id: number; joint_probability: number; matches: Matchup[] };
type Bracket = {
  season: string; scenario: string; scenario_description: string; cutoff: string;
  clubs: Club[]; forecasts: Record<"greedy" | "global", Forecast>;
  rules: { away_goals: boolean };
};
const rounds = [
  ["round_of_16", "Round of 16"], ["quarterfinal", "Quarterfinals"],
  ["semifinal", "Semifinals"], ["final", "Final"],
];
const percent = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 1 });
const jointPercent = new Intl.NumberFormat(undefined, { style: "percent", maximumSignificantDigits: 3 });
const rating = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });

export default function ChampionsBracket() {
  const [params] = useSearchParams();
  return params.has("season") || params.has("scenario") || params.has("method")
    ? <HistoricalBracket /> : <SeasonProjection />;
}

function HistoricalBracket() {
  const [params, setParams] = useSearchParams();
  const season = params.get("season") || "2020-2021";
  const scenario = params.get("scenario") || "r16_order";
  const method = params.get("method") === "global" ? "global" : "greedy";
  const [data, setData] = useState<Bracket | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    apiFetch(`/api/ucl/bracket?season=${encodeURIComponent(season)}&scenario=${encodeURIComponent(scenario)}`,
      { signal: controller.signal, cache: "no-store" })
      .then(async (response) => {
        if (!response.ok) throw new Error("Bracket unavailable. Choose a supported season or retry.");
        return response.json() as Promise<Bracket>;
      })
      .then((result) => { if (!controller.signal.aborted) { setData(result); setError(""); } })
      .catch((e: Error) => { if (e.name !== "AbortError") setError(e.message); });
    return () => controller.abort();
  }, [season, scenario, revision]);
  function change(key: string, value: string) {
    const next = new URLSearchParams(params);
    next.set(key, value);
    if (key !== "match") next.delete("match");
    setParams(next);
    if (key === "season" || key === "scenario") setError("");
  }
  const current = data?.season === season && data.scenario === scenario ? data : null;
  const forecast = current?.forecasts[method];
  const clubs = new Map(current?.clubs.map((club) => [club.id, club]));
  const selected = forecast?.matches.find((match) => match.id === params.get("match"));
  const champion = forecast && clubs.get(forecast.champion_id);
  const detailRef = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const dialog = detailRef.current;
    if (selected && dialog && !dialog.open) dialog.showModal();
    else if (!selected && dialog?.open) dialog.close();
  }, [selected]);
  function closeSelection() {
    const next = new URLSearchParams(params);
    next.delete("match");
    setParams(next, { replace: true });
  }
  return <>
    <div className="title-row"><div><h1>Knockout bracket</h1>
      <p>Model A · Ratings frozen before the Round of 16.</p></div></div>
    <div className="table-toolbar history-filters bracket-controls">
      <label>Season<select value={season} name="season" onChange={(e) => change("season", e.target.value)}>
        {Array.from({ length: 6 }, (_, i) => 2020 + i).map((y) =>
          <option key={y} value={`${y}-${y + 1}`}>{y}/{String(y + 1).slice(-2)}</option>)}
      </select></label>
      <label>Bracket scenario<select value={scenario} name="scenario" onChange={(e) => change("scenario", e.target.value)}>
        <option value="r16_order">Fixed R16 order</option>
        <option value="observed_draw">Recorded later draws · retrospective</option>
      </select></label>
      <label>Selection<select value={method} name="method" onChange={(e) => change("method", e.target.value)}>
        <option value="greedy">Greedy winners</option><option value="global">Most probable complete bracket</option>
      </select></label>
    </div>
    <aside className="bracket-assumption" aria-label="Forecast assumptions">
      <strong>Conditional forecast</strong>
      <p>{scenario === "observed_draw"
        ? "Uses recorded later-round pairings, home order and venue flags. These are retrospective assumptions, not information established as known before the Round of 16."
        : "Adjacent winners in sorted Round-of-16 tie order meet next; the left slot hosts first. This is a specified scenario, not the historical later draw."}</p>
    </aside>
    {error ? <div className="error-state" role="alert"><p>{error}</p>
      <button onClick={() => { setError(""); setRevision((n) => n + 1); }}>Retry bracket</button></div>
      : !current || !forecast ? <p className="bracket-loading" role="status">Calculating knockout bracket…</p>
      : <>
        <section className="bracket-summary" aria-live="polite" aria-label="Forecast summary">
          <div><span>Predicted champion</span><strong>{champion?.name}</strong></div>
          <div><span>Rating cutoff, exclusive</span><strong><time dateTime={current.cutoff}>
            {new Intl.DateTimeFormat(undefined, { day: "numeric", month: "short", year: "numeric" }).format(new Date(`${current.cutoff}T12:00:00`))}
          </time></strong></div>
          <div><span>Complete bracket probability</span><strong>{jointPercent.format(forecast.joint_probability)}</strong></div>
        </section>
        <p className="bracket-explainer">Select a tie for Elo ratings and advancement probabilities.
          {method === "global" && " Global optimization can choose a less likely individual winner to improve the probability of the complete bracket."}
          {" "}The complete-bracket probability is not the champion’s marginal title probability.</p>
        <div className="bracket-scroll" role="region" aria-label="Predicted knockout bracket" tabIndex={0}>
          <div className="knockout-grid">
            {rounds.map(([round, label], roundIndex) => <section className={`bracket-round bracket-round-${roundIndex}`} key={round} aria-label={label}>
              <h2>{label}</h2><div className="bracket-slots">
                {forecast.matches.filter((match) => match.round === round).map((match) =>
                  <div className="bracket-slot" key={match.id}>
                    <button className={`bracket-tie ${selected?.id === match.id ? "is-selected" : ""}`}
                      aria-pressed={selected?.id === match.id} aria-controls="bracket-detail"
                      aria-label={`${label}: ${clubs.get(match.team_a_id)?.name} versus ${clubs.get(match.team_b_id)?.name}. Predicted winner ${clubs.get(match.winner_id)?.name}`}
                      onClick={() => change("match", match.id)}>
                      {[match.team_a_id, match.team_b_id].map((id, i) => <span className={`bracket-club ${match.winner_id === id ? "bracket-winner" : ""}`} key={id}>
                        {clubs.get(id)?.crest && <img src={clubs.get(id)?.crest || ""} alt="" width={22} height={22} loading="lazy" />}
                        <span>{clubs.get(id)?.name}<small>{match.winner_id === id ? "Predicted winner" : ""}</small></span>
                        <b>{percent.format(i === 0 ? match.p_a : match.p_b)}</b>
                      </span>)}
                    </button>
                  </div>)}
              </div>
            </section>)}
          </div>
        </div>
        <dialog ref={detailRef} id="bracket-detail" className="bracket-detail" onClose={closeSelection} aria-label="Selected matchup details">
          <button className="bracket-close" onClick={closeSelection}>Close matchup</button>
          {selected ? <><h2>{clubs.get(selected.team_a_id)?.name} vs {clubs.get(selected.team_b_id)?.name}</h2>
            <p>{selected.single_match ? "Single neutral final · extra time and penalties if needed."
              : `Two legs · ${current.rules.away_goals ? "Historical away-goals rule applies" : "No away-goals rule"}${selected.neutral_first || selected.neutral_second ? " · Includes a recorded neutral leg" : " · Home advantage in each leg"}.`}</p>
            <dl>{[selected.team_a_id, selected.team_b_id].map((id, i) => <div key={id}>
              <dt>{clubs.get(id)?.name}</dt><dd>{rating.format(clubs.get(id)?.elo || 0)} Elo · {percent.format(i === 0 ? selected.p_a : selected.p_b)} to {selected.single_match ? "win" : "advance"}</dd>
            </div>)}</dl></> : <p>Select a matchup to inspect its frozen ratings and probabilities.</p>}
        </dialog>
      </>}
  </>;
}
