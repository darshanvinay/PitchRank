export interface Club {
  id: number;
  name: string;
  crest_url: string | null;
  rank: number;
  rating: number;
  initial_rating: number;
  change: number;
  played: number;
  won: number;
  drawn: number;
  lost: number;
  goals_for: number;
  goals_against: number;
  goal_difference: number;
  squad_value: number | null;
  valuation_date: string | null;
  value_source: string | null;
  form: string[];
}
export interface League {
  league_id: import("./navigation").LeagueId;
  name: string;
  country: string;
  valuation_note: string;
  season: string;
  results_through: string | null;
  refreshed_at: string;
  matches: number;
  squad_coverage: number;
  squad_count: number;
  source: string;
  squad_log_scale: number;
  squad_cap: number;
  squad_reference_eur: number;
  clubs: Club[];
}
export interface Result {
  match_id: number;
  date: string;
  home_id: number;
  away_id: number;
  home: string;
  away: string;
  home_goals: number;
  away_goals: number;
  home_change: number;
  away_change: number;
}
export interface TeamDetail {
  season: string;
  club: Club;
  history: {
    date: string;
    rating: number;
    change: number;
    opponent: string | null;
    result: string | null;
  }[];
  results: Result[];
}
