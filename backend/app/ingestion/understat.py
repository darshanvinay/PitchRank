"""Explicit, fixture-verified Understat archive importer. Never creates football results.

The provider is currently in maintenance. The pinned public archive is explicitly
Understat, not a substitute xG vendor. Parquet conversion is an acquisition-only step;
the importer and experiment need only stdlib and existing SQLAlchemy/NumPy.
"""

import argparse
import gzip
import hashlib
import json
import math
import unicodedata
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Match, MatchXG, Team, TeamAlias
from app.db.session import get_engine

ARCHIVE_URL = (
    "https://github.com/peteowen1/pannadata/releases/download/understat-latest/"
    "understat_metadata.parquet"
)
LEAGUES = {
    "EPL": "epl",
    "La liga": "laliga",
    "Bundesliga": "bundesliga",
    "Serie A": "seriea",
    "Ligue 1": "ligue1",
}
# Reviewed naming differences, never fuzzy matches and never current league membership.
ALIASES = {
    "Atletico Madrid": "Atlético de Madrid",
    "Celta Vigo": "Celta",
    "Deportivo La Coruna": "RC Deportivo",
    "Espanyol": "RCD Espanyol de Barcelona",
    "Real Oviedo": "Oviedo",
    "Real Valladolid": "Valladolid",
    "SD Huesca": "Huesca",
    "Sporting Gijon": "Sporting Gijón",
    "Borussia M.Gladbach": "Borussia Mönchengladbach",
    "FC Cologne": "Cologne",
    "FC Heidenheim": "Heidenheim",
    "Hamburger SV": "Hamburg",
    "Hertha Berlin": "Hertha BSC",
    "Mainz 05": "Mainz",
    "Nuernberg": "FC Nürnberg",
    "Fortuna Duesseldorf": "Fortuna Düsseldorf",
    "Greuther Fuerth": "Greuther Fürth",
    "RasenBallsport Leipzig": "RB Leipzig",
    "Parma Calcio 1913": "Parma",
    "SPAL 2013": "SPAL",
    "Clermont Foot": "Clermont",
    "GFC Ajaccio": "Gazélec Ajaccio",
    "SC Bastia": "Bastia",
    "Paris Saint Germain": "Paris Saint-Germain",
    "Saint-Etienne": "St Etienne",
    "St. Pauli": "St Pauli",
}


def normalized(name):
    return " ".join(unicodedata.normalize("NFKC", name).casefold().split())


def read_rows(path):
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", encoding="utf-8") as stream:
        rows = json.load(stream)
    if not isinstance(rows, list) or not rows:
        raise ValueError("Expected nonempty Understat match metadata list")
    return rows


def import_rows(engine, rows, archive_sha256, archive_url=ARCHIVE_URL, apply=False):
    """Exact historical fixture + date + score agreement or quarantine; idempotent upsert.

    No date tolerance, result corrections, team creation or fuzzy resolution. Duplicate
    archive entries must agree on every football field (season_input is ignored).
    """
    report = dict(inserted=0, updated=0, unchanged=0, duplicate_rows=0, rejected=[], coverage=[])
    unique = {}
    keys = (
        "league",
        "season",
        "match_date",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
        "home_xg",
        "away_xg",
    )
    conflicts = set()
    for row in rows:
        if row.get("league") not in LEAGUES:
            continue
        uid = str(row.get("understat_id", ""))
        if uid in unique:
            report["duplicate_rows"] += 1
            if any(row.get(k) != unique[uid].get(k) for k in keys):
                conflicts.add(uid)
        else:
            unique[uid] = row
    with Session(engine) as session:
        aliases = defaultdict(set)
        for t in session.scalars(select(Team)):
            for name in (t.canonical_name, t.display_name):
                aliases[normalized(name)].add(t.id)
        for a in session.scalars(select(TeamAlias)):
            aliases[normalized(a.name)].add(a.team_id)
        matches = session.scalars(select(Match).where(Match.league.in_(LEAGUES.values()))).all()
        fixtures = defaultdict(list)
        for m in matches:
            fixtures[m.league, m.season, m.home_team_id, m.away_team_id].append(m)
        existing = {x.match_id: x for x in session.scalars(select(MatchXG))}
        source_ids = {
            x.external_id: x.match_id for x in existing.values() if x.source == "understat"
        }
        accepted = {}
        ambiguous_fixtures = set()
        counts = Counter()
        for uid, row in unique.items():
            league = LEAGUES[row["league"]]
            season = str(row.get("season", "unknown"))
            try:
                year = int(row["season"])
                season = f"{year}-{year + 1}"
                counts[league, season, "source"] += 1
                if uid in conflicts or not uid.isdigit():
                    raise ValueError("Conflicting or invalid source match ID")
                day = date.fromisoformat(row["match_date"][:10])
                if day > date.today():
                    raise ValueError("Future match")
                teams = []
                for name in (row["home_team"], row["away_team"]):
                    ids = aliases[normalized(ALIASES.get(name, name))]
                    if len(ids) != 1:
                        raise ValueError(f"Unmatched/ambiguous club: {name}")
                    teams.append(next(iter(ids)))
                candidates = fixtures[league, season, *teams]
                candidates = [m for m in candidates if m.match_date == day]
                if len(candidates) != 1:
                    raise ValueError("No unique exact-date existing fixture")
                m = candidates[0]
                if m.status != "finished" or (m.home_goals, m.away_goals) != (
                    row["home_score"],
                    row["away_score"],
                ):
                    raise ValueError("Incomplete fixture or score disagreement")
                values = float(row["home_xg"]), float(row["away_xg"])
                if not all(math.isfinite(v) and v >= 0 for v in values):
                    raise ValueError("Invalid/missing xG")
                if m.id in ambiguous_fixtures:
                    raise ValueError("Multiple source IDs for one existing fixture")
                if m.id in accepted and accepted[m.id][0] != uid:
                    previous_uid = accepted.pop(m.id)[0]
                    ambiguous_fixtures.add(m.id)
                    report["rejected"].append(
                        dict(
                            id=previous_uid,
                            league=league,
                            season=season,
                            reason="Multiple source IDs for one existing fixture",
                        )
                    )
                    raise ValueError("Multiple source IDs for one existing fixture")
                if uid in source_ids and source_ids[uid] != m.id:
                    raise ValueError("Source ID changed fixture identity")
                accepted[m.id] = (uid, values, day)
                counts[league, season, "matched"] += 1
            except (ValueError, TypeError, KeyError) as exc:
                report["rejected"].append(
                    dict(
                        id=uid,
                        league=league,
                        season=season,
                        home=row.get("home_team"),
                        away=row.get("away_team"),
                        date=row.get("match_date"),
                        reason=str(exc),
                    )
                )
        for mid, (uid, values, day) in accepted.items():
            old = existing.get(mid)
            if old and old.source != "understat":
                raise ValueError("Refusing to overwrite a different xG source")
            if old and (old.external_id, old.home_xg, old.away_xg) == (uid, *values):
                report["unchanged"] += 1
                continue
            report["updated" if old else "inserted"] += 1
            if apply:
                if old is None:
                    old = MatchXG(match_id=mid)
                    session.add(old)
                old.source, old.external_id = "understat", uid
                old.home_xg, old.away_xg = values
                old.provider_date, old.source_url = day, f"https://understat.com/match/{uid}"
                old.archive_url, old.archive_sha256 = archive_url, archive_sha256
        for league, season in sorted({(a, b) for a, b, _ in counts}):
            stored = [
                m
                for m in matches
                if m.league == league and m.season == season and m.status == "finished"
            ]
            matched = [m for m in stored if m.id in accepted]
            report["coverage"].append(
                dict(
                    league=league,
                    season=season,
                    existing=len(stored),
                    source=counts[league, season, "source"],
                    matched=len(matched),
                    missing=len(stored) - len(matched),
                    first=str(min(m.match_date for m in matched)) if matched else None,
                    last=str(max(m.match_date for m in matched)) if matched else None,
                )
            )
        if apply:
            session.commit()
    report["applied"] = apply
    report["archive_url"], report["archive_sha256"] = archive_url, archive_sha256
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("path", type=Path, help="Normalized Understat metadata JSON or JSON.gz")
    parser.add_argument("--archive-sha256", required=True, help="Original Parquet SHA256")
    parser.add_argument("--apply", action="store_true", help="Write xG only; otherwise dry run")
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if len(args.archive_sha256) != 64:
        parser.error("Expected original SHA256")
    result = import_rows(get_engine(), read_rows(args.path), args.archive_sha256, apply=args.apply)
    result["normalized_sha256"] = hashlib.sha256(args.path.read_bytes()).hexdigest()
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k: v for k, v in result.items() if k not in ("coverage", "rejected")}))
    print(f"Quarantined {len(result['rejected'])} rows; see {args.report}")


if __name__ == "__main__":
    main()
