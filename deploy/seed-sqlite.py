"""Install a checked SQLite backup once, before starting the Render web service."""

import hashlib
import os
import shutil
import sqlite3
from pathlib import Path
from tempfile import NamedTemporaryFile
from urllib.parse import urlsplit
from urllib.request import urlopen

from sqlalchemy.engine import make_url


def main():
    target = Path(make_url(os.environ["DATABASE_URL"]).database)
    if target.is_file():
        return

    url = os.environ.get("PITCHRANK_SEED_URL", "")
    expected = os.environ.get("PITCHRANK_SEED_SHA256", "").lower()
    if urlsplit(url).scheme != "https" or len(expected) != 64:
        raise SystemExit(
            "A private HTTPS seed URL and SHA-256 are required on the first boot."
        )

    with NamedTemporaryFile(dir=target.parent, suffix=".sqlite3") as temp:
        try:
            with urlopen(url, timeout=60) as response:
                shutil.copyfileobj(response, temp)
            temp.flush()
        except OSError:
            raise SystemExit(
                "SQLite seed download failed. Check the signed URL and expiry."
            ) from None

        with open(temp.name, "rb") as source:
            if hashlib.file_digest(source, "sha256").hexdigest() != expected:
                raise SystemExit("SQLite seed checksum mismatch.")

        with sqlite3.connect(
            f"{Path(temp.name).as_uri()}?mode=ro", uri=True
        ) as database:
            if database.execute("PRAGMA quick_check").fetchone() != ("ok",):
                raise SystemExit("SQLite seed integrity check failed.")

        # Publish without overwriting a database if another startup initialized it first.
        try:
            os.link(temp.name, target)
        except FileExistsError:
            pass


if __name__ == "__main__":
    main()
