import { useState } from "react";
import { Link } from "react-router-dom";
import { leaguePath } from "./navigation";
import type { Club } from "./types";

const number = new Intl.NumberFormat(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 });

export default function EloPlot({ clubs, query }: { clubs: Club[]; query: string }) {
  const [selected, setSelected] = useState<number | null>(null);
  const ordered = [...clubs].sort((a, b) => a.rank - b.rank);
  const low = Math.min(...ordered.map((club) => club.rating));
  const high = Math.max(...ordered.map((club) => club.rating));
  const minimum = Math.floor(low / 50) * 50 - 25;
  const maximum = Math.ceil(high / 50) * 50 + 25;
  return <section className="elo-plot" aria-labelledby="elo-plot-heading">
    <h3 id="elo-plot-heading">Club strength on one scale</h3>
    <p>Select a dot to keep its rating in view. Search highlights matching clubs.</p>
    <div className="elo-axis" aria-hidden="true"><div><span>{minimum}</span><span>{(minimum + maximum) / 2}</span><span>{maximum} Elo</span></div></div>
    <ol>
      {ordered.map((club) => {
        const active = selected === club.id;
        const match = query.trim() && club.name.toLowerCase().includes(query.trim().toLowerCase());
        const detail = number.format(club.rating) + " Elo · rank " + club.rank;
        return <li key={club.id} className={active || match ? "elo-highlight" : undefined}>
          <Link to={leaguePath("/teams/" + club.id, club.league_id)}>{club.name}</Link>
          <div className="elo-lane">
            <button type="button" aria-label={club.name + " " + detail} aria-pressed={active}
              style={{ left: 100 * (club.rating - minimum) / (maximum - minimum) + "%" }}
              onClick={() => setSelected(active ? null : club.id)}>
              <span className="elo-tooltip" aria-hidden="true">{club.name} · {detail}</span>
            </button>
          </div>
          <span>{number.format(club.rating)}</span>
        </li>;
      })}
    </ol>
  </section>;
}
