"""
test_performance.py: PERFORMANCE TESTS
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Automates benchmarks/index_benchmark.md: CI notices when a change makes the
warehouse slow.

1. PLAN TESTS (deterministic, never flaky). EXPLAIN shows the layout still works:
     - a one-dataset, one-month query reads exactly ONE partition (pruning)
     - inside it, the primary-key index (dataset_id, start_time) is used
     - a one-week query reads at most two partitions
2. LATENCY BUDGETS (generous, median of several runs). Fail only on a big
   regression, e.g. a lost index, JIT switched back on, an accidental cross join.

Loosen the budgets on a slow machine:  PERF_BUDGET_FACTOR=3 pytest -m performance

Run only these:  pytest -m performance
"""

import json
import os
import statistics
import time

import pytest

pytestmark = pytest.mark.performance

FACTOR = float(os.environ.get("PERF_BUDGET_FACTOR", 1))
RUNS = 3
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def _plan(db, sql, params=None):
    with db.cursor() as cur:
        cur.execute("EXPLAIN (FORMAT JSON) " + sql, params)
        result = cur.fetchone()[0]
    db.rollback()
    return (json.loads(result) if isinstance(result, str) else result)[0]["Plan"]


def _nodes(plan):
    yield plan
    for child in plan.get("Plans", []):
        yield from _nodes(child)


@pytest.fixture(scope="module")
def full_month(db):
    """A complete month inside the warehouse (the one before the newest)."""
    with db.cursor() as cur:
        cur.execute("SELECT date_trunc('month', max(start_time)) - interval '1 month' FROM fingrid_observation WHERE dataset_id = 75")
        start = cur.fetchone()[0]
    db.rollback()
    return start


# ── Plan tests ─────────────────────────────────────────────────

def test_one_month_query_reads_one_partition_with_the_index(db, full_month):
    plan = _plan(db, "SELECT * FROM fingrid_observation WHERE dataset_id = 75 "
                     "AND start_time >= %s AND start_time < %s + interval '1 month'", (full_month, full_month))
    relations = {n["Relation Name"] for n in _nodes(plan) if "Relation Name" in n}
    assert relations == {f"fingrid_observation_{full_month:%Y_%m}"}
    assert any("Index" in n["Node Type"] for n in _nodes(plan)), "primary-key index not used"


def test_one_week_query_reads_at_most_two_partitions(db, full_month):
    plan = _plan(db, "SELECT avg(value) FROM fingrid_observation WHERE dataset_id = 177 "
                     "AND start_time >= %s + interval '27 days' AND start_time < %s + interval '34 days'",
                 (full_month, full_month))
    relations = {n["Relation Name"] for n in _nodes(plan) if "Relation Name" in n}
    assert 1 <= len(relations) <= 2 and "fingrid_observation_default" not in relations


def test_connections_run_without_jit(db):
    """JIT compilation made the analyses 3-6x slower on the partitioned table (see db_connection.py)."""
    with db.cursor() as cur:
        cur.execute("SHOW jit")
        assert cur.fetchone()[0] == "off"
    db.rollback()


# ── Latency budgets ────────────────────────────────────────────

def _median_seconds(fn):
    times = []
    for _ in range(RUNS):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


@pytest.mark.parametrize("name,budget", [
    ("13_forecast_scorecard.sql", 3.0),
    ("17_forecast_error_vs_balancing.sql", 4.0),
    ("19_co2_forecast_backtest.sql", 4.0),
    ("20_grid_events.sql", 3.0),
    ("21_frequency_by_minute.sql", 2.0),
])
def test_analysis_query_stays_within_budget(db, name, budget):
    from analysis_window import params_for

    with open(os.path.join(ROOT, "sql", "analysis", name), encoding="utf-8") as fh:
        sql = fh.read()

    def run():
        with db.cursor() as cur:
            cur.execute(sql, params_for(sql))
            cur.fetchall()
        db.rollback()

    seconds = _median_seconds(run)
    assert seconds < budget * FACTOR, f"{name}: {seconds:.2f}s (budget {budget * FACTOR:.1f}s)"


@pytest.mark.parametrize("path,budget", [
    ("/api/datasets", 2.0),
    ("/api/latest", 1.0),
    ("/api/forecast-scorecard", 3.0),
    ("/api/grid-events?days=365", 3.0),
])
def test_api_endpoint_stays_within_budget(client, path, budget):
    seconds = _median_seconds(lambda: client.get(path).raise_for_status())
    assert seconds < budget * FACTOR, f"{path}: {seconds:.2f}s (budget {budget * FACTOR:.1f}s)"
