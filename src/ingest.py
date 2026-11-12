"""
ingest.py
~~~~~~~~~
Loads the three raw CSV files into PostgreSQL.

Key engineering decisions
-------------------------
* readings are loaded in chunks of 5,000 rows via pandas chunksize so
  memory usage stays flat regardless of file size (~6 M rows → ~2 GB CSV).
* executemany is used for bulk inserts; psycopg2 batches these into a
  single round-trip per chunk.
* ON CONFLICT DO NOTHING makes every function idempotent — safe to re-run
  without duplicating data. For readings, the conflict target is read from
  the table's primary key at run time, so it works both before
  (PRIMARY KEY (reading_id)) and after partitioning
  (PRIMARY KEY (reading_id, recorded_at)).
* Each function wraps its work in an explicit transaction with rollback on
  failure, so a partial load never leaves the database in a dirty state.
"""

import os
import pandas as pd
import psycopg2
from psycopg2.extensions import connection as PgConnection

CHUNK_SIZE = 5_000


# ──────────────────────────────────────────────────────────────
# facilities
# ──────────────────────────────────────────────────────────────

_INSERT_FACILITY = """
    INSERT INTO facilities
        (facility_id, facility_name, facility_type, country,
         capacity_mw, commissioned_year)
    VALUES (%s, %s, %s, %s, %s, %s)
    ON CONFLICT (facility_id) DO NOTHING
"""

def ingest_facilities(conn: PgConnection, filepath: str) -> None:
    """Load facilities.csv into the facilities table."""
    df = pd.read_csv(filepath)
    rows = [
        (
            int(r.facility_id), r.facility_name, r.facility_type,
            r.country, float(r.capacity_mw), int(r.commissioned_year),
        )
        for r in df.itertuples(index=False)
    ]
    try:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_FACILITY, rows)
        conn.commit()
        print(f"  ✓ facilities: {len(rows):,} rows inserted (or skipped if already present)")
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"ingest_facilities failed: {exc}") from exc


# ──────────────────────────────────────────────────────────────
# sensors
# ──────────────────────────────────────────────────────────────

# Sensors are reference data: upsert so a regenerated sensors.csv (e.g. new
# sensor types) also updates rows that already exist. Still idempotent.
_INSERT_SENSOR = """
    INSERT INTO sensors (sensor_id, facility_id, sensor_type, unit)
    VALUES (%s, %s, %s, %s)
    ON CONFLICT (sensor_id) DO UPDATE SET
        facility_id = EXCLUDED.facility_id,
        sensor_type = EXCLUDED.sensor_type,
        unit        = EXCLUDED.unit
"""

def ingest_sensors(conn: PgConnection, filepath: str) -> None:
    """Load sensors.csv into the sensors table."""
    df = pd.read_csv(filepath)
    rows = [
        (int(r.sensor_id), int(r.facility_id), r.sensor_type, r.unit)
        for r in df.itertuples(index=False)
    ]
    try:
        with conn.cursor() as cur:
            cur.executemany(_INSERT_SENSOR, rows)
        conn.commit()
        print(f"  ✓ sensors   : {len(rows):,} rows inserted or updated")
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"ingest_sensors failed: {exc}") from exc


# ──────────────────────────────────────────────────────────────
# readings  (chunked — the large table)
# ──────────────────────────────────────────────────────────────

_INSERT_READING_TEMPLATE = """
    INSERT INTO readings (reading_id, sensor_id, recorded_at, value, is_anomaly)
    VALUES (%s, %s, %s, %s, %s)
    ON CONFLICT ({conflict_cols}) DO NOTHING
"""

# Columns that may appear in the readings primary key (whitelist: the result is
# interpolated into SQL, so only known column names are accepted).
_READINGS_PK_ALLOWED = ("reading_id", "recorded_at")


def readings_conflict_target(conn: PgConnection) -> str:
    """
    Return the primary-key column list of `readings` for use as an
    ON CONFLICT target.

    PostgreSQL requires the ON CONFLICT columns to match a unique constraint
    exactly. The unpartitioned table has PRIMARY KEY (reading_id); after
    migrate_to_partitioned.py the key becomes (reading_id, recorded_at),
    because a partitioned table's key must include the partition column.
    """
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT a.attname
            FROM pg_index i
            JOIN pg_attribute a
              ON a.attrelid = i.indrelid
             AND a.attnum = ANY (i.indkey)
            WHERE i.indrelid = 'readings'::regclass
              AND i.indisprimary
            ORDER BY array_position(i.indkey::int2[], a.attnum)
            """
        )
        cols = [row[0] for row in cur.fetchall()]
    if not cols or any(c not in _READINGS_PK_ALLOWED for c in cols):
        raise RuntimeError(f"Unexpected primary key on readings: {cols!r}")
    return ", ".join(cols)

def ingest_readings(
    conn: PgConnection,
    filepath: str,
    chunk_size: int = CHUNK_SIZE,
    use_watermark: bool = True,
) -> None:
    """
    Load readings.csv into the readings table in chunks.

    Chunking is essential for the ~6 M row file: loading it entirely
    into memory would require ~1.5 GB of RAM and stall the ingest.
    With chunk_size=5000 memory usage is constant at ~5 MB per batch.
    """
    total_rows = 0
    chunk_num  = 0

    try:
        insert_sql = _INSERT_READING_TEMPLATE.format(
            conflict_cols=readings_conflict_target(conn)
        )
        watermark = None
        if use_watermark:
            with conn.cursor() as cur:
                cur.execute("SELECT MAX(recorded_at) FROM readings;")
                watermark = cur.fetchone()[0]
            
            if watermark:
                print(f"    High-watermark detected: {watermark}")
            
        reader = pd.read_csv(
            filepath,
            chunksize=chunk_size,
            parse_dates=["recorded_at"],
        )
        for chunk in reader:
            chunk_num += 1
            
            if watermark:
                # Filter out rows older than or equal to the watermark to prevent replaying old data
                # Ensure both are UTC-aware to avoid TypeError
                watermark_pd = pd.to_datetime(watermark, utc=True)
                chunk_ts = pd.to_datetime(chunk["recorded_at"], utc=True)
                chunk = chunk[chunk_ts > watermark_pd]
                
            if chunk.empty:
                continue
            rows = [
                (
                    int(r.reading_id),
                    int(r.sensor_id),
                    r.recorded_at.isoformat(),
                    float(r.value),
                    bool(r.is_anomaly),
                )
                for r in chunk.itertuples(index=False)
            ]
            with conn.cursor() as cur:
                cur.executemany(insert_sql, rows)
            conn.commit()
            total_rows += len(rows)

            # Progress indicator every 50 chunks (~250 k rows)
            if chunk_num % 50 == 0:
                print(f"    … {total_rows:>10,} rows loaded so far")

    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"ingest_readings failed at chunk {chunk_num}: {exc}") from exc

    print(f"  ✓ readings  : {total_rows:,} rows inserted across {chunk_num} chunks")


# ──────────────────────────────────────────────────────────────
# Entry point  (run all three in dependency order)
# ──────────────────────────────────────────────────────────────

def main():
    import sys
    import argparse
    parser = argparse.ArgumentParser(description="Ingest CSV data into PostgreSQL.")
    parser.add_argument("--incremental", action="store_true", help="Ingest incremental readings instead of full load")
    parser.add_argument("--no-watermark", action="store_true", help="Bypass high-watermark check to test database-level ON CONFLICT deduplication")
    args = parser.parse_args()

    sys.path.insert(0, os.path.dirname(__file__))
    from db_connection import get_connection
    from run_quality_checks import run_quality_checks

    raw_dir = os.path.join(os.path.dirname(__file__), "..", "data", "raw")

    print("Connecting to PostgreSQL …")
    conn = get_connection()
    print("  ✓ Connected\n")

    use_wm = not args.no_watermark

    if not args.incremental:
        print("Ingesting facilities …")
        ingest_facilities(conn, os.path.join(raw_dir, "facilities.csv"))

        print("Ingesting sensors …")
        ingest_sensors(conn, os.path.join(raw_dir, "sensors.csv"))

        print("Ingesting readings (large file — may take several minutes) …")
        ingest_readings(conn, os.path.join(raw_dir, "readings.csv"), use_watermark=use_wm)
    else:
        print("Ingesting incremental readings …")
        ingest_readings(conn, os.path.join(raw_dir, "readings_incremental.csv"), use_watermark=use_wm)

    # ── Post-ingestion quality gate ──────────────────────────────
    # Runs 02_data_quality_checks.sql immediately after loading so
    # any data integrity problems are caught before analysis begins.
    print("\nRunning post-ingestion data quality checks …")
    passed = run_quality_checks(conn)
    
    conn.close()

    if not passed:
        print("⚠ Ingestion completed but quality checks flagged problems.")
        sys.exit(1)
        
    print("\nIngestion complete — all quality checks passed.")


if __name__ == "__main__":
    main()
