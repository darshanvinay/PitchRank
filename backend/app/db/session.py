import os
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine, make_url

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATABASE_URL = f"sqlite:///{ROOT / 'data' / 'pitchrank.sqlite3'}"


def get_engine(url: str | None = None) -> Engine:
    url = url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    parsed = make_url(url)
    if parsed.drivername != "sqlite":
        raise ValueError("PitchRank currently supports SQLite only")
    if parsed.database and parsed.database != ":memory:":
        Path(parsed.database).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(url)

    @event.listens_for(engine, "connect")
    def configure_sqlite(connection, _):
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")

    return engine
