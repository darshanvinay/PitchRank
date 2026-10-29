import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path
from urllib.error import URLError

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.elo import load_config
from app.core.leagues import LEAGUES, competition
from app.db.models import ImportRun, Match, Team
from app.db.session import ROOT, get_engine
from app.ingestion.historical import download_season, import_csv
from app.services.ratings import rankings, rebuild_ratings


def main() -> None:
    parser = argparse.ArgumentParser(description="PitchRank match ingestion and season ratings")
    commands = parser.add_subparsers(dest="command", required=True)
    load = commands.add_parser("import", help="Validate and import one historical season")
    load.add_argument("--season", required=True, help="YYYY-YYYY")
    load.add_argument(
        "--file", type=Path, help="Local CSV; omit to download from football-data.co.uk"
    )
    status = commands.add_parser(
        "status", help="Show match counts, latest results and successful imports"
    )
    status.add_argument("--season", help="Filter to YYYY-YYYY")
    status.add_argument("--league", choices=LEAGUES, help="Filter to one domestic league")
    history = commands.add_parser(
        "ucl-history", help="Import audited Openfootball Champions League history"
    )
    selection = history.add_mutually_exclusive_group(required=True)
    selection.add_argument("--season", help="YYYY-YYYY, available 2011-2012 through 2025-2026")
    selection.add_argument(
        "--all", action="store_true", help="Import all available archive seasons"
    )
    history.add_argument("--file", type=Path, help="Local football.txt file for one season")
    domestic = commands.add_parser("domestic-history", help="Import reviewed domestic seasons")
    domestic.add_argument("--from-season", default="2010-2011")
    domestic.add_argument("--to-season", default="2025-2026")
    domestic.add_argument("--league", choices=LEAGUES)
    domestic.add_argument(
        "--directory", type=Path, help="Read existing provider CSVs without downloading"
    )
    snapshot = commands.add_parser(
        "historical-elo", help="Reconstruct ratings strictly before a date"
    )
    snapshot.add_argument("--cutoff", required=True, help="Exclusive YYYY-MM-DD")
    snapshot.add_argument("--team-id", type=int)
    knockout = commands.add_parser(
        "knockout-backtest", help="Evaluate historical UCL Round-of-16 advancement"
    )
    knockout.add_argument("--seasons", nargs="+", default=["2020-2021"])
    knockout.add_argument(
        "--config", type=Path, help="Frozen SeasonConfig JSON; no tuning on evaluated ties"
    )
    knockout.add_argument("--draw-strength", type=float, default=0.7)
    knockout.add_argument("--output", type=Path, help="Optional measured JSON report")
    snapshot.add_argument(
        "--config", type=Path, help="SeasonConfig JSON including nested elo parameters"
    )
    elo = commands.add_parser("elo", help="Compute and inspect versioned Elo ratings")
    elo_commands = elo.add_subparsers(dest="elo_command", required=True)
    rebuild = elo_commands.add_parser("rebuild", help="Replay all finished matches atomically")
    rebuild.add_argument("--config", type=Path, help="JSON overrides for Elo defaults")
    rebuild.add_argument("--force", action="store_true", help="Replay even if unchanged")
    ranking = elo_commands.add_parser("rankings", help="Latest stored season's Elo snapshot")
    ranking.add_argument("--config", type=Path)
    backtest = commands.add_parser("backtest", help="Fit and evaluate chronological experiments")
    backtest.add_argument("--train", nargs="+", required=True, help="Training seasons, YYYY-YYYY")
    backtest.add_argument("--validation", nargs="+", required=True, help="Validation seasons")
    backtest.add_argument("--test", nargs="+", required=True, help="Final held-out seasons")
    backtest.add_argument("--output", type=Path, required=True, help="New report directory")
    backtest.add_argument("--starts", type=int, default=3)
    backtest.add_argument("--maxiter", type=int, default=150)
    backtest.add_argument("--seed", type=int, default=42)
    refresh = commands.add_parser(
        "refresh", help="Update current-season results, squad values, and Elo"
    )
    refresh.add_argument("--season", help="YYYY-YYYY; defaults to current season")
    refresh.add_argument("--file", type=Path, help="Local results CSV instead of download")
    refresh.add_argument("--squads", type=Path, help="Documented squad values CSV")
    for command in (load, refresh):
        command.add_argument(
            "--league",
            choices=[*LEAGUES, "europe"] if command is refresh else LEAGUES,
            default="europe" if command is refresh else "epl",
        )
    args = parser.parse_args()
    try:
        engine = get_engine()
        if args.command == "knockout-backtest":
            from app.backtesting.knockout import backtest_seasons
            from app.core.season import SeasonConfig

            config = (
                SeasonConfig.model_validate_json(args.config.read_text())
                if args.config
                else SeasonConfig()
            )
            result = backtest_seasons(engine, args.seasons, config, args.draw_strength)
            rendered = json.dumps(result, indent=2)
            if args.output:
                args.output.parent.mkdir(parents=True, exist_ok=True)
                args.output.write_text(rendered + "\n")
            print(rendered)
        elif args.command == "domestic-history":
            from app.ingestion.domestic_history import import_domestic_history

            result = import_domestic_history(
                engine, args.from_season, args.to_season, args.league, args.directory
            )
            print(json.dumps(result, indent=2))
            if any(r["errors"] for r in result["seasons"]):
                sys.exit(1)
        elif args.command == "historical-elo":
            from datetime import date

            from app.core.season import SeasonConfig
            from app.services.historical import get_team_elo_at_date, historical_elo_snapshot

            config = (
                SeasonConfig.model_validate_json(args.config.read_text())
                if args.config
                else SeasonConfig()
            )
            cutoff = date.fromisoformat(args.cutoff)
            result = (
                {
                    "team_id": args.team_id,
                    "cutoff": args.cutoff,
                    "rating": get_team_elo_at_date(
                        args.team_id, cutoff, engine=engine, config=config
                    ),
                }
                if args.team_id is not None
                else historical_elo_snapshot(engine, cutoff, config)
            )
            print(json.dumps(result, indent=2, default=str))
        elif args.command == "ucl-history":
            from app.ingestion.ucl_history import AVAILABLE, download_history, import_history

            if args.file and args.all:
                raise ValueError("--file requires --season")
            reports = []
            for season in AVAILABLE if args.all else [args.season]:
                path = args.file or download_history(season, ROOT / "data/raw/openfootball")
                reports.append(import_history(engine, path, season))
            print(
                json.dumps(
                    {
                        "source": "openfootball/champions-league",
                        "seasons": reports,
                        "unavailable_seasons": [f"{y}-{y + 1}" for y in range(2005, 2011)],
                    },
                    indent=2,
                )
            )
            if any(r["errors"] or r["unresolved_teams"] for r in reports):
                sys.exit(1)
        elif args.command == "refresh":
            from app.core.season import current_season
            from app.services.season import refresh_season

            print(
                json.dumps(
                    refresh_season(
                        engine,
                        args.season or current_season(),
                        args.file,
                        args.squads,
                        league=args.league,
                    ),
                    indent=2,
                )
            )
        elif args.command == "backtest":
            from app.backtesting.evaluation import ChronologicalSplit
            from app.backtesting.report import run_experiment

            split = ChronologicalSplit(tuple(args.train), tuple(args.validation), tuple(args.test))
            result = run_experiment(
                engine, split, args.output, args.starts, args.maxiter, args.seed
            )
            print(json.dumps(result, indent=2))
        elif args.command == "elo":
            config = load_config(args.config)
            result = (
                asdict(rebuild_ratings(engine, config, args.force))
                if args.elo_command == "rebuild"
                else rankings(engine, config)
            )
            print(json.dumps(result, indent=2))
        elif args.command == "import":
            path = args.file or download_season(args.season, ROOT / "data" / "raw", args.league)
            location = (
                None
                if args.file
                else (
                    "https://www.football-data.co.uk/mmz4281/"
                    f"{args.season[2:4]}{args.season[7:9]}/{competition(args.league).division}.csv"
                )
            )
            print(
                json.dumps(
                    asdict(
                        import_csv(engine, path, args.season, location=location, league=args.league)
                    )
                )
            )
        else:
            with Session(engine) as session:
                query = (
                    select(
                        Match.league, Match.season, func.count(Match.id), func.max(Match.match_date)
                    )
                    .where(Match.status == "finished")
                    .group_by(Match.league, Match.season)
                    .order_by(Match.season)
                )
                if args.season:
                    query = query.where(Match.season == args.season)
                if args.league:
                    query = query.where(Match.league == args.league)
                seasons = session.execute(query).all()
                print(
                    json.dumps(
                        {
                            "teams": session.scalar(select(func.count(Team.id))),
                            "seasons": [
                                {
                                    "league": league,
                                    "season": season,
                                    "matches": count,
                                    "latest_completed_match": str(latest),
                                    "last_synced_at": str(
                                        session.scalar(
                                            select(func.max(ImportRun.imported_at)).where(
                                                ImportRun.league == league,
                                                ImportRun.season == season,
                                            )
                                        )
                                        or "Never"
                                    ),
                                }
                                for league, season, count, latest in seasons
                            ],
                        },
                        indent=2,
                    )
                )
    except (ValueError, OSError, URLError, SQLAlchemyError) as exc:
        print(f"PitchRank: {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
