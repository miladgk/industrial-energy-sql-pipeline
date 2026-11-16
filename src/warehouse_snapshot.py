"""
warehouse_snapshot.py
~~~~~~~~~~~~~~~~~~~~~
Save and restore fingrid_observation as one gzip-compressed CSV file.

The daily GitHub Action starts with an empty PostgreSQL. It restores the
snapshot published by the previous run (a GitHub release asset), syncs only
the last few days from Fingrid, and publishes the new snapshot. Without a
snapshot the sync simply backfills, so losing the file costs time, not data.

The file is plain CSV (dataset_id, start_time, end_time, value), so anyone
can download the whole dataset without a database.

Usage:
    python src/warehouse_snapshot.py dump    fingrid_observation.csv.gz
    python src/warehouse_snapshot.py restore fingrid_observation.csv.gz
"""

import argparse
import gzip
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fingrid_catalog import ensure_catalog  # noqa: E402

# The column list is written out in each statement (no string formatting in SQL).


def dump(conn, path: str) -> int:
    """Write every observation, ordered, to *path*; returns the row count."""
    with conn.cursor() as cur, gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.copy_expert(
            "COPY (SELECT dataset_id, start_time, end_time, value FROM fingrid_observation "
            "ORDER BY dataset_id, start_time) "
            "TO STDOUT WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("SELECT count(*) FROM fingrid_observation")
        n = cur.fetchone()[0]
    conn.rollback()
    return n


def restore(conn, path: str) -> int:
    """Load *path* into fingrid_observation; rows already present are kept. Returns rows added."""
    ensure_catalog(conn)
    with conn.cursor() as cur, gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        cur.execute("CREATE TEMP TABLE snapshot_rows (LIKE fingrid_observation INCLUDING DEFAULTS) ON COMMIT DROP")
        cur.copy_expert("COPY snapshot_rows (dataset_id, start_time, end_time, value) "
                        "FROM STDIN WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("""
            INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value)
            SELECT dataset_id, start_time, end_time, value FROM snapshot_rows
            ON CONFLICT (dataset_id, start_time) DO NOTHING
        """)
        added = cur.rowcount
    conn.commit()
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["dump", "restore"])
    parser.add_argument("path")
    args = parser.parse_args()

    from db_connection import get_connection
    conn = get_connection()
    try:
        if args.action == "dump":
            n = dump(conn, args.path)
            print(f"✓ wrote {n:,} rows to {args.path} ({os.path.getsize(args.path) / 1e6:.1f} MB)")
        else:
            n = restore(conn, args.path)
            print(f"✓ restored {n:,} rows from {args.path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
