import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";

type Club = {
  id: number; name: string; crest: string | null; elo: number;
  title: number; rank: number; points: number; top8: number; playoffs: number;
  r16: number; quarter: number; semi: number; final: number;
};
type Tie = { round: string; first: number; second: number; winner: number; p_first: number; fallback: boolean };
type Bracket = { champion: number; finalists: number[]; bracket: Tie[] };
type Model = { clubs: Club[]; champion: number; bracket_modes: Record<"likely" | "simulated", Bracket>; residual_tiebreak_rate: number };
type Projection = {
  generated_at: string; trials: number; completed: number; xg_clubs: number;
  latest: Record<string, string | null>; models: Record<"xg" | "baseline", Model>;
};
const rounds = ["Play-offs", "Round of 16", "Quarter-finals", "Semi-finals", "Final"];
const pct = new Intl.NumberFormat(undefined, { style: "percent", maximumFractionDigits: 2 });
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 1 });
const timestamp = new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" });

function ClubName({ club }: { club: Club }) {
  return <span className="projection-club">
    {club.crest && <img src={club.crest} alt="" width={24} height={24} loading="lazy" />}
    <span>{club.name}</span>
  </span>;
}

export default function SeasonProjection() {
  const [data, setData] = useState<Projection | null>(null);
  const [error, setError] = useState("");
  const [model, setModel] = useState<"xg" | "baseline">("xg");
  const [mode, setMode] = useState<"likely" | "simulated">("likely");
  const [view, setView] = useState<"title" | "league">("title");
  const [selected, setSelected] = useState<Tie | null>(null);
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const controller = new AbortController();
    async function load() {
      try {
        const response = await fetch("/api/ucl/projection", { signal: controller.signal });
        if (!response.ok) throw new Error("Season projection unavailable.");
        setData(await response.json() as Projection);
        setError("");
      } catch (err) {
        if (!controller.signal.aborted) setError(err instanceof Error ? err.message : "Could not load projection.");
      }
    }
    void load();
    const timer = window.setInterval(() => void load(), 60_000);
    return () => { controller.abort(); window.clearInterval(timer); };
  }, []);
  const forecast = data?.models[model];
  const clubs = forecast?.clubs ?? [];
  const champion = forecast && clubs[forecast.champion];
  const bracket = forecast?.bracket_modes?.[mode];
  const bracketName = mode === "likely" ? "Most Likely Bracket" : "Simulated Bracket";
  const ordered = [...clubs].sort((a, b) => view === "title" ? b.title - a.title : a.rank - b.rank);
  return <>
    <div className="title-row"><div><h1>Champions League 2026/27</h1>
      <p>League phase and knockout projections</p></div></div>
    <div className="table-toolbar history-filters bracket-controls">
      <label>Prediction model<select value={model} name="projection-model" onChange={(e) => {
        setModel(e.target.value === "baseline" ? "baseline" : "xg");
      }}>
        <option value="xg">Frozen xG ensemble · experimental</option>
        <option value="baseline">Model A · Elo</option>
      </select></label>
      <label>Bracket mode<select value={mode} name="bracket-mode" onChange={(e) => {
        setMode(e.target.value === "simulated" ? "simulated" : "likely");
      }}>
        <option value="likely">Most Likely Bracket</option>
        <option value="simulated">Simulated Bracket</option>
      </select></label>
      <Link to="/champions-league/bracket?season=2020-2021">Historical brackets</Link>
    </div>
    {error && <p className="error-notice" role="alert">{error}</p>}
    {(!data || !forecast || !champion) ? (!error && <p role="status">Loading season projection…</p>) : <>
      <section className="bracket-summary projection-summary" aria-label="Forecast summary">
        <div><span>Title favorite</span><strong><ClubName club={champion} /></strong></div>
        <div><span>Championship probability</span><strong className="bracket-winner">{pct.format(champion.title)}</strong></div>
        <div><span>Simulation run</span><strong><time dateTime={data.generated_at}>
          {timestamp.format(new Date(data.generated_at))}</time></strong></div>
      </section>
      <p className="bracket-explainer">
        {data.trials.toLocaleString()} simulations per model · {data.completed}/144 league results confirmed
        {data.latest.ucl && <> through <time dateTime={data.latest.ucl}>{data.latest.ucl}</time></>}.
        {model === "xg" && <> {data.xg_clubs}/36 clubs meet the xG freshness threshold. Matchups with insufficient xG use Model A.</>}
      </p>
      {bracket ? <section aria-labelledby="scenario-heading">
        <h2 id="scenario-heading">{bracketName}</h2>
        <p className="bracket-explainer">{mode === "likely"
          ? "The higher-probability team advances in each matchup on this simulated draw."
          : "One possible tournament outcome. Winners are sampled from their matchup probabilities, so upsets can occur."}
          {" "}Final: {bracket.finalists.map((id) => clubs[id].name).join(" vs ")}.</p>
        <p><strong>Bracket champion</strong> · {clubs[bracket.champion].name}</p>
        <div className="projection-scroll" role="region" aria-label="Simulated bracket rounds" tabIndex={0}>
          <div className="projection-rounds">
            {rounds.map((round) => <section className="bracket-round" key={round} aria-label={round}>
              <h3>{round}</h3>
              {bracket.bracket.filter((tie) => tie.round === round).map((tie) =>
                <button key={tie.first + "-" + tie.second} className="bracket-tie" aria-haspopup="dialog" onClick={() => {
                  setSelected(tie); dialog.current?.showModal();
                }}>
                  {[tie.first, tie.second].map((id, index) =>
                    <span className={"bracket-club" + (tie.winner === id ? " bracket-winner" : "")} key={id}>
                      <span><ClubName club={clubs[id]} />{tie.winner === id && <small>Advances</small>}</span>
                      <b>{pct.format(index === 0 ? tie.p_first : 1 - tie.p_first)}</b>
                    </span>)}
                </button>)}
            </section>)}
          </div>
        </div>
      </section> : <p role="status">Bracket modes will appear after the next projection refresh.</p>}
      <dialog ref={dialog} className="bracket-detail" aria-label="Matchup details">
        <form method="dialog"><button className="bracket-close">Close matchup</button></form>
        {selected && <>
          <h2>{clubs[selected.first].name} vs {clubs[selected.second].name}</h2>
          <p>{selected.round} · {selected.round === "Final" ? "Neutral venue" : clubs[selected.second].name + " hosts the return leg"}</p>
          <p>{pct.format(selected.p_first)} to advance for {clubs[selected.first].name}.
            {selected.fallback && " Uses Model A because fresh xG is unavailable."}</p>
          <dl>{[selected.first, selected.second].map((id) => <div key={id}>
            <dt>{clubs[id].name}</dt><dd>{number.format(clubs[id].elo)} Elo · {pct.format(clubs[id].title)} title</dd>
          </div>)}</dl>
        </>}
      </dialog>
      <section className="projection-table" aria-labelledby="projection-table-title">
        <div className="table-toolbar history-filters bracket-controls">
          <h2 id="projection-table-title">All 36 clubs</h2>
          <label>Sort by<select value={view} name="projection-sort" onChange={(e) => {
            setView(e.target.value === "league" ? "league" : "title");
          }}>
            <option value="title">Title probability</option>
            <option value="league">Mean league position</option>
          </select></label>
        </div>
        <div className="projection-scroll" role="region" aria-label="Club probabilities and league projections" tabIndex={0}>
          <table><thead><tr>{["Club", "Title", "Final", "Semi-final", "Quarter-final", "Round of 16",
            "Mean rank", "Mean points", "Top 8", "Play-offs"].map((h) => <th key={h} scope="col">{h}</th>)}</tr></thead>
            <tbody>{ordered.map((club) => <tr key={club.id}><th scope="row"><ClubName club={club} /></th>
              {[club.title, club.final, club.semi, club.quarter, club.r16].map((p, i) =>
                <td key={i}>{pct.format(p)}</td>)}
              <td>{number.format(club.rank)}</td><td>{number.format(club.points)}</td>
              <td>{pct.format(club.top8)}</td><td>{pct.format(club.playoffs)}</td>
            </tr>)}</tbody></table>
        </div>
      </section>
      <p className="bracket-explainer">Exact ties after the available sporting criteria occurred in {pct.format(forecast.residual_tiebreak_rate)} of simulations.
        Disciplinary and coefficient data are unavailable in the fixture feed.</p>
    </>}
  </>;
}
