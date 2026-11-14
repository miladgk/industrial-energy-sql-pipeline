"""
migrate_to_partitioned.py
~~~~~~~~~~~~~~~~~~~~~~~~~
Migrates data from `readings` to `readings_partitioned` and swaps tables.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(__file__))
from db_connection import get_connection

def main():
    conn = get_connection()
    conn.autocommit = True
    cur = conn.cursor()

    # Idempotency: after a successful run `readings` IS the partitioned table.
    # Running again would create a second, partition-less `readings_partitioned`
    # and fail with "no partition of relation found for row".
    cur.execute("""
        SELECT relkind FROM pg_class
        WHERE relname = 'readings' AND relnamespace = 'public'::regnamespace
    """)
    row = cur.fetchone()
    if row and row[0] == "p":
        print("`readings` is already partitioned: nothing to migrate.")
        cur.close()
        conn.close()
        return

    print("Running schema definition...")
    schema_path = os.path.join(os.path.dirname(__file__), "..", "sql", "schema", "10_partition_readings.sql")
    with open(schema_path, "r") as f:
        sql = f.read()
    cur.execute(sql)
    print("Schema created.")

    print("Counting rows in `readings` (old table)...")
    cur.execute("SELECT COUNT(*) FROM readings;")
    old_count = cur.fetchone()[0]
    print(f"Old count: {old_count:,}")

    print("Migrating data (this may take a minute for 6.3M rows)...")
    # Doing a direct insert-select which is generally the fastest for a single database node
    cur.execute("INSERT INTO readings_partitioned (reading_id, sensor_id, recorded_at, value, is_anomaly) SELECT reading_id, sensor_id, recorded_at, value, is_anomaly FROM readings;")
    print("Data migrated.")

    print("Counting rows in `readings_partitioned` (new table)...")
    cur.execute("SELECT COUNT(*) FROM readings_partitioned;")
    new_count = cur.fetchone()[0]
    print(f"New count: {new_count:,}")

    if old_count == new_count:
        print("Row counts match! Proceeding with table swap.")
        # Swap tables
        cur.execute("ALTER TABLE readings RENAME TO readings_old;")
        cur.execute("ALTER TABLE readings_partitioned RENAME TO readings;")
        
        # Swap indexes so the names match expectations for benchmarks and other queries
        cur.execute("ALTER INDEX idx_readings_sensor_time RENAME TO idx_readings_sensor_time_old;")
        cur.execute("ALTER INDEX idx_readings_part_sensor_time RENAME TO idx_readings_sensor_time;")
        
        print("Tables swapped successfully. `readings_old` retained for manual cleanup.")
    else:
        print("Row counts DO NOT MATCH. Aborting table swap.")
        sys.exit(1)

    cur.close()
    conn.close()

if __name__ == "__main__":
    main()
