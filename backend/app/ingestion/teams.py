import json

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Team, TeamAlias
from app.db.session import ROOT

# Explicit mappings: fuzzy matching can silently attach results to the wrong club.
# Covers every Premier League club since 1992. Provider-specific additions are reviewed here.
CLUBS = {
    "Arsenal": ["Arsenal FC"],
    "Aston Villa": ["Aston Villa FC"],
    "Barnsley": ["Barnsley FC"],
    "Birmingham": ["Birmingham City", "Birmingham City FC"],
    "Blackburn": ["Blackburn Rovers", "Blackburn Rovers FC"],
    "Blackpool": ["Blackpool FC"],
    "Bolton": ["Bolton Wanderers", "Bolton Wanderers FC"],
    "Bournemouth": ["AFC Bournemouth"],
    "Bradford": ["Bradford City", "Bradford City AFC"],
    "Brentford": ["Brentford FC"],
    "Brighton": ["Brighton & Hove Albion", "Brighton & Hove Albion FC"],
    "Burnley": ["Burnley FC"],
    "Cardiff": ["Cardiff City", "Cardiff City FC"],
    "Charlton": ["Charlton Athletic", "Charlton Athletic FC"],
    "Chelsea": ["Chelsea FC"],
    "Coventry": ["Coventry City", "Coventry City FC"],
    "Crystal Palace": ["Crystal Palace FC"],
    "Derby": ["Derby County", "Derby County FC"],
    "Everton": ["Everton FC"],
    "Fulham": ["Fulham FC"],
    "Huddersfield": ["Huddersfield Town", "Huddersfield Town AFC"],
    "Hull": ["Hull City", "Hull City AFC"],
    "Ipswich": ["Ipswich Town", "Ipswich Town FC"],
    "Leeds": ["Leeds United", "Leeds United FC"],
    "Leicester": ["Leicester City", "Leicester City FC"],
    "Liverpool": ["Liverpool FC"],
    "Luton": ["Luton Town", "Luton Town FC"],
    "Man City": ["Manchester City", "Manchester City FC"],
    "Man United": ["Manchester United", "Manchester United FC"],
    "Middlesbrough": ["Middlesbrough FC"],
    "Newcastle": ["Newcastle United", "Newcastle United FC"],
    "Norwich": ["Norwich City", "Norwich City FC"],
    "Nott'm Forest": ["Nottingham Forest", "Nottingham Forest FC"],
    "Oldham": ["Oldham Athletic", "Oldham Athletic AFC"],
    "Portsmouth": ["Portsmouth FC"],
    "QPR": ["Queens Park Rangers", "Queens Park Rangers FC"],
    "Reading": ["Reading FC"],
    "Sheffield United": ["Sheffield United FC"],
    "Sheffield Weds": ["Sheffield Wednesday", "Sheffield Wednesday FC"],
    "Southampton": ["Southampton FC"],
    "Stoke": ["Stoke City", "Stoke City FC"],
    "Sunderland": ["Sunderland AFC"],
    "Swansea": ["Swansea City", "Swansea City AFC"],
    "Swindon": ["Swindon Town", "Swindon Town FC"],
    "Tottenham": ["Tottenham Hotspur", "Tottenham Hotspur FC"],
    "Watford": ["Watford FC"],
    "West Brom": ["West Bromwich Albion", "West Bromwich Albion FC"],
    "West Ham": ["West Ham United", "West Ham United FC"],
    "Wigan": ["Wigan Athletic", "Wigan Athletic FC"],
    "Wimbledon": ["Wimbledon FC"],
    "Wolves": ["Wolverhampton Wanderers", "Wolverhampton Wanderers FC"],
}


def normalize_name(name: str) -> str:
    return " ".join(name.split()).casefold()


def seed_teams(session: Session, league: str = "epl") -> None:
    from app.core.leagues import competition

    if league == "ucl":
        seed_ucl_teams(session)
        return
    competition(league)
    clubs = CLUBS
    if league != "epl":
        clubs = {}
        for path in sorted((ROOT / "data" / "rosters").glob(f"{league}-*.json")):
            snapshot = json.loads(path.read_text())
            clubs.update({c["provider_name"]: [c["official_name"]] for c in snapshot["clubs"]})
    assets = json.loads((ROOT / "data" / "club-assets.json").read_text())
    for short, alternatives in clubs.items():
        canonical = alternatives[0] if alternatives else short
        team = session.scalar(select(Team).where(Team.canonical_name == canonical))
        if team is None:
            team = Team(
                canonical_name=canonical,
                display_name=short if league == "epl" else canonical,
                league=league,
            )
            session.add(team)
            session.flush()
        if short in assets:
            team.crest_url = "/crests/" + assets[short]["file"]
        for source in ("football-data.co.uk", "football-data.org"):
            for name in {short, *alternatives}:
                normalized = normalize_name(name)
                existing = session.scalar(
                    select(TeamAlias).where(
                        TeamAlias.source == source, TeamAlias.name == normalized
                    )
                )
                if existing is None:
                    session.add(TeamAlias(team_id=team.id, source=source, name=normalized))
    session.flush()


def resolve_team(session: Session, name: str, source: str, league: str = "epl") -> int:
    alias = session.scalar(
        select(TeamAlias)
        .join(Team, Team.id == TeamAlias.team_id)
        .where(
            (Team.league == league) if league != "ucl" else True,
            TeamAlias.source == source,
            TeamAlias.name == normalize_name(name),
        )
    )
    if alias is None:
        raise ValueError(f"Unknown team {name!r} from {source}; review the canonical alias mapping")
    return alias.team_id


def verified_roster(league: str, season: str) -> set[str] | None:
    if league == "epl":
        return None  # Existing historical EPL ingestion retains its reviewed alias mapping.
    from app.core.leagues import competition

    info = competition(league)
    path = ROOT / "data" / "rosters" / f"{league}-{season}.json"
    if not path.exists():
        raise ValueError(f"No verified roster for {league} {season}")
    data = json.loads(path.read_text())
    names = {c["official_name"] for c in data["clubs"]}
    if data["league"] != league or data["season"] != season or len(names) != info.club_count:
        raise ValueError(
            f"Verified roster must contain exactly {info.club_count} clubs "
            "for this league and season"
        )
    return names


def seed_ucl_teams(session: Session) -> None:
    from app.core.leagues import LEAGUES

    for league in LEAGUES:
        seed_teams(session, league)
    registry = json.loads((ROOT / "data/ucl-clubs.json").read_text())
    for item in registry["clubs"]:
        if item["league"] != "other":
            team_id = resolve_team(
                session, item["domestic_name"], "football-data.co.uk", item["league"]
            )
        else:
            team = session.scalar(select(Team).where(Team.canonical_name == item["name"]))
            if team is None:
                team = Team(canonical_name=item["name"], display_name=item["name"], league="other")
                session.add(team)
                session.flush()
            team_id = team.id
        normalized = normalize_name(item["provider_name"])
        existing = session.scalar(
            select(TeamAlias).where(
                TeamAlias.source == "fixturedownload.com", TeamAlias.name == normalized
            )
        )
        if existing is None:
            session.add(TeamAlias(team_id=team_id, source="fixturedownload.com", name=normalized))
        elif existing.team_id != team_id:
            raise ValueError(f"Conflicting UCL identity mapping for {item['provider_name']}")
    session.flush()
