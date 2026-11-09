"""Generate and load the full synthetic dataset into a remote PostgreSQL database."""

import io
import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `src.*` imports work regardless of
# the working directory or whether PYTHONPATH is set manually.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.generate_data import main as generate_data
from src.db_connection import get_connection
from src.ingest import ingest_facilities, ingest_sensors


ROOT    = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"

# Number of CSV rows sent per COPY call.  200 k rows ≈ 30–40 MB per chunk,
# keeping each round-trip well under typical proxy / SSL idle-timeout limits.
CHUNK_SIZE = 200_000


def load_readings_fast(connection) -> None:
    """Bulk-load readings into Render PostgreSQL via chunked COPY.

    Strategy
    --------
    1. TRUNCATE the target table so the load is fully idempotent.
    2. Stream readings.csv in chunks of CHUNK_SIZE rows.
    3. Each chunk is serialised into an in-memory StringIO buffer and sent
       with cursor.copy_expert(), followed by an immediate commit.

    Why chunked instead of one large COPY?
    * A single multi-minute stream is killed by Render's SSL/proxy idle
      timeout (~60 s without traffic), causing OperationalError mid-load.
    * Per-chunk commits keep each TCP round-trip short and give the
      GitHub Actions log a live progress feed so the job doesn't look hung.
    """
    import pandas as pd

    csv_path = RAW_DIR / "readings.csv"

    # ── 0. estimate total rows for the progress display ──────────────────────
    # Count newlines minus the header; fast even for a 2 GB file because we
    # only read raw bytes without parsing.
    with csv_path.open("rb") as fh:
        total_rows = sum(1 for _ in fh) - 1  # subtract header
    print(f"readings.csv: {total_rows:,} rows to load in chunks of {CHUNK_SIZE:,}")

    # ── 1. TRUNCATE — clear any previous (partial) load ──────────────────────
    with connection.cursor() as cur:
        cur.execute("TRUNCATE TABLE readings RESTART IDENTITY CASCADE;")
    connection.commit()
    print("Table truncated — starting chunked COPY …")

    # ── 2. chunked COPY ──────────────────────────────────────────────────────
    _COPY_SQL = (
        "COPY readings (reading_id, sensor_id, recorded_at, value, is_anomaly) "
        "FROM STDIN WITH (FORMAT CSV, HEADER FALSE)"
    )

    rows_loaded = 0
    chunk_num   = 0

    reader = pd.read_csv(
        csv_path,
        chunksize=CHUNK_SIZE,
        dtype=str,          # keep everything as strings — no parsing overhead
    )

    for chunk in reader:
        chunk_num += 1

        # Serialise chunk to an in-memory CSV buffer (no temp files on disk).
        buf = io.StringIO()
        chunk.to_csv(buf, index=False, header=False)
        buf.seek(0)

        with connection.cursor() as cur:
            cur.copy_expert(_COPY_SQL, buf)
        connection.commit()

        rows_loaded += len(chunk)
        pct = rows_loaded / total_rows * 100
        print(
            f"  chunk {chunk_num:>3} | "
            f"loaded {rows_loaded:>10,} / {total_rows:,} rows "
            f"({pct:.1f}%)"
        )

    # ── 3. final verification ────────────────────────────────────────────────
    with connection.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM readings;")
        db_count = cur.fetchone()[0]

    print(f"\n✅ Done — {db_count:,} readings in Render PostgreSQL.")


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "Set DATABASE_URL to the Render External Database URL before running."
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating facilities, sensors, and the full 6.3M-row readings dataset...")
    sys.argv = ["generate_data.py"]
    generate_data()

    print("\nLoading the generated CSV files into Render PostgreSQL...")
    connection = get_connection()
    try:
        ingest_facilities(connection, str(RAW_DIR / "facilities.csv"))
        ingest_sensors(connection, str(RAW_DIR / "sensors.csv"))
        load_readings_fast(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
