"""
test_integration.py: INTEGRATION TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests check one piece alone. Integration tests check that the pieces work
*together*: Python <-> PostgreSQL <-> SQL files <-> API. Everything here runs
against the real database (no mocks), which is exactly where integration bugs
live: wrong column names, broken joins, schema drift, SQL that no longer runs.

(The ingest + idempotency flow is covered by test_incremental.py.)

Run only these:  pytest -m integration
"""

import glob
import os

import pytest

pytestmark = pytest.mark.integration

ANALYSIS_SQL = sorted(glob.glob(
    os.path.join(os.path.dirname(__file__), "..", "sql", "analysis", "*.sql")
))


def _scalar(db, sql):
    with db.cursor() as cur:
        cur.execute(sql)
        return cur.fetchone()[0]


# ── SQL files <-> database schema ──────────────────────────────

@pytest.mark.parametrize("path", ANALYSIS_SQL, ids=os.path.basename)
def test_analysis_sql_file_executes(path):
    """
    Every analysis query must still run against the current schema. If a column
    is renamed or a table changes, the broken file is named in the failure.
    Runs in a read-only transaction on its own connection, so it cannot modify data.
    """
    from analysis_window import params_for
    from db_connection import get_connection

    conn = get_connection()
    try:
        conn.set_session(readonly=True)
        with conn.cursor() as cur, open(path, encoding="utf-8") as fh:
            sql = fh.read()
            cur.execute(sql, params_for(sql))
            if cur.description is not None:
                cur.fetchall()  # force the full result to be produced
    finally:
        conn.close()


# ── Referential integrity & partitioning ───────────────────────

def test_no_orphan_readings(db):
    assert _scalar(db, """
        SELECT COUNT(*) FROM readings r
        LEFT JOIN sensors s ON s.sensor_id = r.sensor_id
        WHERE s.sensor_id IS NULL""") == 0


def test_no_orphan_sensors(db):
    assert _scalar(db, """
        SELECT COUNT(*) FROM sensors s
        LEFT JOIN facilities f ON f.facility_id = s.facility_id
        WHERE f.facility_id IS NULL""") == 0


def test_readings_table_is_partitioned_and_complete(db):
    """Rows must be routed into partitions, and no row may live outside one."""
    assert _scalar(db, "SELECT relkind FROM pg_class WHERE relname = 'readings'") == "p"
    total = _scalar(db, "SELECT COUNT(*) FROM readings")
    in_partitions = _scalar(db, """
        SELECT COALESCE(SUM(n_live), 0) FROM (
            SELECT (xpath('/row/c/text()',
                    query_to_xml(format('SELECT COUNT(*) AS c FROM %I', c.relname),
                                 false, true, '')))[1]::text::bigint AS n_live
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'readings'::regclass
        ) t""")
    assert in_partitions == total


# ── API <-> database consistency ───────────────────────────────

def test_overview_matches_database(client, db):
    body = client.get("/api/overview").json()
    assert body["reading_count"] == _scalar(db, "SELECT COUNT(*) FROM readings")
    assert body["facility_count"] == _scalar(db, "SELECT COUNT(*) FROM facilities")
    assert body["sensor_count"] == _scalar(db, "SELECT COUNT(*) FROM sensors")
    assert body["anomaly_count"] == _scalar(
        db, "SELECT COUNT(*) FROM readings WHERE is_anomaly")


def test_detection_quality_matches_database(client, db):
    total = client.get("/api/detection-quality").json()["total"]
    assert total["readings"] == _scalar(db, "SELECT COUNT(*) FROM readings")
    assert total["injected"] == _scalar(
        db, "SELECT COUNT(*) FROM readings WHERE is_anomaly")


def test_ranking_covers_every_facility_with_power_sensor(client, db):
    expected = _scalar(db, """
        SELECT COUNT(DISTINCT s.facility_id) FROM sensors s
        WHERE s.sensor_type = 'power_output'""")
    assert client.get("/api/facilities/ranking").json()["count"] == expected
