"""
test_integration.py: INTEGRATION TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Unit tests check one piece alone. Integration tests check that the pieces work
*together*: Python <-> PostgreSQL <-> SQL files <-> API. Everything here runs
against the real database (no mocks), which is exactly where integration bugs
live: wrong column names, broken joins, schema drift, SQL that no longer runs.

(The sync, idempotency and snapshot flow is covered by test_fingrid_warehouse.py.)

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


# ── Warehouse structure ────────────────────────────────────────

def test_warehouse_is_partitioned_by_month(db):
    """Monthly UTC partitions, back to back, no overlap; the default partition stays empty."""
    with db.cursor() as cur:
        cur.execute("SELECT relkind FROM pg_class WHERE relname = 'fingrid_observation'")
        assert cur.fetchone()[0] == "p"
        cur.execute("""
            SELECT c.relname, pg_get_expr(c.relpartbound, c.oid)
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'fingrid_observation'::regclass ORDER BY c.relname""")
        parts = cur.fetchall()
        cur.execute("SELECT COUNT(*) FROM fingrid_observation_default")
        in_default = cur.fetchone()[0]
    db.rollback()
    names = [p[0] for p in parts]
    assert "fingrid_observation_default" in names
    monthly = sorted(n for n in names if n != "fingrid_observation_default")
    assert len(monthly) >= 12
    stamps = [int(n[-7:-3]) * 12 + int(n[-2:]) for n in monthly]       # ..._YYYY_MM
    assert stamps == list(range(stamps[0], stamps[0] + len(stamps))), "a month is missing"
    assert in_default == 0


def test_no_runaway_empty_partitions(db):
    """The schema creates ~15 months back and the sync/restore only the months they write;
    a long run of empty months before the data means something created partitions by span."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT c.relname, EXISTS (SELECT 1 FROM fingrid_observation o WHERE o.tableoid = c.oid) AS has_rows
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'fingrid_observation'::regclass AND c.relname <> 'fingrid_observation_default'
            ORDER BY c.relname""")
        parts = cur.fetchall()
    db.rollback()
    leading_empty = next((i for i, (_, has_rows) in enumerate(parts) if has_rows), len(parts))
    assert leading_empty <= 16, f"{leading_empty} empty partitions before the first month with data"


def test_every_observation_has_an_ended_or_day_ahead_slot(db):
    """Only the day-ahead forecasts (STORE_FUTURE) may hold slots that have not ended yet."""
    from fingrid_catalog import STORE_FUTURE

    with db.cursor() as cur:
        cur.execute("SELECT DISTINCT dataset_id FROM fingrid_observation WHERE end_time > now() + interval '5 minutes'")
        future = {r[0] for r in cur.fetchall()}
    db.rollback()
    assert future <= STORE_FUTURE


def test_catalogue_in_code_matches_the_database(db):
    from fingrid_catalog import DATASETS

    with db.cursor() as cur:
        cur.execute("SELECT dataset_id, key FROM fingrid_dataset")
        stored = dict(cur.fetchall())
    db.rollback()
    assert {d[0]: d[1] for d in DATASETS}.items() <= stored.items()


def test_quality_checks_pass(db):
    from run_quality_checks import load_checks, run_quality_checks

    assert len(load_checks()) >= 4
    assert run_quality_checks(db)
