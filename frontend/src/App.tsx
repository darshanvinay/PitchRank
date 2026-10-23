import { lazy, Suspense, useEffect, useState, useRef } from "react";
import {
  Link,
  NavLink,
  Route,
  Routes,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";
import {
  ArrowLeft,
  ArrowUpRight,
  BarChart3,
  Check,
  ChevronRight,
  CircleHelp,
  ExternalLink,
  Moon,
  RefreshCw,
  Search,
  Sun,
} from "lucide-react";

import "@fontsource/geist/400.css";
import "@fontsource/geist/500.css";
import "@fontsource/geist/700.css";
import type { Club, League, Result, TeamDetail } from "./types";
import { competitions, selectedLeague, leaguePath } from "./navigation";
import type { LeagueId } from "./navigation";
import "./style.css";

const RatingChart = lazy(() => import("./RatingChart"));

const number = new Intl.NumberFormat(undefined, {
  maximumFractionDigits: 1,
  minimumFractionDigits: 1,
});
const integer = new Intl.NumberFormat();
const money = (value: number | null) =>
  value === null
    ? "Unavailable"
    : new Intl.NumberFormat(undefined, {
        style: "currency",
        currency: "EUR",
        notation: "compact",
        maximumFractionDigits: 1,
      }).format(value);
const date = (value: string | null, short = false) =>
  value
    ? new Intl.DateTimeFormat(undefined, {
        day: "numeric",
        month: short ? "short" : "long",
        ...(!short ? { year: "numeric" } : {}),
      }).format(new Date(`${value.slice(0, 10)}T12:00:00`))
    : "No results yet";
const delta = (value: number) =>
  `${value > 0 ? "+" : ""}${number.format(value)}`;
async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => ({
      detail: "Could not reach PitchRank. Check the backend and try again.",
    }));
    throw new Error(body.detail || "Something went wrong. Try again.");
  }
  return response.json() as Promise<T>;
}
function Crest({
  club,
  size = 28,
}: {
  club: Pick<Club, "name" | "crest_url">;
  size?: number;
}) {
  const [failed, setFailed] = useState(false);
  return club.crest_url && !failed ? (
    <img
      className="crest"
      width={size}
      height={size}
      src={club.crest_url}
      alt=""
      onError={() => setFailed(true)}
    />
  ) : (
    <span
      className="crest-fallback"
      style={{ width: size, height: size }}
      aria-hidden="true"
    >
      {club.name.slice(0, 2)}
    </span>
  );
}
function Change({ value }: { value: number }) {
  return (
    <span className={value > 0 ? "positive" : value < 0 ? "negative" : "muted"}>
      {delta(value)}
    </span>
  );
}
function Form({ items }: { items: string[] }) {
  return (
    <span
      className="form"
      aria-label={`Recent results, oldest first: ${items.join(", ") || "none"}`}
    >
      {items.map((item, index) => (
        <span key={index} className={`form-${item.toLowerCase()}`}>
          {item}
        </span>
      ))}
    </span>
  );
}
function Loading() {
  return (
    <div className="loading" role="status" aria-label="Loading ratings">
      <div className="skeleton-title" />
      {Array.from({ length: 8 }, (_, i) => (
        <div className="skeleton-row" key={i} />
      ))}
      <span className="sr-only">Loading ratings…</span>
    </div>
  );
}
function ErrorState({
  message,
  retry,
}: {
  message: string;
  retry: () => void;
}) {
  return (
    <div className="error-state" role="alert">
      <CircleHelp aria-hidden="true" size={22} />
      <h2>Data couldn’t be loaded</h2>
      <p>{message}</p>
      <button onClick={retry}>Try again</button>
    </div>
  );
}
export default function App() {
  const [league, setLeague] = useState<League | null>(null);
  const [error, setError] = useState("");
  const [refreshError, setRefreshError] = useState("");
  const [busy, setBusy] = useState(false);
  const [dark, setDark] = useState(() => {
    try {
      return (
        localStorage.getItem("pitchrank-theme") === "dark" ||
        (!localStorage.getItem("pitchrank-theme") &&
          matchMedia("(prefers-color-scheme: dark)").matches)
      );
    } catch {
      return false;
    }
  });
  const [notice, setNotice] = useState("");
  const location = useLocation();
  const navigate = useNavigate();
  const leagueId = selectedLeague(location.search);
  const viewId = location.pathname === "/europe" ? "europe" : leagueId;
  const scope =
    viewId === "europe"
      ? {
          name: "European Rankings",
          country: "Europe",
          source: "https://fixturedownload.com/results/champions-league-2026",
        }
      : competitions[leagueId];
  const activeLeague = useRef(viewId);
  activeLeague.current = viewId;
  const [revision, setRevision] = useState(0);
  const path = (url: string) => leaguePath(url, leagueId);
  useEffect(() => {
    document.documentElement.dataset.theme = dark ? "dark" : "light";
    document
      .querySelector('meta[name="theme-color"]')
      ?.setAttribute("content", dark ? "#111111" : "#f8f8f8");
    try {
      localStorage.setItem("pitchrank-theme", dark ? "dark" : "light");
    } catch {
      /* Browsing remains usable without storage. */
    }
  }, [dark]);
  useEffect(() => {
    window.scrollTo(0, 0);
  }, [location.pathname]);
  useEffect(() => {
    const controller = new AbortController();
    setError("");
    setRefreshError("");
    setNotice("");
    request<League>(`/api/league?league=${viewId}`, {
      signal: controller.signal,
    })
      .then(setLeague)
      .catch((error) => {
        if (error.name !== "AbortError") setError(error.message);
      });
    return () => controller.abort();
  }, [viewId, revision]);
  useEffect(() => {
    document.title = `PitchRank — ${scope.name} strength ratings`;
  }, [scope.name, location.pathname]);
  async function refresh() {
    setBusy(true);
    setRefreshError("");
    setNotice("");
    try {
      const updated = await request<League>(`/api/refresh?league=${viewId}`, {
        method: "POST",
      });
      if (activeLeague.current === viewId) {
        setLeague(updated);
        setNotice(`${scope.name} results refreshed and ratings recalculated.`);
      }
    } catch (error) {
      if (activeLeague.current === viewId)
        setRefreshError((error as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <div className="app-shell">
        <aside className="sidebar">
          <Link className="brand" to={path("/")} aria-label="PitchRank home">
            <svg viewBox="0 0 30 32" width="30" height="32" aria-hidden="true">
              <path
                d="M4 28V4h13c8 0 12 10 5 15-2 1-4 1-8 1H4M9 4v24M9 9h7c4 0 5 6 1 6H9"
                fill="none"
                stroke="currentColor"
                strokeWidth="2.3"
              />
            </svg>
            <span translate="no">
              PitchRank<span className="brand-period">.</span>
            </span>
          </Link>
          <div className="workspace">
            <label className="context-label" htmlFor="league-selector">
              League · {competitions[leagueId].country}
            </label>
            <select
              id="league-selector"
              name="league"
              className="league-selector"
              aria-label={`League · ${competitions[leagueId].country}`}
              value={leagueId}
              disabled={busy}
              onChange={(event) =>
                navigate(leaguePath("/", event.target.value as LeagueId))
              }
            >
              {(Object.keys(competitions) as LeagueId[]).map((id) => (
                <option key={id} value={id}>
                  {competitions[id].name}
                </option>
              ))}
            </select>
            <span>
              {league?.season.replace("-", " / ") || "Current season"}
            </span>
          </div>
          <nav aria-label="Main navigation">
            <NavLink to={path("/")} end>
              <BarChart3 aria-hidden="true" size={17} />
              Leaderboard
              <ChevronRight
                aria-hidden="true"
                className="nav-chevron"
                size={15}
              />
            </NavLink>
            <NavLink to="/europe">
              <BarChart3 aria-hidden="true" size={17} />
              European Rankings
            </NavLink>
            <NavLink to={path("/method")}>
              <CircleHelp aria-hidden="true" size={17} />
              <span className="nav-method-full">How ratings work</span>
              <span className="nav-method-short">Method</span>
            </NavLink>
          </nav>
          <div className="sidebar-bottom">
            <div className="sidebar-note">
              <span className="small-pitch" aria-hidden="true">
                ◯
              </span>
              <p>
                The game, in perspective.
                <br />
                <span>Results meet squad strength.</span>
              </p>
            </div>
            <button
              className="theme-toggle"
              onClick={() => setDark(!dark)}
              aria-label={`Switch to ${dark ? "light" : "dark"} mode`}
            >
              {dark ? (
                <Sun aria-hidden="true" size={17} />
              ) : (
                <Moon aria-hidden="true" size={17} />
              )}
              <span>{dark ? "Light" : "Dark"} appearance</span>
            </button>
            <p className="version-note">Independent football analytics</p>
          </div>
        </aside>
        <main id="main" tabIndex={-1}>
          <header className="page-top">
            <span className="breadcrumb">
              Football <ChevronRight aria-hidden="true" size={13} />{" "}
              {scope.name}
            </span>
            <div className="top-actions">
              <span className="data-stamp">
                {league?.league_id === viewId
                  ? `Through ${date(league.results_through, true)}`
                  : "Loading data…"}
              </span>
              <button
                className="refresh-button"
                onClick={refresh}
                disabled={busy}
                aria-busy={busy}
              >
                <RefreshCw
                  aria-hidden="true"
                  size={15}
                  className={busy ? "rotating" : ""}
                />
                {busy ? "Refreshing…" : "Refresh data"}
              </button>
            </div>
          </header>
          <div className="announcements" aria-live="polite">
            {notice && (
              <p className="success-notice">
                <Check aria-hidden="true" size={15} />
                {notice}
              </p>
            )}
            {refreshError && <p className="error-notice">{refreshError}</p>}
          </div>
          {error ? (
            <ErrorState
              message={error}
              retry={() => setRevision((v) => v + 1)}
            />
          ) : !league || league.league_id !== viewId ? (
            <Loading />
          ) : (
            <Routes>
              <Route path="/" element={<Leaderboard league={league} />} />
              <Route path="/europe" element={<Leaderboard league={league} />} />
              <Route
                path="/teams/:id"
                element={<TeamPage key={leagueId} league={league} />}
              />
              <Route path="/method" element={<Method league={league} />} />
              <Route
                path="*"
                element={
                  <div className="error-state">
                    <h1>Page not found</h1>
                    <Link to={path("/")}>Back to leaderboard</Link>
                  </div>
                }
              />
            </Routes>
          )}
          <footer className="page-footer">
            <span>PitchRank · Strength beyond the standings.</span>
            <a href={scope.source} target="_blank" rel="noreferrer">
              Results:{" "}
              {viewId === "europe" ? "Fixture Download" : "Football-Data"}{" "}
              <ExternalLink aria-hidden="true" size={12} />
            </a>
          </footer>
        </main>
      </div>
    </>
  );
}
function Leaderboard({ league }: { league: League }) {
  const european = league.league_id === "europe";
  const path = (url: string) =>
    leaguePath(url, league.league_id === "europe" ? "epl" : league.league_id);
  const [params, setParams] = useSearchParams();
  const query = params.get("q") || "";
  const sort = params.get("sort") || "rating";
  const clubs = league.clubs
    .filter((c) => c.name.toLowerCase().includes(query.toLowerCase()))
    .filter(
      (c) =>
        !european ||
        !params.get("filterLeague") ||
        c.league_id === params.get("filterLeague"),
    )
    .sort((a, b) =>
      sort === "value"
        ? (b.squad_value ?? 0) - (a.squad_value ?? 0)
        : sort === "change"
          ? european
            ? b.last_change - a.last_change
            : b.change - a.change
          : a.rank - b.rank,
    );
  const leader = league.clubs[0];
  const changeLeader = [...league.clubs].sort((a, b) =>
    european ? b.last_change - a.last_change : b.change - a.change,
  )[0];
  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };
  return (
    <>
      <section className="title-row">
        <div>
          <div className="eyebrow">Club strength ratings</div>
          <h1>{league.name}</h1>
          <p>
            {european
              ? "The top 25 across five leagues, connected by Champions League results."
              : "A clearer view of who’s performing, and against whom."}
          </p>
        </div>
        <span className="season-label">
          {league.season.replace("-", "/")} season
        </span>
      </section>
      <div className="insight-strip">
        <div>
          <span className="stat-label">Highest rated</span>
          <div className="strip-club">
            <Crest club={leader} size={25} />
            <Link to={leaguePath(`/teams/${leader.id}`, leader.league_id)}>
              {leader.name}
            </Link>
            <span className="strip-number">{number.format(leader.rating)}</span>
          </div>
        </div>
        <div>
          <span className="stat-label">
            {european ? "Biggest last-match gain" : "Biggest season gain"}
          </span>
          <div className="strip-club">
            <Link
              to={leaguePath(
                `/teams/${changeLeader.id}`,
                changeLeader.league_id,
              )}
            >
              {changeLeader.name}
            </Link>
            <span className="strip-number">
              <Change
                value={
                  european ? changeLeader.last_change : changeLeader.change
                }
              />
            </span>
          </div>
        </div>
        <div>
          <span className="stat-label">Performance evidence</span>
          <div className="strip-value">
            {integer.format(european ? league.pool_matches : league.matches)}
            <span>matches processed</span>
          </div>
        </div>
      </div>
      <section className="ranking-section" aria-labelledby="rankings-heading">
        <div className="section-title">
          <div>
            <h2 id="rankings-heading">
              {european ? "European leaderboard" : "Elo leaderboard"}{" "}
              <span className="count">
                {european ? clubs.length : league.clubs.length}
              </span>
            </h2>
            <p>
              Ratings reflect results, opposition and a capped squad-value
              starting point.
            </p>
          </div>
          <Link className="text-link" to={path("/method")}>
            The methodology <ArrowUpRight aria-hidden="true" size={15} />
          </Link>
        </div>
        <div className="table-toolbar">
          <label className="search-field">
            <Search aria-hidden="true" size={16} />
            <span className="sr-only">Search clubs</span>
            <input
              type="search"
              name="club"
              autoComplete="off"
              placeholder="Search clubs…"
              value={query}
              onChange={(event) => setFilter("q", event.target.value)}
            />
          </label>
          {european && (
            <label className="sort-control">
              <span className="sr-only">Filter Top 25 by domestic league</span>
              <select
                name="filterLeague"
                aria-label="Filter Top 25 by domestic league"
                value={params.get("filterLeague") || ""}
                onChange={(event) =>
                  setFilter("filterLeague", event.target.value)
                }
              >
                <option value="">All five leagues</option>
                {(Object.keys(competitions) as LeagueId[]).map((id) => (
                  <option key={id} value={id}>
                    {competitions[id].name}
                  </option>
                ))}
              </select>
            </label>
          )}
          <label className="sort-control">
            <span>Sort by</span>
            <select
              aria-label="Sort clubs"
              name="sort"
              value={sort}
              onChange={(event) => setFilter("sort", event.target.value)}
            >
              <option value="rating">Elo rating</option>
              <option value="change">
                {european ? "Last match change" : "Season gain"}
              </option>
              {!european && <option value="value">Squad value</option>}
            </select>
          </label>
        </div>
        <div className="table-scroll">
          <table className={`leaderboard ${european ? "european-table" : ""}`}>
            <caption className="sr-only">
              {european
                ? "European Top 25: club, domestic league, unified Elo, last-match Elo change and recent form."
                : "Current-season domestic statistics and unified Elo ratings. Elo rank is different from the official league position."}
            </caption>
            <thead>
              <tr>
                <th scope="col" className="rank-cell">
                  #
                </th>
                <th scope="col" className="club-cell">
                  Club
                </th>
                {european && <th scope="col">Domestic league</th>}
                <th scope="col" className="numeric rating-cell">
                  Elo rating
                </th>
                {european ? (
                  <th scope="col" className="numeric">
                    Last match Δ
                  </th>
                ) : (
                  <>
                    <th scope="col" className="numeric">
                      MP
                    </th>
                    <th scope="col" className="numeric">
                      W
                    </th>
                    <th scope="col" className="numeric">
                      D
                    </th>
                    <th scope="col" className="numeric">
                      L
                    </th>
                    <th scope="col" className="numeric">
                      GF
                    </th>
                    <th scope="col" className="numeric">
                      GA
                    </th>
                    <th scope="col" className="numeric">
                      GD
                    </th>
                    <th scope="col" className="numeric value-cell">
                      Squad value
                    </th>
                  </>
                )}
                <th scope="col" className="form-cell">
                  Last 5
                </th>
              </tr>
            </thead>
            <tbody>
              {clubs.map((club) => (
                <tr key={club.id}>
                  <td className="rank-cell">
                    <span className={club.rank <= 3 ? "top-rank" : ""}>
                      {club.rank}
                    </span>
                  </td>
                  <th scope="row" className="club-cell">
                    <Link to={leaguePath(`/teams/${club.id}`, club.league_id)}>
                      <Crest club={club} />
                      <span>{club.name}</span>
                      <ChevronRight aria-hidden="true" size={14} />
                    </Link>
                  </th>
                  {european && <td>{club.league_name}</td>}
                  <td className="numeric rating-cell">
                    <Link to={leaguePath(`/teams/${club.id}`, club.league_id)}>
                      {number.format(club.rating)}
                    </Link>
                    <span className="rating-track" aria-hidden="true">
                      <span
                        style={{
                          width: `${Math.min(100, Math.max(0, (club.rating - 1200) / 5))}%`,
                        }}
                      />
                    </span>
                  </td>
                  {european ? (
                    <td className="numeric">
                      <Change value={club.last_change} />
                    </td>
                  ) : (
                    <>
                      <td className="numeric">{club.played}</td>
                      <td className="numeric">{club.won}</td>
                      <td className="numeric">{club.drawn}</td>
                      <td className="numeric">{club.lost}</td>
                      <td className="numeric">{club.goals_for}</td>
                      <td className="numeric">{club.goals_against}</td>
                      <td className="numeric gd">
                        {club.goal_difference > 0 ? "+" : ""}
                        {club.goal_difference}
                      </td>
                      <td className="numeric value-cell">
                        <span
                          title={
                            club.squad_value
                              ? `Valued ${date(club.valuation_date)}`
                              : "No documented value; neutral 1500 starting rating"
                          }
                        >
                          {money(club.squad_value)}
                        </span>
                      </td>
                    </>
                  )}
                  <td className="form-cell">
                    <Form items={club.form} />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {clubs.length === 0 && (
            <div className="empty-state">
              {european
                ? "No Top 25 clubs match the selected filters."
                : `No clubs match “${query}”.`}{" "}
              <button
                onClick={() => {
                  setParams(european ? {} : { league: league.league_id });
                }}
              >
                Clear filters
              </button>
            </div>
          )}
        </div>
        <div className="table-key">
          <span>
            {european
              ? "Last match Δ includes domestic and Champions League matches. Form: oldest to newest."
              : "MP played · W wins · D draws · L losses · GF goals for · GA goals against · GD goal difference"}
          </span>
          <span>Elo is not the points table.</span>
        </div>
      </section>
      <div className="source-note">
        <CircleHelp aria-hidden="true" size={17} />
        <p>
          <strong>Squad value starts the story. Results write the rest.</strong>{" "}
          Market value initializes a club once; ratings carry across seasons.
          Completed matches determine every move after that.{" "}
          {league.squad_coverage}/{league.squad_count} clubs have documented
          values. <Link to={path("/method")}>View sources and calculation</Link>
        </p>
      </div>
    </>
  );
}
function TeamPage({ league }: { league: League }) {
  const path = (url: string) =>
    leaguePath(url, league.league_id === "europe" ? "epl" : league.league_id);
  const { id } = useParams();
  const [detail, setDetail] = useState<TeamDetail | null>(null);
  const [error, setError] = useState("");
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    setDetail(null);
    setError("");
    request<TeamDetail>(`/api/teams/${id}?league=${league.league_id}`, {
      signal: controller.signal,
    })
      .then(setDetail)
      .catch((error) => {
        if (error.name !== "AbortError") setError(error.message);
      });
    return () => controller.abort();
  }, [id, league.league_id, league.refreshed_at, revision]);
  useEffect(() => {
    document.title = detail
      ? `${detail.club.name} · PitchRank`
      : "Club · PitchRank";
  }, [detail]);
  if (error)
    return (
      <ErrorState message={error} retry={() => setRevision((v) => v + 1)} />
    );
  if (!detail) return <Loading />;
  const { club, history, results } = detail;
  return (
    <>
      <Link className="back-link" to={path("/")}>
        <ArrowLeft aria-hidden="true" size={14} />
        All clubs
      </Link>
      <section className="team-title">
        <Crest club={club} size={64} />
        <div>
          <span className="eyebrow">
            {league.name} · {detail.season.replace("-", "/")}
          </span>
          <h1>{club.name}</h1>
          <Form items={club.form} />
        </div>
        <div className="team-head-rating">
          <span className="stat-label">Elo rating · #{club.rank}</span>
          <strong>{number.format(club.rating)}</strong>
          <span>
            <Change value={club.change} /> since season start
          </span>
        </div>
      </section>
      <p className="stat-context">
        Domestic season statistics. Elo history and results also include
        Champions League matches.
      </p>
      <div className="team-stats">
        {[
          ["Played", club.played],
          ["Won", club.won],
          ["Drawn", club.drawn],
          ["Lost", club.lost],
          ["Goals for", club.goals_for],
          ["Goals against", club.goals_against],
          [
            "Goal difference",
            `${club.goal_difference > 0 ? "+" : ""}${club.goal_difference}`,
          ],
          ["Squad value", money(club.squad_value)],
        ].map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <div className="team-grid">
        <section className="chart-section">
          <div className="section-title">
            <div>
              <h2>Rating history</h2>
              <p>
                Every result, from a {number.format(club.initial_rating)}{" "}
                starting point.
              </p>
            </div>
            <span className="chart-key">
              <i />
              Elo
            </span>
          </div>
          <figure>
            <div
              className="history-chart"
              data-ui="rating-chart"
              role="img"
              aria-label={`${club.name} Elo rating history: started at ${number.format(club.initial_rating)}, now ${number.format(club.rating)}. Full values are available in the history table below.`}
            >
              <Suspense fallback={<p role="status">Loading rating history…</p>}>
                <RatingChart history={history} />
              </Suspense>
            </div>
            <figcaption>
              Ratings carry across seasons. Domestic and Champions League match
              updates are zero-sum.
            </figcaption>
          </figure>
          <details className="history-details">
            <summary>View all rating changes</summary>
            <div className="table-scroll">
              <table>
                <caption className="sr-only">Rating history values</caption>
                <thead>
                  <tr>
                    <th>Date</th>
                    <th>Opponent</th>
                    <th className="numeric">Elo</th>
                    <th className="numeric">Change</th>
                  </tr>
                </thead>
                <tbody>
                  {history.map((row, index) => (
                    <tr key={index}>
                      <td>{date(row.date, true)}</td>
                      <td>{row.opponent || "Season starting point"}</td>
                      <td className="numeric">{number.format(row.rating)}</td>
                      <td className="numeric">
                        {index ? <Change value={row.change} /> : "—"}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </details>
        </section>
        <aside className="club-context">
          <h2>The starting point</h2>
          <span className="starting-value">
            {number.format(club.initial_rating)}
          </span>
          <p>
            {club.squad_value
              ? `The season opened at ${number.format(club.initial_rating)} Elo. Previous ratings carry forward; squad value initializes a club only once.`
              : "No documented initial squad value is stored. The first rating used the neutral 1500 prior and has since carried forward."}
          </p>
          <dl>
            <div>
              <dt>
                {league.league_id !== "epl"
                  ? "Source published"
                  : "Market snapshot"}
              </dt>
              <dd>{date(club.valuation_date, true)}</dd>
            </div>
            <div>
              <dt>Performance change</dt>
              <dd>
                <Change value={club.change} />
              </dd>
            </div>
            <div>
              <dt>Rated matches this season</dt>
              <dd>{results.length}</dd>
            </div>
          </dl>
          {league.league_id !== "epl" && (
            <p>
              Values dated September 2026; the exact valuation day is
              unspecified.
            </p>
          )}
          {club.value_source && (
            <a
              className="text-link"
              href={club.value_source}
              target="_blank"
              rel="noreferrer"
            >
              Valuation source
              <ExternalLink aria-hidden="true" size={13} />
            </a>
          )}
        </aside>
      </div>
      <section className="recent-section">
        <div className="section-title">
          <div>
            <h2>Season results</h2>
            <p>Elo changes from the perspective of {club.name}.</p>
          </div>
          <span className="count">{results.length} matches</span>
        </div>
        {results.length ? (
          results.map((result) => (
            <ResultRow
              key={result.match_id}
              result={result}
              club={club}
              leagueId={club.league_id}
            />
          ))
        ) : (
          <div className="empty-state">
            No completed matches yet. The first result will start the rating
            history.
          </div>
        )}
      </section>
    </>
  );
}
function ResultRow({
  result,
  club,
}: {
  result: Result;
  club: Club;
  leagueId: LeagueId;
}) {
  const home = result.home_id === club.id;
  const own = home ? result.home_goals : result.away_goals;
  const against = home ? result.away_goals : result.home_goals;
  const outcome = own > against ? "W" : own < against ? "L" : "D";
  return (
    <div className="result-row">
      <time
        dateTime={result.date}
        title={`${result.competition} · importance ${result.importance}`}
      >
        {date(result.date, true)}
        <small>
          {result.competition === "Champions League" ? "UCL" : "League"}
        </small>
      </time>
      <span className={`outcome form-${outcome.toLowerCase()}`}>{outcome}</span>
      <div className="result-teams">
        {result.home_league ? (
          <Link to={leaguePath(`/teams/${result.home_id}`, result.home_league)}>
            {result.home}
          </Link>
        ) : (
          <span>{result.home}</span>
        )}
        <strong>
          {result.home_goals}
          <span>–</span>
          {result.away_goals}
        </strong>
        {result.away_league ? (
          <Link to={leaguePath(`/teams/${result.away_id}`, result.away_league)}>
            {result.away}
          </Link>
        ) : (
          <span>{result.away}</span>
        )}
      </div>
      <span className="result-change">
        <Change value={home ? result.home_change : result.away_change} />
        <small>Elo</small>
      </span>
    </div>
  );
}
function Method({ league }: { league: League }) {
  const path = (url: string) =>
    leaguePath(url, league.league_id === "europe" ? "epl" : league.league_id);
  const sources = [
    ...new Set(league.clubs.map((c) => c.value_source).filter(Boolean)),
  ];
  return (
    <article className="method-page">
      <Link className="back-link" to={path("/")}>
        <ArrowLeft aria-hidden="true" size={14} />
        Leaderboard
      </Link>
      <div className="eyebrow">The calculation</div>
      <h1>Strength beyond the standings.</h1>
      <p className="method-intro">
        PitchRank estimates club strength from the squad a team starts with, the
        opponents it faces, and what happens on the pitch.
      </p>
      <section>
        <span className="method-index">01</span>
        <div>
          <h2>A measured starting point</h2>
          <p>
            A club enters the connected replay once, at 1500 Elo plus a squad
            market value logarithmic adjustment relative to one shared reference
            of {money(league.squad_reference_eur)}, capped at ±
            {league.squad_cap} points. Doubling squad value has the same effect
            at every budget level.
          </p>
          <code>
            1500 + clamp({league.squad_log_scale} × ln(value /{" "}
            {integer.format(league.squad_reference_eur)}), −{league.squad_cap},
            +{league.squad_cap})
          </code>
          <p>
            The reference is fixed from the Premier League’s September 2026
            squad-value median and is used unchanged for every league. Equal
            squad values therefore receive equal starting ratings, regardless of
            league.
          </p>
          <p>
            When a documented value is missing, the club starts at 1500 and its
            value is shown as unavailable. Values are estimates, not transfer
            budgets or spending.
          </p>
        </div>
      </section>
      <section>
        <span className="method-index">02</span>
        <div>
          <h2>Earn the movement on the pitch</h2>
          <p>
            Before each match, both ratings and 65 points of home advantage
            determine an expected score. A win scores 1, a draw 0.5, and a loss
            0. The difference between actual and expected determines the update.
          </p>
          <code>
            change = 20 × I × max(1, ln(absolute goal margin + 1)) × (actual −
            expected)
          </code>
          <p>
            Beating a stronger opponent earns more than beating a weaker one.
            Large winning margins increase the update. Every match transfers the
            same number of points from one club to the other. Draws still
            matter.
          </p>
        </div>
      </section>
      <section>
        <span className="method-index">03</span>
        <div>
          <h2>Evidence, without double-counting</h2>
          <p>
            Initial configurable importance assumptions: domestic{" "}
            {league.importance_weights.domestic.toFixed(2)}; UCL league phase{" "}
            {league.importance_weights.league.toFixed(2)}; knockout rounds{" "}
            {league.importance_weights.knockout.toFixed(2)}; semifinals/final{" "}
            {league.importance_weights.finals.toFixed(2)}. These weights are not
            proven optimal. Neutral finals have no home advantage; 90-minute
            scores exclude extra-time and shootout goals. No trophy bonus.
          </p>
          <p>
            Wins, draws and losses enter through the actual result. Goals for
            and against enter through the goal margin. Opponent strength enters
            through the expected score. Matches played measure how much evidence
            exists; simply playing a match earns no points.
          </p>
          <p>
            Domestic and Champions League results since {league.history_start}{" "}
            are replayed together, chronologically. Ratings carry forward
            without seasonal resets or repeated squad bonuses. Matches with an
            ambiguous kickoff order share the ratings available before that
            group. All competitions share one pool. Refreshing imports the
            selected league and UCL, then recalculates the connected pool
            atomically without duplicating matches.
          </p>
        </div>
      </section>
      <section id="sources">
        <span className="method-index">↗</span>
        <div>
          <h2>Real data. Visible limitations.</h2>
          <p>
            Results through {date(league.results_through)}. All displayed
            statistics and Elo values are calculated from stored match results.
            Squad values use a fixed snapshot for this replay, which may have
            been published after the season began; this is a strength estimate,
            not a historical prediction. Historical replay starts in{" "}
            {league.history_start}; the available September 2026 values are a
            retrospective initial prior, not information known at the historical
            kickoff. Clubs without a documented value start at 1500.
          </p>
          <a href={league.source} target="_blank" rel="noreferrer">
            Football-Data · {league.name} results
            <ExternalLink aria-hidden="true" size={14} />
          </a>
          <p>{league.valuation_note}</p>
          <a
            href="https://fixturedownload.com/results/champions-league-2026"
            target="_blank"
            rel="noreferrer"
          >
            Fixture Download · Champions League results
          </a>
          {sources.map((source) => (
            <a key={source} href={source!} target="_blank" rel="noreferrer">
              Football Whispers · squad values citing Transfermarkt
              <ExternalLink aria-hidden="true" size={14} />
            </a>
          ))}
          <p>
            Direct Transfermarkt access was unavailable. The documented
            secondary source is retained with a valuation date for every club.
            Crests are sourced from Transfermarkt’s asset CDN; club marks belong
            to their owners.
          </p>
          <p>
            Ratings are connected by {league.ucl_matches} Champions League
            matches in a pool of {league.pool_teams} clubs and{" "}
            {league.pool_matches} matches. Opponents outside the five leagues
            remain in the calculation but are excluded from the Top 25. Their
            non-UCL domestic results are not included. The finite history window
            and retrospective valuation priors remain limitations.
          </p>
          <p>
            These ratings are not the official league standings, guaranteed
            outcomes, or a measure of financial value. Early-season ratings
            contain less match evidence.
          </p>
        </div>
      </section>
    </article>
  );
}
