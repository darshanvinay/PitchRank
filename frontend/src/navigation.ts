export type LeagueId = "epl" | "laliga" | "seriea" | "bundesliga" | "ligue1";
export const competitions = {
  epl: {
    name: "Premier League",
    country: "England",
    source: "https://www.football-data.co.uk/englandm.php",
  },
  laliga: {
    name: "La Liga",
    country: "Spain",
    source: "https://www.football-data.co.uk/spainm.php",
  },
  seriea: {
    name: "Serie A",
    country: "Italy",
    source: "https://www.football-data.co.uk/italym.php",
  },
  bundesliga: {
    name: "Bundesliga",
    country: "Germany",
    source: "https://www.football-data.co.uk/germanym.php",
  },
  ligue1: {
    name: "Ligue 1",
    country: "France",
    source: "https://www.football-data.co.uk/francem.php",
  },
} as const;
export function selectedLeague(search: string): LeagueId {
  const value = new URLSearchParams(search).get("league");
  return value && Object.hasOwn(competitions, value)
    ? (value as LeagueId)
    : "epl";
}
export function leaguePath(path: string, league: LeagueId): string {
  const [pathname, search = ""] = path.split("?");
  const params = new URLSearchParams(search);
  if (league !== "epl") params.set("league", league);
  else params.delete("league");
  return pathname + (params.size ? `?${params}` : "");
}
