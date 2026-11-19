"""Run the existing daily refresh on the web service that owns the SQLite disk."""

import asyncio
import logging
import sys
from datetime import UTC, datetime, timedelta

LOG = logging.getLogger(__name__)


async def run_daily(season: str) -> None:
    """Refresh at 10:15 UTC, with one catch-up run after each process start."""
    while True:
        process = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "app.ingestion.daily", "--season", season
        )
        try:
            if await process.wait():
                LOG.error("Scheduled PitchRank refresh failed")
        finally:
            if process.returncode is None:
                process.terminate()
                await process.wait()

        now = datetime.now(UTC)
        next_run = now.replace(hour=10, minute=15, second=0, microsecond=0)
        if next_run <= now:
            next_run += timedelta(days=1)
        await asyncio.sleep((next_run - now).total_seconds())
