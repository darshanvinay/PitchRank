"""The five supported competitions; shared Elo parameters live in core.season."""

from dataclasses import dataclass
from typing import Literal

LeagueView = Literal["epl", "laliga", "seriea", "bundesliga", "ligue1", "europe"]
LeagueId = Literal["epl", "laliga", "seriea", "bundesliga", "ligue1"]


@dataclass(frozen=True)
class Competition:
    name: str
    country: str
    division: str
    timezone: str
    source: str
    valuation_note: str
    club_count: int = 20


LEAGUES = {
    "epl": Competition(
        "Premier League",
        "England",
        "E0",
        "Europe/London",
        "https://www.football-data.co.uk/englandm.php",
        "Fixed 1 September 2026 squad-value snapshot, via Football Whispers citing Transfermarkt.",
    ),
    "laliga": Competition(
        "La Liga",
        "Spain",
        "SP1",
        "Europe/Madrid",
        "https://www.football-data.co.uk/spainm.php",
        (
            "September 2026 Transfermarkt values via Football Whispers, published 6 September. "
            "The stored date is the publication reference date; the source does not specify "
            "an exact valuation day."
        ),
    ),
    "seriea": Competition(
        "Serie A",
        "Italy",
        "I1",
        "Europe/Rome",
        "https://www.football-data.co.uk/italym.php",
        (
            "September 2026 Transfermarkt values via Football Whispers, published 2026-09-07. "
            "The stored date is the publication reference date; the source does not specify "
            "an exact valuation day."
        ),
        club_count=20,
    ),
    "bundesliga": Competition(
        "Bundesliga",
        "Germany",
        "D1",
        "Europe/Berlin",
        "https://www.football-data.co.uk/germanym.php",
        (
            "September 2026 Transfermarkt values via Football Whispers, published 2026-09-04. "
            "The stored date is the publication reference date; the source does not specify "
            "an exact valuation day."
        ),
        club_count=18,
    ),
    "ligue1": Competition(
        "Ligue 1",
        "France",
        "F1",
        "Europe/Paris",
        "https://www.football-data.co.uk/francem.php",
        (
            "September 2026 Transfermarkt values via Football Whispers, published 2026-09-04. "
            "The stored date is the publication reference date; the source does not specify "
            "an exact valuation day."
        ),
        club_count=18,
    ),
}


def competition(league: str) -> Competition:
    if league not in LEAGUES:
        raise ValueError("Supported leagues are " + ", ".join(LEAGUES))
    return LEAGUES[league]
