import { useEffect, useState } from "react";
import "./club-analysis.css";
import RatingChart from "./RatingChart";
import type { Club, Result, TeamDetail } from "./types";

type Observation = { id: number; date: string; opponent: string; xg: number; xga: number };
type Metric = "elo" | "form" | "xg";
const metrics = { elo: "Elo trajectory", form: "Match form", xg: "Expected goals" } as const;
const number = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
const calendar = new Intl.DateTimeFormat(undefined, { dateStyle: "medium" });
const day = (value: string) => calendar.format(new Date(value.slice(0, 10) + "T12:00:00"));

export default function ClubAnalysis({ club, history, results }: {
  club: Club; history: TeamDetail["history"]; results: Result[];
}) {
  const [metric, setMetric] = useState<Metric>("elo");
  const [range, setRange] = useState("all");
  const [active, setActive] = useState(0);
  const [xg, setXg] = useState<{ club: number; rows: Observation[] }>();
  const [error, setError] = useState("");
  useEffect(() => {
    if (metric !== "xg") return;
    const controller = new AbortController();
    fetch("/api/teams/" + club.id + "/xg", { signal: controller.signal })
      .then((response) => {
        if (!response.ok) throw new Error("Could not load xG observations.");
        return response.json() as Promise<Observation[]>;
      })
      .then((rows) => { setXg({ club: club.id, rows }); setError(""); })
      .catch((cause: Error) => { if (cause.name !== "AbortError") setError(cause.message); });
    return () => controller.abort();
  }, [club.id, metric]);
  const recent = [...results].sort((a, b) => b.date.localeCompare(a.date)).slice(0, 10);
  const observations = xg?.club === club.id ? xg.rows : undefined;
  const rows = observations?.slice(0, range === "all" ? 20 : 10) ?? [];
  const selected = metric === "xg" ? rows[active] ?? rows[0] : recent[active] ?? recent[0];
  const maximum = Math.max(1, ...rows.flatMap((row) => [row.xg, row.xga]));
  return <div className="optional-club-analysis">
    <div className="analysis-heading">
      <h2>Club performance</h2>
      <div className="editorial-tabs" aria-label="Performance metric">
        {(Object.keys(metrics) as Metric[]).map((key) => <button key={key} type="button"
          aria-pressed={metric === key} onClick={() => { setMetric(key); setActive(0); setError(""); }}>
          {metrics[key]}
        </button>)}
      </div>
    </div>
    {metric === "elo" ? <>
      <label className="analysis-range">Match window <select value={range} onChange={(e) => setRange(e.target.value)}>
        <option value="all">Full season</option><option value="recent">Last 10</option>
      </select></label>
      <div className="history-chart analysis-chart"><RatingChart history={range === "all" ? history : history.slice(-11)} /></div>
    </> : metric === "form" ? <>
      <p className="analysis-caption">Latest rated fixtures · newest first</p>
      <div className="form-timeline" aria-label="Recent fixtures">
        {recent.map((result, index) => {
          const home = result.home_id === club.id;
          const scored = home ? result.home_goals : result.away_goals;
          const conceded = home ? result.away_goals : result.home_goals;
          const opponent = home ? result.away : result.home;
          const outcome = scored > conceded ? "W" : scored < conceded ? "L" : "D";
          return <button key={result.match_id} type="button" aria-pressed={index === active}
            onClick={() => setActive(index)} className={"timeline-" + outcome.toLowerCase()}>
            <strong>{outcome} · {scored}–{conceded}</strong><span>{opponent}</span><small>{home ? "Home" : "Away"}</small>
          </button>;
        })}
      </div>
      {selected && "home" in selected && <p aria-live="polite" className="analysis-readout">
        {day(selected.date)} · {selected.home} {selected.home_goals}–{selected.away_goals} {selected.away} · {number.format(selected.home_id === club.id ? selected.home_change : selected.away_change)} Elo change
      </p>}
      {!recent.length && <p>No completed fixtures available.</p>}
    </> : <>
      {error ? <p role="alert">{error} Switch metrics and return to retry.</p> : observations === undefined ?
        <p role="status">Loading xG observations…</p> : !rows.length ?
        <p>No archived xG observations for this club.</p> : <>
          <div className="analysis-heading">
            <p className="analysis-caption">Understat archive · Latest observation {day(rows[0].date)}</p>
            <label className="analysis-range">Observations <select value={range} onChange={(e) => { setRange(e.target.value); setActive(0); }}>
              <option value="all">Last 20</option><option value="recent">Last 10</option>
            </select></label>
          </div>
          <div className="xg-columns" aria-label="Expected goals for and against by match">
            {rows.map((row, index) => <button key={row.id} type="button" aria-pressed={index === active}
              aria-label={row.opponent + ", " + day(row.date) + ", xG " + number.format(row.xg) + ", xGA " + number.format(row.xga)}
              onClick={() => setActive(index)}>
              <span aria-hidden="true"><i style={{ height: 100 * row.xg / maximum + "%" }} />
                <i style={{ height: 100 * row.xga / maximum + "%" }} /></span>
              <small>{index + 1}</small>
            </button>)}
          </div>
          {selected && "xg" in selected && <p aria-live="polite" className="analysis-readout">
            {day(selected.date)} · {selected.opponent} · <strong>{number.format(selected.xg)} xG</strong> · {number.format(selected.xga)} xGA
          </p>}
        </>}
    </>}
  </div>;
}
