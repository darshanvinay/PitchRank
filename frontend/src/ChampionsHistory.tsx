import { apiFetch } from "./api";
import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";

interface ArchiveSeason {
  season: string;
  source_available: boolean;
  imported_matches: number;
  expected_matches: number;
  complete: boolean;
  status: string;
  last_imported_at: string | null;
  source_url: string;
  limitations: string[];
}
interface ArchiveMatch {
  match_id: number;
  date: string;
  round: string;
  group: string | null;
  leg: number | null;
  tie_id: string | null;
  tie_format: string | null;
  home_id: number;
  away_id: number;
  home: string;
  away: string;
  home_crest: string | null;
  away_crest: string | null;
  home_goals: number;
  away_goals: number;
  extra_time_home: number | null;
  extra_time_away: number | null;
  penalties_home: number | null;
  penalties_away: number | null;
  erratum?: { reason: string; source_url: string } | null;
  source_url: string;
  source_line: number;
}
const rounds: Record<string, string> = {
  group: "Group stage",
  league: "League phase",
  playoff: "Knockout play-offs",
  round_of_16: "Round of 16",
  quarterfinal: "Quarterfinal",
  semifinal: "Semifinal",
  final: "Final",
};
async function load<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await apiFetch(url, { signal, cache: "no-store" });
  if (!response.ok)
    throw new Error(
      "History could not be loaded. Check the backend and retry.",
    );
  return response.json() as Promise<T>;
}
export default function ChampionsHistory() {
  const [params, setParams] = useSearchParams();
  const season = params.get("season") || "2025-2026";
  const stage = params.get("stage") || "";
  const team = params.get("team") || "";
  const [seasons, setSeasons] = useState<ArchiveSeason[]>([]);
  const [dataset, setDataset] = useState<{
    season: string;
    matches: ArchiveMatch[];
    teams: { id: number; name: string }[];
  } | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    Promise.all([
      load<{ seasons: ArchiveSeason[] }>("/api/ucl/seasons", controller.signal),
      load<NonNullable<typeof dataset>>(
        `/api/ucl/matches?season=${encodeURIComponent(season)}`,
        controller.signal,
      ),
    ])
      .then(([coverage, matches]) => {
        setSeasons(coverage.seasons);
        setDataset(matches);
      })
      .catch((e) => {
        if (e.name !== "AbortError") setError(e.message);
      });
    return () => controller.abort();
  }, [season, revision]);
  const selected = seasons.find((s) => s.season === season);
  const matches =
    dataset?.season === season
      ? dataset.matches.filter(
          (m) =>
            (!stage || m.round === stage) &&
            (!team || m.home_id === Number(team) || m.away_id === Number(team)),
        )
      : [];
  const pages = Math.max(1, Math.ceil(matches.length / 30));
  const page = Math.max(
    1,
    Math.min(pages, Number.parseInt(params.get("page") || "1", 10) || 1),
  );
  const visibleMatches = matches.slice((page - 1) * 30, page * 30);
  function filter(key: string, value: string) {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    if (key !== "page") next.delete("page");
    if (key === "season") {
      next.delete("stage");
      next.delete("team");
    }
    setParams(next);
  }
  function club(id: number, name: string, crest: string | null) {
    return (
      <button
        type="button"
        className="history-club"
        onClick={() => filter("team", String(id))}
        aria-label={`View ${name} Champions League history`}
      >
        {crest && (
          <img src={crest} alt="" width={24} height={24} loading="lazy" />
        )}
        {name}
      </button>
    );
  }
  return (
    <>
      <section className="programme-lead">
        <h1>Champions League history</h1>
        <p>
          Real main-draw results, with regulation, extra-time and shootout
          scores kept separate.
        </p>
      </section>
      <section className="programme-archive" aria-labelledby="archive-heading">
        <div className="section-title">
          <div>
            <h2 id="archive-heading">Historical results</h2>
            <p>
              {selected
                ? `${selected.imported_matches} / ${selected.expected_matches} main-draw matches · ${selected.complete ? "Complete match coverage" : selected.source_available ? "Not imported" : "Unavailable in this source"}`
                : "Loading archive…"}
            </p>
          </div>
        </div>
        <div className="table-panel">
          <div className="table-toolbar history-filters">
            <label>
              Season
              <select
                aria-label="Historical Champions League season"
                value={season}
                onChange={(e) => filter("season", e.target.value)}
              >
                {seasons.length ? (
                  seasons.map((s) => (
                    <option key={s.season} value={s.season}>
                      {s.season.replace("-", "/")}{" "}
                      {!s.source_available ? "· unavailable" : ""}
                    </option>
                  ))
                ) : (
                  <option value={season}>{season}</option>
                )}
              </select>
            </label>
            <label>
              Stage
              <select
                aria-label="Tournament stage"
                value={stage}
                onChange={(e) => filter("stage", e.target.value)}
              >
                <option value="">All stages</option>
                {Object.entries(rounds).map(([value, label]) => (
                  <option key={value} value={value}>
                    {label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Club
              <select
                aria-label="Historical club"
                value={team}
                onChange={(e) => filter("team", e.target.value)}
              >
                <option value="">All clubs</option>
                {dataset?.season === season &&
                  dataset.teams.map((t) => (
                    <option key={t.id} value={t.id}>
                      {t.name}
                    </option>
                  ))}
              </select>
            </label>
            {(stage || team) && (
              <button onClick={() => setParams({ season })}>
                Clear filters
              </button>
            )}
          </div>
          {error ? (
            <div className="error-state" role="alert">
              <p>{error}</p>
              <button onClick={() => setRevision((v) => v + 1)}>
                Try again
              </button>
            </div>
          ) : dataset?.season !== season ? (
            <p className="history-notice" role="status">
              Loading historical matches…
            </p>
          ) : !selected?.complete ? (
            <p className="history-notice">
              {selected?.source_available
                ? "This season has not been imported. Run the historical ingestion command to load it."
                : "Openfootball has no file for this season. No substitute results have been used."}
            </p>
          ) : (
            <>
              <div className="table-scroll">
                <table className="history-matches">
                  <caption className="sr-only">
                    Champions League results in chronological order. Scores are
                    at 90 minutes; extra time and penalties are additional
                    labels.
                  </caption>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Stage / leg</th>
                      <th>Home</th>
                      <th className="numeric">90 min</th>
                      <th>Away</th>
                      <th>Extra time / penalties</th>
                    </tr>
                  </thead>
                  <tbody>
                    {visibleMatches.map((m) => (
                      <tr key={m.match_id}>
                        <td>
                          <time dateTime={m.date}>
                            {new Intl.DateTimeFormat(undefined, {
                              day: "numeric",
                              month: "short",
                              year: "numeric",
                            }).format(new Date(`${m.date}T12:00:00`))}
                          </time>
                        </td>
                        <td>
                          {rounds[m.round]}
                          {m.group && ` · ${m.group}`}
                          <small>
                            {m.leg
                              ? `Leg ${m.leg} · derived from pair dates`
                              : m.tie_format === "single"
                                ? "Single match"
                                : ""}
                          </small>
                        </td>
                        <td>{club(m.home_id, m.home, m.home_crest)}</td>
                        <td className="numeric">
                          {m.home_goals}–{m.away_goals}
                        </td>
                        <td>{club(m.away_id, m.away, m.away_crest)}</td>
                        <td>
                          {m.extra_time_home !== null ? (
                            <span>
                              After ET: {m.extra_time_home}–{m.extra_time_away}
                            </span>
                          ) : (
                            "—"
                          )}
                          {m.penalties_home !== null && (
                            <small>
                              Penalties: {m.penalties_home}–{m.penalties_away}
                            </small>
                          )}
                          {m.erratum && (
                            <small>
                              <a
                                href={m.erratum.source_url}
                                target="_blank"
                                rel="noreferrer"
                              >
                                Reviewed source erratum
                              </a>
                            </small>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              {!matches.length && (
                <p className="history-notice">
                  No matches match these filters.
                </p>
              )}
              <p className="table-footnote">
                {visibleMatches.length} of {matches.length} matches shown ·
                Click a club to filter its history. Leg numbers are derived;
                unreported fields remain empty.
              </p>
              {pages > 1 && (
                <nav
                  className="history-pagination"
                  aria-label="Historical match pages"
                >
                  <button
                    disabled={page === 1}
                    onClick={() => filter("page", String(page - 1))}
                  >
                    Previous page
                  </button>
                  <span aria-live="polite">
                    Page {page} of {pages}
                  </span>
                  <button
                    disabled={page === pages}
                    onClick={() => filter("page", String(page + 1))}
                  >
                    Next page
                  </button>
                </nav>
              )}
            </>
          )}
        </div>
      </section>
      <div className="history-notice">
        <p>
          Coverage means complete main-draw fixture counts and validated
          stages/ties, not independent verification of every score. Qualifiers
          are excluded. {selected?.limitations.join(" ")}
        </p>
        <p>
          <a
            className="text-link"
            href={
              selected?.source_url ||
              "https://github.com/openfootball/champions-league"
            }
            target="_blank"
            rel="noreferrer"
          >
            Openfootball source · CC0
          </a>
          {selected?.last_imported_at && (
            <>
              {" "}
              · Imported{" "}
              <time dateTime={selected.last_imported_at}>
                {new Intl.DateTimeFormat(undefined, {
                  dateStyle: "medium",
                  timeStyle: "short",
                }).format(new Date(selected.last_imported_at))}
              </time>
            </>
          )}
        </p>
      </div>
    </>
  );
}
