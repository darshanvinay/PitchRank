"""Retrieve the exact reviewed Understat archive and normalize it; no DB writes.

Optional acquisition-only dependency: pyarrow (never needed by the app/importer/search).
PYTHONPATH=backend:/tmp/pitchrank-xg-tools .venv/bin/python experiments/xg/acquire.py
"""

import gzip
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from urllib.request import Request, urlopen

from app.ingestion.historical import provider_ssl_context
from app.ingestion.understat import ARCHIVE_URL

EXPECTED = "edddd2a00f259ea631e9c5089939b6b35d64bef79c8ba4c4d8d8cec0534d18d3"


def main():
    try:
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise SystemExit(
            "Install temporary acquisition reader as documented in README.md"
        ) from exc
    root = Path(__file__).resolve().parents[2]
    directory = root / "data/raw/understat"
    directory.mkdir(parents=True, exist_ok=True)
    request = Request(
        ARCHIVE_URL, headers={"User-Agent": "PitchRank historical xG research"}
    )
    with urlopen(request, timeout=60, context=provider_ssl_context()) as response:
        raw = response.read(10_000_001)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != EXPECTED:
        raise ValueError(
            "Archive asset changed: review provenance before importing a new snapshot"
        )
    path = directory / "metadata.parquet"
    path.write_bytes(raw)
    rows = pq.read_table(path).to_pylist()
    normalized = directory / "metadata.json.gz"
    normalized.write_bytes(gzip.compress(json.dumps(rows).encode(), mtime=0))
    (directory / "acquisition.json").write_text(
        json.dumps(
            {
                "url": ARCHIVE_URL,
                "asset_id": 399247157,
                "archive_sha256": digest,
                "retrieved_at": datetime.now(UTC).isoformat(),
                "rows": len(rows),
                "normalized_sha256": hashlib.sha256(
                    normalized.read_bytes()
                ).hexdigest(),
            },
            indent=2,
        )
        + "\n"
    )
    print(
        f"Verified {len(rows)} genuine archived Understat records; wrote {normalized}"
    )


if __name__ == "__main__":
    main()
