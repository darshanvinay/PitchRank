from pydantic import BaseModel


class Club(BaseModel):
    league_id: str
    league_name: str
    last_change: float
    id: int
    name: str
    crest_url: str | None
    rank: int
    rating: float
    initial_rating: float
    change: float
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_difference: int
    squad_value: float | None
    valuation_date: str | None
    value_source: str | None
    form: list[str]


class Result(BaseModel):
    home_league: str | None
    away_league: str | None
    competition: str
    importance: float
    match_id: int
    date: str
    home_id: int
    away_id: int
    home: str
    away: str
    home_goals: int
    away_goals: int
    home_change: float
    away_change: float


class League(BaseModel):
    league_id: str
    name: str
    country: str
    valuation_note: str
    season: str
    results_through: str | None
    refreshed_at: str
    matches: int
    squad_coverage: int
    squad_count: int
    source: str
    squad_log_scale: float
    squad_reference_eur: float
    squad_cap: float
    pool_matches: int
    pool_teams: int
    ucl_matches: int
    history_start: str
    importance_weights: dict[str, float]
    clubs: list[Club]


class HistoryPoint(BaseModel):
    date: str
    rating: float
    change: float
    opponent: str | None
    result: str | None


class TeamDetail(BaseModel):
    season: str
    club: Club
    history: list[HistoryPoint]
    results: list[Result]
