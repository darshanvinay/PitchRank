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
from app.db.models import Match, Team
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
    commands.add_parser("status", help="Show stored match counts by season")
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
        command.add_argument("--league", choices=LEAGUES, default="epl")
    args = parser.parse_args()
    try:
        engine = get_engine()
        if args.command == "refresh":
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
                seasons = session.execute(
                    select(Match.league, Match.season, func.count(Match.id))
                    .group_by(Match.league, Match.season)
                    .order_by(Match.season)
                ).all()
                print(
                    json.dumps(
                        {
                            "teams": session.scalar(select(func.count(Team.id))),
                            "seasons": [
                                {"league": league, "season": season, "matches": count}
                                for league, season, count in seasons
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
