"""Generate and load the full synthetic dataset into a remote PostgreSQL database."""

import os
from pathlib import Path

from src.generate_data import main as generate_data
from src.db_connection import get_connection
from src.ingest import ingest_facilities, ingest_sensors


ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"


def load_readings_fast(connection) -> None:
    """Bulk-load readings through PostgreSQL COPY and preserve idempotency."""
    with connection.cursor() as cursor:
        cursor.execute(
            """
            CREATE TEMP TABLE readings_import (LIKE readings INCLUDING DEFAULTS)
            ON COMMIT DROP
            """
        )
        with (RAW_DIR / "readings.csv").open("r", encoding="utf-8") as readings_file:
            cursor.copy_expert(
                """
                COPY readings_import (reading_id, sensor_id, recorded_at, value, is_anomaly)
                FROM STDIN WITH (FORMAT CSV, HEADER TRUE)
                """,
                readings_file,
            )
        cursor.execute(
            """
            INSERT INTO readings (reading_id, sensor_id, recorded_at, value, is_anomaly)
            SELECT reading_id, sensor_id, recorded_at, value, is_anomaly
            FROM readings_import
            ON CONFLICT (reading_id, recorded_at) DO NOTHING
            """
        )
        print(f"Loaded {cursor.rowcount:,} readings into Render PostgreSQL.")
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
