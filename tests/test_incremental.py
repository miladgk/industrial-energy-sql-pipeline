"""
test_incremental.py
~~~~~~~~~~~~~~~~~~~
Pytest suite to verify the idempotency of incremental ingestion mode.
"""

import os
import sys
import subprocess
import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
from db_connection import get_connection

@pytest.fixture(scope="module")
def db_conn():
    conn = get_connection()
    conn.autocommit = True
    yield conn
    conn.close()

def test_incremental_idempotency(db_conn):
    """
    Test that running incremental ingestion twice for the same date
    inserts exactly the correct number of rows on the first run, and 
    0 new rows on the second run (idempotency).
    """
    src_dir = os.path.join(os.path.dirname(__file__), "..", "src")
    gen_script = os.path.join(src_dir, "generate_data.py")
    ingest_script = os.path.join(src_dir, "ingest.py")

    target_date = "2024-01-01"

    # Clean up any existing data for 2024-01-01 in case of re-runs
    with db_conn.cursor() as cur:
        cur.execute("DELETE FROM readings WHERE recorded_at >= '2024-01-01' AND recorded_at < '2024-01-02';")
        db_conn.commit()
        
        cur.execute("SELECT COUNT(*) FROM readings;")
        initial_total_count = cur.fetchone()[0]

    # 1. Generate incremental data
    subprocess.run([sys.executable, gen_script, "--incremental", "--date", target_date], check=True)

    # 2. Run first ingest
    subprocess.run([sys.executable, ingest_script, "--incremental"], check=True)

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM readings;")
        count_after_first = cur.fetchone()[0]

    added_rows = count_after_first - initial_total_count
    assert added_rows > 0, "First ingest should have added rows"

    # 3. Run second ingest (should be filtered by application-level high-watermark)
    subprocess.run([sys.executable, ingest_script, "--incremental"], check=True)

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM readings;")
        count_after_second = cur.fetchone()[0]

    assert count_after_second == count_after_first, "Second ingest should not add rows (Application high-watermark filter)"

    # 4. Run third ingest WITH --no-watermark to explicitly test database-level ON CONFLICT DO NOTHING
    subprocess.run([sys.executable, ingest_script, "--incremental", "--no-watermark"], check=True)

    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) FROM readings;")
        count_after_third = cur.fetchone()[0]

    assert count_after_third == count_after_first, "Third ingest should not add rows (Database ON CONFLICT DO NOTHING)"

    # 5. Incremental IDs must not reuse IDs from the base dataset. On a partitioned
    #    table (PK = reading_id, recorded_at) a reused ID would still be inserted,
    #    and on an unpartitioned table (PK = reading_id) the new day would be
    #    silently dropped, so check both outcomes explicitly.
    with db_conn.cursor() as cur:
        cur.execute("SELECT COUNT(*) - COUNT(DISTINCT reading_id) FROM readings;")
        duplicate_ids = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM readings WHERE recorded_at >= %s AND recorded_at < %s::date + 1;", (target_date, target_date))
        target_day_rows = cur.fetchone()[0]

    assert duplicate_ids == 0, f"{duplicate_ids} reading_id values are reused across batches"
    assert target_day_rows == added_rows, "All rows for the incremental day should be stored"
