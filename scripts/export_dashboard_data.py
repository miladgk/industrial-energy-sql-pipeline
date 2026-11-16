"""
export_dashboard_data.py
~~~~~~~~~~~~~~~~~~~~~~~~
Build the static data files of the GitHub Pages dashboard (docs/data/) from the
Fingrid warehouse. Each file comes from the SQL in sql/analysis and sql/schema.

  fingrid_recent_daily.json   Daily wind and consumption, last 365 complete days   [part: fingrid-recent]
  forecast_scorecard.json     Error of Fingrid's own forecasts (13-17)             [part: forecast-scorecard]
  co2_forecast.json           Tomorrow's hourly CO2 intensity, backtest (18-19)    [part: co2-forecast]
  grid_events.json            Grid event log of the last year (20-21)              [part: grid-events]
  fingrid_latest.json         Newest wind and consumption from the Fingrid API;
                              built by the hourly Pages deploy, never committed    [part: fingrid-latest]
  sql_sources.json            Verbatim text of the SQL shown on the page           [part: sql]
  engineering.json            Benchmark, partition layout, test counts per layer   [part: engineering]

Usage (from the repository root; the database comes from DATABASE_URL or config.yaml):
    python src/sync_fingrid.py && python scripts/export_dashboard_data.py   # everything the daily workflow builds
    python scripts/export_dashboard_data.py --parts fingrid-latest          # the hourly Pages deploy
    python scripts/benchmark_warehouse.py && \
    python scripts/export_dashboard_data.py --parts sql engineering         # after changing SQL or tests
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

import pandas as pd

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..")
OUT_DIR = os.path.join(ROOT, "docs", "data")


def _write(name: str, payload: dict) -> None:
    path = os.path.join(OUT_DIR, name)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, separators=(",", ":"))
    print(f"  ✓ {name} ({os.path.getsize(path) / 1024:.1f} KB)")


FINGRID_SOURCE = ("Fingrid Open Data API, dataset 75 (wind power production) and 124 "
                  "(electricity consumption), Finland, 15-minute values averaged per UTC day")


def _daily_grid_payload(grid: pd.DataFrame, extra: dict, min_rows_per_day: int = 20) -> dict:
    """Daily means per metric plus summary stats; days with fewer rows than
    min_rows_per_day (20 of 24 hourly, or 92 of 96 quarter-hourly) are dropped."""
    grid = grid.copy()
    grid["recorded_at"] = pd.to_datetime(grid["recorded_at"], utc=True)
    grid["day"] = grid["recorded_at"].dt.strftime("%Y-%m-%d")
    hours = grid.groupby(["day", "metric"]).size().unstack()
    complete = hours[(hours >= min_rows_per_day).all(axis=1)].index
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


def export_fingrid_recent(days: int = 365) -> None:
    """Daily means of the last *days* complete UTC days, read from the warehouse
    (run src/sync_fingrid.py first). No extra API calls: the daily sync already has the data."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from analysis_window import default_window

    w = default_window(days=days)
    conn = _db()
    try:
        rows = _rows(conn, """
            SELECT start_time AS recorded_at,
                   CASE dataset_id WHEN 75 THEN 'wind_production' ELSE 'consumption' END AS metric,
                   value
            FROM fingrid_observation
            WHERE dataset_id IN (75, 124) AND start_time >= %(start)s AND start_time < %(end)s
        """, w)
    finally:
        conn.close()
    if not rows:
        raise SystemExit("fingrid_observation has no wind/consumption rows in the window: run src/sync_fingrid.py")
    _write("fingrid_recent_daily.json", _daily_grid_payload(pd.DataFrame(rows), {
        "source": "Fingrid Open Data API, dataset 75 (wind power production) and 124 (electricity consumption), "
                  "Finland, 15-minute values averaged per UTC day",
        "generated_at": _now(),
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
    }, min_rows_per_day=92))


FORECAST_SQL = {
    "summary": "sql/analysis/13_forecast_scorecard.sql",
    "by_hour": "sql/analysis/14_forecast_error_by_hour.sql",
    "by_month": "sql/analysis/15_forecast_error_by_month.sql",
    "biggest_misses": "sql/analysis/16_forecast_biggest_misses.sql",
    "balancing": "sql/analysis/17_forecast_error_vs_balancing.sql",
}
FORECAST_DATASETS = (75, 124, 165, 166, 245, 246, 268, 319, 375, 376, 377)


def _rounded(rows: list[dict], digits: int = 1) -> list[dict]:
    """Round floats for the page (MW and percentages to one decimal)."""
    return [{k: round(v, digits) if isinstance(v, float) else v for k, v in r.items()} for r in rows]


def export_forecast_scorecard(days: int = 365) -> None:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from analysis_window import default_window
    from fingrid_catalog import BY_ID

    w = default_window(days=days)
    conn = _db()
    try:
        out = {}
        for part, path in FORECAST_SQL.items():
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                out[part] = _rows(conn, fh.read(), w)
        coverage = _rows(conn, """
            SELECT dataset_id, count(*) AS slots, min(start_time) AS first_start, max(end_time) AS last_end
            FROM fingrid_observation
            WHERE dataset_id = ANY(%(ids)s) AND start_time >= %(start)s AND start_time < %(end)s
            GROUP BY dataset_id ORDER BY dataset_id
        """, {**w, "ids": list(FORECAST_DATASETS)})
    finally:
        conn.close()
    if len(out["summary"]) != 4:
        raise SystemExit(f"expected 4 forecast products in the window, got {len(out['summary'])}: "
                         "run src/sync_fingrid.py first")

    bins = out["balancing"]
    _write("forecast_scorecard.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0), synced into fingrid_observation by src/sync_fingrid.py",
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
        "products": {
            "day_ahead": "published the previous day at 12:00 Finnish time (datasets 246 wind, 165 consumption)",
            "intraday": "updated every 15 minutes; the last update before each slot (datasets 245, 166)",
        },
        "summary": _rounded(out["summary"]),
        "by_hour": _rounded(out["by_hour"]),
        "by_month": _rounded(out["by_month"]),
        "biggest_misses": _rounded(out["biggest_misses"]),
        "balancing": {
            "r_surprise_vs_mfrr_need": round(bins[0]["r_surprise_vs_mfrr_need"], 3) if bins else None,
            "r_surprise_vs_net_mfrr": round(bins[0]["r_surprise_vs_net_mfrr"], 3) if bins else None,
            "r_surprise_vs_price": round(bins[0]["r_surprise_vs_price"], 3) if bins else None,
            "bins": _rounded([{k: v for k, v in b.items() if not k.startswith("r_")} for b in bins]),
        },
        "coverage": [{**c, "key": BY_ID[c["dataset_id"]][1]} for c in coverage],
        "sql": list(FORECAST_SQL.values()),
    })


CO2_SQL = {"forecast": "sql/analysis/18_co2_forecast.sql", "backtest": "sql/analysis/19_co2_forecast_backtest.sql"}
CO2_TRAINING_DAYS = 62     # co2_forecast() fits on days D-61 .. D-2


def export_co2_forecast(days: int = 365) -> None:
    """Tomorrow's hourly CO2 forecast (today's if Fingrid has not yet published tomorrow's
    day-ahead forecasts, at 12:00 Finnish time), yesterday's forecast against what happened,
    and the backtest over up to *days* days."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from analysis_window import default_window, tomorrow_fi

    def sql(name):
        with open(os.path.join(ROOT, CO2_SQL[name]), encoding="utf-8") as fh:
            return fh.read()

    tomorrow = tomorrow_fi()
    w = default_window(days=days)
    conn = _db()
    try:
        target, hours = tomorrow, _rows(conn, sql("forecast"), {"day": tomorrow})
        if len(hours) < 23:                      # 23 to 25 hours, depending on DST
            target, hours = tomorrow - timedelta(days=1), _rows(conn, sql("forecast"), {"day": tomorrow - timedelta(days=1)})
        yesterday = tomorrow - timedelta(days=2)
        past = _rows(conn, sql("forecast"), {"day": yesterday})
        first = _rows(conn, "SELECT min(day_fi) AS d FROM co2_hourly WHERE co2_actual IS NOT NULL")[0]["d"]
        start = max(w["start"], datetime.fromisoformat(first).replace(tzinfo=timezone.utc)
                    + timedelta(days=CO2_TRAINING_DAYS))
        backtest = _rows(conn, sql("backtest"), {"start": start, "end": w["end"]})[0]
    finally:
        conn.close()
    if len(hours) < 23:
        raise SystemExit("no complete CO2 forecast for today or tomorrow: run src/sync_fingrid.py first")

    hours = _rounded(hours)
    # Order by the unclamped line: hours on the training-window floor share one value.
    cleanest = min(hours, key=lambda h: h["co2_unclamped"])
    dirtiest = max(hours, key=lambda h: h["co2_unclamped"])
    best3 = min((h for h in hours if h["mean_next_3h_unclamped"] is not None), key=lambda h: h["mean_next_3h_unclamped"])
    known = [h for h in past if h["co2_actual"] is not None]
    _write("co2_forecast.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0): emission factor of electricity consumed in Finland (396) "
                  "and the day-ahead forecasts of consumption (165), wind (246) and solar (247)",
        "unit": "gCO2/kWh",
        "model": "least-squares line of CO2 intensity on residual load (consumption - wind - solar forecast), "
                 "refitted daily on the 60 days ending two days before the target day, plus that line's mean "
                 "error on the last fully known day; baseline: the same hour two days earlier",
        "target_day": target.isoformat(),
        "target_is_tomorrow": target == tomorrow,
        "hours": [{k: h[k] for k in ("hour_start", "hour_fi", "co2_forecast", "co2_naive", "mean_next_3h_g",
                                     "rank_cleanest", "residual_load_mw")} for h in hours],
        "cleanest_hour": {"hour_start": cleanest["hour_start"], "hour_fi": cleanest["hour_fi"], "co2": cleanest["co2_forecast"]},
        "dirtiest_hour": {"hour_start": dirtiest["hour_start"], "hour_fi": dirtiest["hour_fi"], "co2": dirtiest["co2_forecast"]},
        "best_3h": {"hour_start": best3["hour_start"], "hour_fi": best3["hour_fi"], "co2": best3["mean_next_3h_g"]},
        "day_mean_forecast": round(sum(h["co2_forecast"] for h in hours) / len(hours), 1),
        "yesterday": {
            "day": yesterday.isoformat(),
            "hours": [{k: round(h[k], 1) if isinstance(h[k], float) else h[k]
                       for k in ("hour_start", "hour_fi", "co2_forecast", "co2_actual")} for h in past],
            "mae_g": round(sum(abs(h["co2_actual"] - h["co2_forecast"]) for h in known) / len(known), 1) if known else None,
        },
        "backtest": {
            "window_start": start.strftime("%Y-%m-%d"),
            "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
            **{k: (round(v, 1) if isinstance(v, float) else v) for k, v in backtest.items()},
        },
        "sql": ["sql/schema/14_co2_forecast.sql", *CO2_SQL.values()],
    })


EVENT_SQL = {"events": "sql/analysis/20_grid_events.sql", "by_minute": "sql/analysis/21_frequency_by_minute.sql"}
EVENT_KINDS = {   # kind: (label, True when a higher peak is more severe)
    "frequency_low": ("Frequency below 49.9 Hz", False),
    "frequency_high": ("Frequency above 50.1 Hz", True),
    "nuclear_drop": ("Fast drop in nuclear output", False),
    "low_inertia": ("Low system inertia", False),
    "price_spike": ("Imbalance price spike", True),
}


def export_grid_events(days: int = 365) -> None:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from analysis_window import default_window

    w = default_window(days=days)
    conn = _db()
    try:
        out = {}
        for part, path in EVENT_SQL.items():
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                out[part] = _rows(conn, fh.read(), w)
        quality = _rows(conn, """
            SELECT count(*) FILTER (WHERE value >= 45) AS valid, count(*) FILTER (WHERE value < 45) AS invalid,
                   (extract(epoch FROM %(end)s::timestamptz - %(start)s::timestamptz) / 60)::int AS minutes_in_window
            FROM fingrid_observation WHERE dataset_id = 177 AND start_time >= %(start)s AND start_time < %(end)s
        """, w)[0]
    finally:
        conn.close()
    events = _rounded(out["events"], 3)
    if not out["by_minute"]:
        raise SystemExit("no frequency data in the window: run src/sync_fingrid.py first")

    cutoff = (w["end"] - timedelta(days=30)).isoformat()
    counts = {k: {"label": label,
                  "year": sum(e["kind"] == k for e in events),
                  "last_30_days": sum(e["kind"] == k and e["start_time"] >= cutoff for e in events)}
              for k, (label, _) in EVENT_KINDS.items()}
    top = {k: sorted((e for e in events if e["kind"] == k), key=lambda e: e["peak"], reverse=higher)[:3]
           for k, (_, higher) in EVENT_KINDS.items()}
    _write("grid_events.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0): frequency (177), nuclear production (188), kinetic energy "
                  "of the Nordic system (260), imbalance price (319)",
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
        "thresholds": {
            "frequency": "outside the Nordic normal band 49.9-50.1 Hz (1-minute samples)",
            "nuclear_drop": "at least 400 MW below the highest value of the previous 15 minutes",
            "low_inertia": "kinetic energy in the lowest 1% of the window",
            "price_spike": "imbalance price of 1,000 EUR/MWh or more",
        },
        "counts": counts,
        "recent": [e for e in events if e["kind"] != "frequency_high" and e["kind"] != "frequency_low"][:8],
        "recent_frequency": [e for e in events if e["kind"] in ("frequency_low", "frequency_high")][:5],
        "top": top,
        "nuclear_crosscheck": [e for e in events if e["kind"] == "nuclear_drop"],
        "frequency_by_minute": _rounded(out["by_minute"], 3),
        "data_quality": quality,
        "sql": ["sql/schema/15_grid_events.sql", *EVENT_SQL.values()],
    })


def export_fingrid_latest(hours: int = 6) -> None:
    """Newest raw value of each dataset in the last few hours: two small requests, no history."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from fingrid_api import fetch_dataset_chunk, load_api_key
    DATASETS = {124: "consumption", 75: "wind_production"}

    api_key = load_api_key()
    if not api_key:
        raise SystemExit("No Fingrid API key: set FINGRID_API_KEY or fingrid_api_key in config.yaml.")
    now = pd.Timestamp.now(tz="UTC")
    start = now - pd.Timedelta(hours=hours)
    latest = {}
    for dataset_id, metric in DATASETS.items():
        rows = fetch_dataset_chunk(dataset_id, api_key, start.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                   now.strftime("%Y-%m-%dT%H:%M:%SZ"))
        rows = [r for r in rows if r.get("value") is not None]
        if not rows:
            raise RuntimeError(f"Fingrid returned no {metric} values in the last {hours} hours.")
        newest = max(rows, key=lambda r: pd.Timestamp(r["startTime"]))
        latest[metric] = {
            "dataset_id": dataset_id,
            "value_mw": round(float(newest["value"]), 1),
            "start_time": pd.Timestamp(newest["startTime"]).tz_convert("UTC").isoformat(),
            "end_time": pd.Timestamp(newest["endTime"]).tz_convert("UTC").isoformat(),
        }
    _write("fingrid_latest.json", {
        "source": "Fingrid Open Data API, newest published value of dataset 75 (wind power production) "
                  "and 124 (electricity consumption), Finland, not averaged",
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "unit": "MW",
        **latest,
    })


GITHUB_BLOB = "https://github.com/miladgk/industrial-energy-sql-pipeline/blob/main/"
PAGE_SQL_FILES = [
    "sql/schema/13_fingrid_warehouse.sql",
    "sql/schema/14_co2_forecast.sql",
    "sql/schema/15_grid_events.sql",
    "sql/analysis/13_forecast_scorecard.sql",
    "sql/analysis/17_forecast_error_vs_balancing.sql",
]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _db():
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from db_connection import get_connection
    return get_connection()


def _rows(conn, sql: str, params: tuple | dict = ()) -> list[dict]:
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


def export_engineering() -> None:
    bench_path = os.path.join(ROOT, "benchmarks", "index_benchmark.md")
    with open(bench_path, encoding="utf-8") as fh:
        raw = re.search(r"```json\n(.*?)\n```", fh.read(), re.S)
    if not raw:
        raise SystemExit("benchmarks/index_benchmark.md has no measurements: run scripts/benchmark_warehouse.py")
    bench = json.loads(raw.group(1))
    ms = [r["median_ms"] for r in bench["results"]]

    conn = _db()
    try:
        partitions = _rows(conn, """
            SELECT c.relname AS partition, pg_get_expr(c.relpartbound, c.oid) AS bounds,
                   c.reltuples::bigint AS estimated_rows
            FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid
            WHERE i.inhparent = 'fingrid_observation'::regclass ORDER BY c.relname""")
        counts = {r["partition"]: r["rows"] for r in _rows(conn, """
            SELECT tableoid::regclass::text AS partition, count(*) AS rows
            FROM fingrid_observation GROUP BY tableoid""")}
    finally:
        conn.close()
    for p in partitions:
        p["rows"] = counts.get(p["partition"], 0)
        del p["estimated_rows"]

    _write("engineering.json", {
        "generated_at": _now(),
        "benchmark": {
            "source": "benchmarks/index_benchmark.md (scripts/benchmark_warehouse.py, median of 7 warm runs)",
            "query": f"one week of 1-minute grid frequency, {bench['matched_rows']:,} of {bench['total_rows']:,} rows",
            "no_index_ms": round(ms[0], 2),
            "indexed_ms": round(ms[1], 2),
            "partitioned_ms": round(ms[2], 2),
            "speedup_index_vs_none": round(ms[0] / ms[1], 1),
            "partitions_read": bench["results"][2]["relations"],
            "rows_discarded_without_index": bench["results"][0]["rows_removed"],
        },
        "partitioning": {
            "partition_count": len(partitions),
            "total_rows": sum(p["rows"] for p in partitions),
            "partitions": partitions,
        },
        "tests": {
            "total": _count_tests(None),
            "by_layer": {layer: _count_tests(layer) for layer in TEST_LAYERS},
            "load_test": "tests/load/locustfile.py (Locust, run in CI)",
            "ci_matrix": "Python 3.11 / 3.12 on PostgreSQL 15, plus PostgreSQL 14 and 16 on Python 3.11",
        },
    })


PARTS = {
    "fingrid-recent": export_fingrid_recent,
    "forecast-scorecard": export_forecast_scorecard,
    "co2-forecast": export_co2_forecast,
    "grid-events": export_grid_events,
    "fingrid-latest": export_fingrid_latest,
    "sql": export_sql_sources,
    "engineering": export_engineering,
}
DAILY_PARTS = ["fingrid-recent", "forecast-scorecard", "co2-forecast", "grid-events"]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--parts", nargs="+", choices=list(PARTS),
                        help=f"Only build these files (default: {' '.join(DAILY_PARTS)})")
    args = parser.parse_args()
    parts = args.parts or DAILY_PARTS
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Writing dashboard data to {os.path.relpath(OUT_DIR, ROOT)}/ ({', '.join(parts)})")
    for part in parts:
        PARTS[part]()


if __name__ == "__main__":
    main()
