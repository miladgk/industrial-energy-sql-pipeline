"""
export_dashboard_data.py
~~~~~~~~~~~~~~~~~~~~~~~~
Rebuild the static data files used by the GitHub Pages dashboard (docs/data/).

  fingrid_year_daily.json     Real Fingrid data for one full calendar year
                              (data/raw/grid_data_<year>.csv), daily means            [part: fingrid]
  wind_validation.json        Real vs. synthetic wind, from the latest daily
                              outputs/08_real_vs_synthetic_comparison_*.csv           [part: validation]
  api_snapshot.json           Overview, trend and detector scorecard from the API, shown
                              instantly while the free Render service wakes up        [part: snapshot]
  fingrid_recent_daily.json   Last 365 complete days fetched live from the Fingrid
                              API (needs FINGRID_API_KEY or config.yaml)              [part: fingrid-recent]

  Dashboard extras (API + database; both must hold the same dataset, which is checked):
  detection_thresholds.json   Detector scorecard for z = 1.0 ... 10.0 in 0.5 steps    [part: thresholds]
  facility_ranking.json       Capacity-factor ranking of all facilities               [part: ranking]
  anomaly_examples.json       Strongest flag per facility/sensor type and one injected
                              zero per sensor type, each with +/- 1 h of readings      [part: anomalies]
  zero_dropout_rules.json     Result of sql/analysis/12_zero_dropout_rules.sql        [part: blindspot]
  sql_sources.json            Verbatim text of the SQL files shown on the page        [part: sql]
  engineering.json            Index benchmark (from benchmarks/index_benchmark.md),
                              partition layout and test counts per layer               [part: engineering]

Usage (from the repository root):
    python scripts/export_dashboard_data.py                          # fingrid, validation, snapshot
    python scripts/export_dashboard_data.py --skip-snapshot          # local files only
    python scripts/export_dashboard_data.py --parts fingrid-recent   # what the daily workflow runs
    python scripts/export_dashboard_data.py --api-url http://127.0.0.1:8000
    python scripts/export_dashboard_data.py --api-url http://127.0.0.1:8000 \
        --parts thresholds ranking anomalies blindspot sql engineering
        (the database comes from DATABASE_URL or config.yaml and must hold the same data as the API)
"""

import argparse
import glob
import json
import math
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT_DIR = os.path.join(ROOT, "docs", "data")
DEFAULT_API = "https://industrial-energy-api.onrender.com"


def _write(name: str, payload: dict) -> None:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"  ✓ {name} ({os.path.getsize(path) / 1024:.1f} KB)")


FINGRID_SOURCE = ("Fingrid Open Data API, dataset 75 (wind power production) and 124 "
                  "(electricity consumption), Finland, hourly values averaged per UTC day")


def _daily_grid_payload(grid: pd.DataFrame, extra: dict) -> dict:
    """Daily means per metric plus summary stats; days missing hours are dropped."""
    grid = grid.copy()
    grid["recorded_at"] = pd.to_datetime(grid["recorded_at"], utc=True)
    grid["day"] = grid["recorded_at"].dt.strftime("%Y-%m-%d")
    hours = grid.groupby(["day", "metric"]).size().unstack()
    complete = hours[(hours >= 20).all(axis=1)].index        # tolerate DST / short gaps
    grid = grid[grid["day"].isin(complete)]
    daily = grid.pivot_table(index="day", columns="metric", values="value", aggfunc="mean").sort_index()
    # Rank only months with most of their days present, so a partial month at the
    # edge of a rolling window cannot be called the windiest or calmest month.
    month_key = daily.index.str[:7]
    days_per_month = daily.groupby(month_key).size()
    monthly = daily.groupby(month_key).mean()[days_per_month >= 20]
    return {
        "source": FINGRID_SOURCE,
        **extra,
        "unit": "MW",
        "days": [
            {"day": day, "wind_mw": round(float(row.wind_production), 1),
             "consumption_mw": round(float(row.consumption), 1)}
            for day, row in daily.iterrows()
        ],
        "summary": {
            "wind_mean_mw": round(float(daily.wind_production.mean()), 1),
            "consumption_mean_mw": round(float(daily.consumption.mean()), 1),
            "wind_share_pct": round(float(daily.wind_production.sum() / daily.consumption.sum() * 100), 1),
            "windiest_month": monthly.wind_production.idxmax() if len(monthly) else None,
            "calmest_month": monthly.wind_production.idxmin() if len(monthly) else None,
            "wind_max_day": daily.wind_production.idxmax(),
            "wind_min_day": daily.wind_production.idxmin(),
        },
    }


def export_fingrid(year: int) -> None:
    # Fetch the file first with:
    #   python src/fetch_grid_data.py --start <year>-01-01 --end <year+1>-01-01 --output data/raw/grid_data_<year>.csv
    name = f"grid_data_{year}.csv"
    grid = pd.read_csv(os.path.join(ROOT, "data", "raw", name))
    _write("fingrid_year_daily.json", _daily_grid_payload(grid, {"year": year, "file": f"data/raw/{name}"}))


def export_fingrid_recent(days: int = 365) -> None:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from fetch_grid_data import fetch_fingrid_data, load_api_key

    api_key = load_api_key()
    if not api_key:
        raise SystemExit("No Fingrid API key: set FINGRID_API_KEY or fingrid_api_key in config.yaml.")
    end = pd.Timestamp.now(tz="UTC").normalize().tz_localize(None)    # today 00:00 UTC, exclusive
    start = end - pd.Timedelta(days=days)
    grid = fetch_fingrid_data(api_key, start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))
    _write("fingrid_recent_daily.json", _daily_grid_payload(grid, {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "window_start": start.strftime("%Y-%m-%d"),
        "window_end_exclusive": end.strftime("%Y-%m-%d"),
    }))


def export_validation() -> None:
    # Only daily outputs (day_label column) have the 365-point series; monthly runs are skipped.
    candidates = sorted(glob.glob(os.path.join(ROOT, "outputs", "08_real_vs_synthetic_comparison_*.csv")), reverse=True)
    daily = next((p for p in candidates if "day_label" in pd.read_csv(p, nrows=0).columns), None)
    if daily is None:
        print("  ⚠ no daily 08_real_vs_synthetic_comparison output found; skipped")
        return
    df = pd.read_csv(daily)
    n = len(df)
    r = float(df.real_avg.corr(df.synthetic_avg))
    t = r * math.sqrt((n - 2) / (1 - r * r))
    try:
        from scipy import stats
        p = float(2 * stats.t.sf(abs(t), n - 2))
    except ImportError:  # normal approximation is accurate for n of a few hundred
        p = math.erfc(abs(t) / math.sqrt(2))
    _write("wind_validation.json", {
        "source": f"outputs/{os.path.basename(daily)} (sql/analysis/08_real_vs_synthetic_comparison.sql), "
                  "run on a full-year synthetic dataset",
        "year": int(str(df.day_label.iloc[0])[:4]),
        "n_days": n,
        "pearson_r": round(r, 4),
        "p_value": round(p, 3),
        "days": [{"day": d, "real_z": round(float(a), 3), "synthetic_z": round(float(b), 3)}
                 for d, a, b in zip(df.day_label, df.real_z, df.synthetic_z)],
    })


def _api_get(api_url: str, path: str) -> dict:
    # urlopen also understands file:// and ftp://; only plain HTTP(S) is acceptable here.
    if urllib.parse.urlparse(api_url).scheme not in ("http", "https"):
        raise ValueError(f"--api-url must start with http:// or https://, got {api_url!r}")
    with urllib.request.urlopen(api_url + path, timeout=300) as resp:  # nosec B310 (scheme validated above)
        return json.load(resp)


def export_snapshot(api_url: str) -> None:
    def get(path: str) -> dict:
        return _api_get(api_url, path)

    _write("api_snapshot.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_url": _api_label(api_url),
        "overview": get("/api/overview"),
        "trend": get("/api/output-trend?hours=24"),
        "detection": get("/api/detection-quality"),
    })


# ──────────────────────────────────────────────────────────────
# Dashboard extras
# ──────────────────────────────────────────────────────────────

GITHUB_BLOB = "https://github.com/miladgk/industrial-energy-sql-pipeline/blob/main/"
PAGE_SQL_FILES = [
    "sql/analysis/11_detection_quality.sql",
    "sql/analysis/12_zero_dropout_rules.sql",
    "sql/analysis/08_real_vs_synthetic_comparison.sql",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from db_connection import get_connection
    return get_connection()


def _rows(conn, sql: str, params: tuple = ()) -> list[dict]:
    with conn.cursor() as cur:
        # With no parameters, pass None so a literal % in the SQL (e.g. in a comment) is not a placeholder.
        cur.execute(sql, params or None)
        names = [c.name for c in cur.description]
        out = []
        for row in cur.fetchall():
            item = {}
            for name, value in zip(names, row):
                if hasattr(value, "isoformat"):
                    value = value.isoformat()
                elif value.__class__.__name__ == "Decimal":
                    value = float(value)
                item[name] = value
            out.append(item)
    conn.rollback()
    return out


def _api_label(api_url: str) -> str:
    """Published files name the production API; a local run is described, not exposed."""
    host = urllib.parse.urlparse(api_url).hostname or ""
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return "local API on a replica of the production database (dataset checked against the published snapshot)"
    return api_url


def check_same_dataset(api_url: str) -> dict:
    """Refuse to mix sources: the database must hold the data the API serves."""
    overview = _api_get(api_url, "/api/overview")
    conn = _db()
    try:
        db = _rows(conn, "SELECT (SELECT COUNT(*) FROM readings) AS reading_count, "
                         "(SELECT COUNT(*) FROM readings WHERE is_anomaly) AS anomaly_count")[0]
    finally:
        conn.close()
    for key in ("reading_count", "anomaly_count"):
        if int(overview[key]) != int(db[key]):
            raise SystemExit(f"API and database disagree on {key}: {overview[key]} vs {db[key]}. "
                             "Point DATABASE_URL at the database behind --api-url.")
    return {"reading_count": int(db["reading_count"]), "anomaly_count": int(db["anomaly_count"]),
            "latest_reading_at": overview["latest_reading_at"]}


def export_thresholds(api_url: str, dataset: dict) -> None:
    thresholds = [x / 2 for x in range(2, 21)]            # 1.0, 1.5, ... 10.0
    results = []
    for z in thresholds:
        det = _api_get(api_url, f"/api/detection-quality?z_threshold={z}")
        results.append({"z_threshold": z, "total": det["total"], "sensors": det["sensors"]})
        print(f"    z = {z:4.1f}  precision {det['total']['precision_pct']}%  recall {det['total']['recall_pct']}%")
    _write("detection_thresholds.json", {
        "generated_at": _now(), "api_url": _api_label(api_url), "dataset": dataset,
        "source": "GET /api/detection-quality?z_threshold=... (same SQL as sql/analysis/11_detection_quality.sql)",
        "thresholds": results,
    })


def export_ranking(api_url: str, dataset: dict) -> None:
    ranking = _api_get(api_url, "/api/facilities/ranking")
    _write("facility_ranking.json", {
        "generated_at": _now(), "api_url": _api_label(api_url), "dataset": dataset,
        "source": "GET /api/facilities/ranking (capacity factor = mean non-anomalous power output / capacity)",
        "count": ranking["count"], "facilities": ranking["facilities"],
    })


ANOMALY_EXAMPLES_SQL = """
WITH stats AS (
    SELECT sensor_id, DATE_TRUNC('month', recorded_at) AS month,
           AVG(value) AS mean_val, STDDEV(value) AS stddev_val
    FROM readings WHERE is_anomaly = FALSE
    GROUP BY sensor_id, DATE_TRUNC('month', recorded_at)
),
scored AS (
    SELECT r.reading_id, r.sensor_id, r.recorded_at, r.value, r.is_anomaly,
           f.facility_name, f.facility_type, se.sensor_type, se.unit,
           s.mean_val, s.stddev_val,
           CASE WHEN s.stddev_val > 0 THEN ABS(r.value - s.mean_val) / s.stddev_val ELSE 0 END AS z_score
    FROM readings r
    JOIN stats s ON s.sensor_id = r.sensor_id AND s.month = DATE_TRUNC('month', r.recorded_at)
    JOIN sensors se ON se.sensor_id = r.sensor_id
    JOIN facilities f ON f.facility_id = se.facility_id
),
bounds AS (
    -- keep examples at least an hour away from the data edges so every neighbourhood is complete
    SELECT MIN(recorded_at) + INTERVAL '60 minutes' AS lo, MAX(recorded_at) - INTERVAL '60 minutes' AS hi
    FROM readings
),
strongest AS (
    SELECT DISTINCT ON (facility_type, sensor_type) 'strongest_flag' AS kind, scored.*
    FROM scored, bounds WHERE z_score > 3 AND recorded_at BETWEEN lo AND hi
    ORDER BY facility_type, sensor_type, z_score DESC, reading_id
),
zeros AS (
    SELECT DISTINCT ON (sensor_type) 'injected_zero' AS kind, scored.*
    FROM scored, bounds WHERE is_anomaly AND value = 0 AND recorded_at BETWEEN lo AND hi
    ORDER BY sensor_type, recorded_at, reading_id
)
SELECT * FROM strongest
UNION ALL
SELECT * FROM zeros
ORDER BY kind, facility_type, sensor_type
"""

NEIGHBOURHOOD_SQL = """
SELECT recorded_at, value, is_anomaly
FROM readings
WHERE sensor_id = %s
  AND recorded_at BETWEEN %s::timestamptz - INTERVAL '60 minutes'
                      AND %s::timestamptz + INTERVAL '60 minutes'
ORDER BY recorded_at
"""


def export_anomalies(dataset: dict) -> None:
    conn = _db()
    try:
        examples = _rows(conn, ANOMALY_EXAMPLES_SQL)
        for ex in examples:
            ex["z_score"] = round(ex["z_score"], 3)
            ex["flagged"] = ex["z_score"] > 3
            ex["mean_val"] = round(ex["mean_val"], 4)
            ex["stddev_val"] = round(ex["stddev_val"], 4)
            ex["neighbourhood"] = _rows(conn, NEIGHBOURHOOD_SQL,
                                        (ex["sensor_id"], ex["recorded_at"], ex["recorded_at"]))
    finally:
        conn.close()
    _write("anomaly_examples.json", {
        "generated_at": _now(), "dataset": dataset,
        "source": "scripts/export_dashboard_data.py (ANOMALY_EXAMPLES_SQL): same monthly baseline and z rule as "
                  "sql/analysis/11_detection_quality.sql; neighbourhood = readings of the same sensor within +/- 60 min",
        "baseline": "mean_val and stddev_val are the sensor's monthly mean and sample standard deviation "
                    "over non-injected readings; a reading is flagged when |value - mean| / stddev > 3",
        "examples": examples,
    })


def export_blindspot(dataset: dict) -> None:
    path = "sql/analysis/12_zero_dropout_rules.sql"
    with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
        sql = fh.read()
    conn = _db()
    try:
        rows = _rows(conn, sql)
    finally:
        conn.close()
    totals = {}
    for row in rows:
        t = totals.setdefault(row["rule"], {"rule": row["rule"], "injected_zeros": 0, "caught": 0, "flagged": 0})
        for key in ("injected_zeros", "caught", "flagged"):
            t[key] += int(row[key])
    for t in totals.values():
        t["recall_pct"] = round(t["caught"] / t["injected_zeros"] * 100, 1) if t["injected_zeros"] else None
        t["precision_pct"] = round(t["caught"] / t["flagged"] * 100, 1) if t["flagged"] else None
    _write("zero_dropout_rules.json", {
        "generated_at": _now(), "dataset": dataset, "source": path, "url": GITHUB_BLOB + path,
        "by_sensor": rows, "totals": list(totals.values()),
    })


def export_sql_sources() -> None:
    files = []
    for path in PAGE_SQL_FILES:
        with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
            files.append({"path": path, "url": GITHUB_BLOB + path, "sql": fh.read()})
    _write("sql_sources.json", {"generated_at": _now(), "files": files})


TEST_LAYERS = ["smoke", "api", "integration", "regression", "performance", "security", "e2e", "data"]


def _count_tests(marker: str | None) -> int:
    cmd = [sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:warnings"]
    if marker:
        cmd += ["-m", marker]
    out = subprocess.run(cmd, cwd=ROOT, capture_output=True, text=True).stdout  # nosec B603 (fixed argv)
    match = re.search(r"(\d+)(?:/\d+)? tests? collected", out)
    return int(match.group(1)) if match else 0


def export_engineering(dataset: dict) -> None:
    bench_path = os.path.join(ROOT, "benchmarks", "index_benchmark.md")
    with open(bench_path, encoding="utf-8") as fh:
        bench = fh.read()
    times = [float(x) for x in re.findall(r"Execution Time: ([\d.]+) ms", bench)]
    removed = re.search(r"Rows Removed by Filter: (\d+)", bench)
    if len(times) < 3:
        raise SystemExit("benchmarks/index_benchmark.md: expected three EXPLAIN ANALYZE runs")

    conn = _db()
    try:
        partitions = _rows(conn, """
            SELECT c.relname AS partition,
                   pg_get_expr(c.relpartbound, c.oid) AS bounds
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'readings'::regclass ORDER BY c.relname""")
        index = _rows(conn, "SELECT indexdef FROM pg_indexes WHERE indexname = 'idx_readings_sensor_time'")
        from psycopg2 import sql as pgsql
        with conn.cursor() as cur:
            for part in partitions:
                cur.execute(pgsql.SQL("SELECT COUNT(*) FROM {}").format(pgsql.Identifier(part["partition"])))
                part["rows"] = int(cur.fetchone()[0])
        conn.rollback()
    finally:
        conn.close()

    layers = {layer: _count_tests(layer) for layer in TEST_LAYERS}
    _write("engineering.json", {
        "generated_at": _now(), "dataset": dataset,
        "benchmark": {
            "source": "benchmarks/index_benchmark.md (full-year 2025 dataset, 6.3 M rows, median of 7 local Docker runs)",
            "query": "SELECT * FROM readings WHERE sensor_id = 5 AND recorded_at BETWEEN '2025-06-01' AND '2025-06-07'",
            "single_column_index_ms": times[0],
            "composite_index_ms": times[1],
            "partitioned_with_composite_index_ms": times[2],
            "speedup_composite_vs_single": round(times[0] / times[1], 1),
            "rows_removed_by_filter_without_composite": int(removed.group(1)) if removed else None,
            "note": "The speed-up comes from the composite index. On this single-sensor lookup the partitioned "
                    "table is about as fast; partitioning pays off in pruning and maintenance.",
        },
        "partitioning": {
            "partition_count": len(partitions),
            "partitions": partitions,
            "composite_index": index[0]["indexdef"] if index else None,
        },
        "tests": {
            "total": _count_tests(None),
            "by_layer": layers,
            "load_test": "tests/load/locustfile.py (Locust, run separately)",
            "ci_matrix": "Python 3.11 / 3.12 on PostgreSQL 15, plus PostgreSQL 14 and 16 on Python 3.11",
            "counted": "pytest --collect-only on the machine that ran this export",
        },
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=DEFAULT_API, help="API base URL for the snapshot")
    parser.add_argument("--skip-snapshot", action="store_true", help="Do not call the API")
    parser.add_argument("--parts", nargs="+",
                        choices=["fingrid", "validation", "snapshot", "fingrid-recent", "thresholds", "ranking",
                                 "anomalies", "blindspot", "sql", "engineering"],
                        help="Only build these files (default: fingrid validation snapshot)")
    parser.add_argument("--year", type=int, default=2025, help="Calendar year for the fingrid part (default 2025)")
    parser.add_argument("--recent-days", type=int, default=365, help="Window for fingrid-recent (days)")
    args = parser.parse_args()

    parts = args.parts or ["fingrid", "validation"] + ([] if args.skip_snapshot else ["snapshot"])
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Writing dashboard data to {os.path.relpath(OUT_DIR, ROOT)}/ ({', '.join(parts)})")
    if "fingrid" in parts:
        export_fingrid(args.year)
    if "validation" in parts:
        export_validation()
    if "snapshot" in parts:
        export_snapshot(args.api_url.rstrip("/"))
    if "fingrid-recent" in parts:
        export_fingrid_recent(args.recent_days)

    api_url = args.api_url.rstrip("/")
    needs_dataset = {"thresholds", "ranking", "anomalies", "blindspot", "engineering"} & set(parts)
    dataset = check_same_dataset(api_url) if needs_dataset else None
    if dataset:
        print(f"  dataset check passed: {dataset['reading_count']:,} readings in both API and database")
    if "thresholds" in parts:
        export_thresholds(api_url, dataset)
    if "ranking" in parts:
        export_ranking(api_url, dataset)
    if "anomalies" in parts:
        export_anomalies(dataset)
    if "blindspot" in parts:
        export_blindspot(dataset)
    if "sql" in parts:
        export_sql_sources()
    if "engineering" in parts:
        export_engineering(dataset)


if __name__ == "__main__":
    main()
