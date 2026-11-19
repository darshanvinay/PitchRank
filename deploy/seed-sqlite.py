"""Verify and install a private SQLite backup into the Render build."""

import gzip
import hashlib
import os
import shutil
import sqlite3
import zlib
from contextlib import closing
from http.client import HTTPException
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import urlsplit
from urllib.request import urlopen

from sqlalchemy.engine import make_url


def main():
    target = Path(make_url(os.environ["DATABASE_URL"]).database)
    target.parent.mkdir(parents=True, exist_ok=True)

    url = os.environ.get("PITCHRANK_SEED_URL", "")
    expected = os.environ.get("PITCHRANK_SEED_SHA256", "").lower()
    try:
        parsed_url = urlsplit(url)
    except ValueError:
        raise SystemExit("SQLite seed URL is invalid.") from None
    if parsed_url.scheme != "https" or not parsed_url.hostname or len(expected) != 64:
        raise SystemExit(
            "A private HTTPS seed URL and SHA-256 are required for the build."
        )

    with TemporaryDirectory(dir=target.parent) as work:
        compressed = Path(work) / "seed.sqlite3.gz"
        snapshot = Path(work) / "seed.sqlite3"
        try:
            with urlopen(url, timeout=60) as response, compressed.open("wb") as output:
                shutil.copyfileobj(response, output)
        except (OSError, HTTPException, ValueError):
            raise SystemExit(
                "SQLite seed download failed. Check the signed URL and expiry."
            ) from None

        try:
            with gzip.open(compressed, "rb") as source, snapshot.open("wb") as output:
                shutil.copyfileobj(source, output)
        except (OSError, EOFError, zlib.error):
            raise SystemExit("SQLite seed gzip decompression failed.") from None

        with snapshot.open("rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise SystemExit("SQLite seed checksum mismatch after decompression.")

        try:
            with closing(
                sqlite3.connect(f"{snapshot.resolve().as_uri()}?mode=ro", uri=True)
            ) as db:
                if db.execute("PRAGMA quick_check").fetchone() != ("ok",):
                    raise SystemExit("SQLite seed integrity check failed.")
        except sqlite3.Error:
            raise SystemExit("SQLite seed integrity check failed.") from None

        os.replace(snapshot, target)


if __name__ == "__main__":
    main()
