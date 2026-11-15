"""
test_performance.py: PERFORMANCE TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
This automates benchmarks/index_benchmark.md: instead of a one-off write-up, CI
now notices when a change makes the database slow.

Timing numbers are noisy (laptop vs. CI runner), so the suite has two parts:

1. PLAN TESTS (deterministic, never flaky). Ask PostgreSQL *how* it would run the
   query (EXPLAIN) and assert the design decisions still hold:
     - the composite index (sensor_id, recorded_at) exists, in that column order
     - a single-sensor time-range query can use it
     - a one-month query touches exactly ONE partition (partition pruning)
2. LATENCY BUDGETS (generous, median of several runs). Fail only on a big
   regression, e.g. someone drops the index or writes an accidental cross join.
     - range query: server-side execution time (EXPLAIN ANALYZE)
     - API endpoints: end-to-end time through the TestClient

Budgets are calibrated for the CI dataset (~50k rows). On the full 6.3M-row
dataset, loosen the endpoint budgets:   PERF_BUDGET_FACTOR=10 pytest -m performance

Run only these:  pytest -m performance
"""

import json
import os
import statistics
import time

import pytest

pytestmark = pytest.mark.performance

FACTOR = float(os.environ.get("PERF_BUDGET_FACTOR", 1))
RUNS = 5


# ── helpers ────────────────────────────────────────────────────

def _plan(db, sql, params=(), analyze=False):
    """Return the root of EXPLAIN's JSON output ({'Plan': ..., 'Execution Time': ...})."""
    prefix = "EXPLAIN (ANALYZE, FORMAT JSON) " if analyze else "EXPLAIN (FORMAT JSON) "
    with db.cursor() as cur:
        cur.execute(prefix + sql, params)
        result = cur.fetchone()[0]
    db.rollback()
    return (json.loads(result) if isinstance(result, str) else result)[0]


def _nodes(plan):
    """Yield every node of a plan tree."""
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


def _relations(plan):
    return {n["Relation Name"] for n in _nodes(plan) if "Relation Name" in n}


@pytest.fixture(scope="module")
def range_query(db):
    """A typical dashboard query: one sensor, six days, inside a single month."""
    with db.cursor() as cur:
        cur.execute("""
            SELECT sensor_id, MIN(recorded_at) FROM readings
            WHERE sensor_id = (SELECT MIN(sensor_id) FROM readings)
            GROUP BY sensor_id""")
        sensor_id, start = cur.fetchone()
    db.rollback()
    sql = ("SELECT * FROM readings WHERE sensor_id = %s "
           "AND recorded_at >= %s AND recorded_at < %s::timestamptz + INTERVAL '6 days'")
    return sql, (sensor_id, start, start)


# ── 1. plan tests ──────────────────────────────────────────────

def test_composite_index_exists_with_correct_column_order(db):
    with db.cursor() as cur:
        cur.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_readings_sensor_time'")
        row = cur.fetchone()
    assert row, "idx_readings_sensor_time is missing: time-range queries will scan everything"
    assert "(sensor_id, recorded_at)" in row[0], "column order matters: equality column first"


def test_range_query_can_use_the_composite_index(db, range_query):
    """
    On a tiny table the planner may legitimately prefer a sequential scan, so we
    forbid it for this test (enable_seqscan = off). The assertion is then:
    "an index path exists and is chosen", which fails if the index is dropped
    or no longer matches the query.
    """
    sql, params = range_query
    with db.cursor() as cur:
        cur.execute("SET enable_seqscan = off")
    try:
        plan = _plan(db, sql, params)["Plan"]
    finally:
        with db.cursor() as cur:
            cur.execute("RESET enable_seqscan")
        db.commit()
    # An index scan alone is not enough: with seq scans disabled PostgreSQL will happily
    # walk the primary-key index and filter every row. The index *condition* itself must
    # use both columns, which only the composite index can do.
    index_conds = [n.get("Index Cond", "") for n in _nodes(plan)
                   if n["Node Type"] in ("Index Scan", "Index Only Scan", "Bitmap Index Scan")]
    assert any("sensor_id" in c and "recorded_at" in c for c in index_conds), index_conds


def test_one_month_query_prunes_to_a_single_partition(db, range_query):
    """Partition pruning: a query bounded to one month must ignore the other months."""
    sql, params = range_query
    plan = _plan(db, sql, params)["Plan"]
    partitions = {r for r in _relations(plan) if r.startswith("readings_20")}
    assert len(partitions) == 1, f"expected 1 partition, planner touched {sorted(partitions)}"


def test_unbounded_query_touches_all_partitions(db):
    """Control for the test above: without a time filter pruning must NOT happen."""
    plan = _plan(db, "SELECT * FROM readings WHERE sensor_id = 1")["Plan"]
    assert len({r for r in _relations(plan) if r.startswith("readings_20")}) > 1


# ── 2. latency budgets ─────────────────────────────────────────

def test_range_query_execution_time(db, range_query):
    """Indexed range query: the benchmark measured ~0.4-1.1 ms; allow 100 ms (server-side)."""
    sql, params = range_query
    times = [_plan(db, sql, params, analyze=True)["Execution Time"] for _ in range(RUNS)]
    assert statistics.median(times) < 100, f"median {statistics.median(times):.1f} ms, runs: {times}"


@pytest.mark.parametrize("path, budget_ms", [
    ("/health", 100),
    ("/api/overview", 1500),
    ("/api/output-trend?hours=24", 1500),
    ("/api/facilities/ranking", 1500),
    ("/api/anomalies?limit=100", 2500),
    ("/api/detection-quality", 2500),
])
def test_endpoint_latency_budget(client, path, budget_ms):
    client.get(path)  # warm-up (connection, caches) so we measure steady state
    times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        response = client.get(path)
        times.append((time.perf_counter() - start) * 1000)
        assert response.status_code == 200
    median = statistics.median(times)
    budget = budget_ms * FACTOR
    assert median < budget, f"{path}: median {median:.0f} ms exceeds budget {budget:.0f} ms"
