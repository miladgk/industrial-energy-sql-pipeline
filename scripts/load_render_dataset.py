"""Generate and load the full synthetic dataset into a remote PostgreSQL database."""

import os
import sys
from pathlib import Path

# Ensure the project root is on sys.path so `src.*` imports work regardless of
# the working directory or whether PYTHONPATH is set manually.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.generate_data import main as generate_data
from src.db_connection import get_connection
from src.ingest import ingest_facilities, ingest_sensors


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"


def load_readings_fast(connection) -> None:
    """Bulk-load readings into Render PostgreSQL via COPY.

    Strategy: TRUNCATE → COPY directly into the target table.
    * No staging table needed — avoids the ON CONFLICT constraint issue
      (readings has PRIMARY KEY on reading_id only, not (reading_id, recorded_at)).
    * TRUNCATE + COPY is the fastest possible ingest path for a full reload.
    * Safe to re-run: TRUNCATE clears any previous partial load before writing.
    """
    with connection.cursor() as cursor:
        # Clear any previously loaded rows so this is idempotent.
        cursor.execute("TRUNCATE TABLE readings RESTART IDENTITY CASCADE;")

        with (RAW_DIR / "readings.csv").open("r", encoding="utf-8") as readings_file:
            cursor.copy_expert(
                """
                COPY readings (reading_id, sensor_id, recorded_at, value, is_anomaly)
                FROM STDIN WITH (FORMAT CSV, HEADER TRUE)
                """,
                readings_file,
            )

        # cursor.rowcount is -1 after COPY; query the actual count instead.
        cursor.execute("SELECT COUNT(*) FROM readings;")
        row_count = cursor.fetchone()[0]
        print(f"Loaded {row_count:,} readings into Render PostgreSQL.")
    connection.commit()


def main() -> None:
    if not os.environ.get("DATABASE_URL"):
        raise RuntimeError(
            "Set DATABASE_URL to the Render External Database URL before running."
        )

    RAW_DIR.mkdir(parents=True, exist_ok=True)

    print("Generating facilities, sensors, and the full 6.3M-row readings dataset...")
    sys.argv = ["generate_data.py"]
    generate_data()

    print("Loading the generated CSV files into Render PostgreSQL...")
    connection = get_connection()
    try:
        ingest_facilities(connection, str(RAW_DIR / "facilities.csv"))
        ingest_sensors(connection, str(RAW_DIR / "sensors.csv"))
        load_readings_fast(connection)
    finally:
        connection.close()


if __name__ == "__main__":
    main()
