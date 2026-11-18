"""
export_dashboard_data.py
~~~~~~~~~~~~~~~~~~~~~~~~
Build the static data files of the GitHub Pages dashboard (docs/data/) from the
Fingrid warehouse. Each file comes from the SQL in sql/analysis and sql/schema.

  fingrid_recent_daily.json   Daily wind and consumption, last 365 complete days   [part: fingrid-recent]
  forecast_scorecard.json     Error of Fingrid's own forecasts (13-17)             [part: forecast-scorecard]
  co2_forecast.json           Tomorrow's hourly CO2 intensity, backtest (18-19)    [part: co2-forecast]
  grid_events.json            Grid event log of the last year (20-21)              [part: grid-events]
  temperature.json            How much each degree of cold raises consumption (22-23) [part: temperature]
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


TEMPERATURE_SQL = {"days": "sql/analysis/22_temperature_daily.sql",
                   "fits": "sql/analysis/23_temperature_sensitivity.sql"}
TEMPERATURE_BIN_C = 3


def export_temperature(days: int = 365) -> None:
    sys.path.insert(0, os.path.join(ROOT, "src"))
    from analysis_window import default_window

    w = default_window(days=days)
    conn = _db()
    try:
        out = {}
        for part, path in TEMPERATURE_SQL.items():
            with open(os.path.join(ROOT, path), encoding="utf-8") as fh:
                out[part] = _rows(conn, fh.read(), w)
    finally:
        conn.close()
    daily, fits = out["days"], out["fits"]
    if len(fits) != 2 or len(daily) < 300:
        raise SystemExit(f"temperature: {len(daily)} days and {len(fits)} fits: run src/sync_fingrid.py first")

    # Mean consumption per temperature bin and day type, for the chart (presentation only).
    bins = {}
    for d in daily:
        b = int(d["temp_c"] // TEMPERATURE_BIN_C) * TEMPERATURE_BIN_C
        bins.setdefault((b, d["weekend"]), []).append(d["consumption_mw"])
    lo, hi = min(b for b, _ in bins), max(b for b, _ in bins)
    binned = [{"from_c": b, "to_c": b + TEMPERATURE_BIN_C,
               **{f"{k}_mw": round(sum(v) / len(v), 1) if (v := bins.get((b, k == "weekend"))) else None for k in ("weekday", "weekend")},
               **{f"{k}_days": len(bins.get((b, k == "weekend"), [])) for k in ("weekday", "weekend")}}
              for b in range(lo, hi + TEMPERATURE_BIN_C, TEMPERATURE_BIN_C)]
    coldest = min(daily, key=lambda d: d["temp_c"])
    warmest = max(daily, key=lambda d: d["temp_c"])
    _write("temperature.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0): temperature in Helsinki (178), Jyväskylä (182), Oulu (196) "
                  "and Rovaniemi (185), electricity consumption in Finland (124)",
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
        "model": "consumption = base_mw + mw_per_degree * max(balance_point - temperature, 0), fitted per day "
                 "type; the balance point (5-20 C) with the highest r2 is kept",
        "fits": _rounded(fits, 3),
        "bins": binned,
        "coldest_day": _rounded([coldest])[0],
        "warmest_day": _rounded([warmest])[0],
        "days": len(daily),
        "sql": list(TEMPERATURE_SQL.values()),
    })


WIND_ALLOCATION_SQL = "sql/analysis/24_wind_allocation_panel.sql"
WIND_ALLOCATION_PARTS = {"net_import_mw": "imports", "hydro_mw": "hydro", "other_mw": "other", "consumption_mw": "consumption"}
WIND_ALLOCATION_BORDERS = {"import_sweden_north_mw": "sweden_north", "import_sweden_central_mw": "sweden_central",
                           "import_estonia_mw": "estonia", "import_norway_mw": "norway",
                           "import_unmeasured_mw": "unmeasured"}
WIND_ALLOCATION_PLANTS = {"chp_district_heating_mw": "chp_district_heating", "chp_industrial_mw": "chp_industrial",
                          "reserve_and_small_mw": "reserve_and_small", "other_rest_mw": "rest"}


def export_wind_allocation(days: int = 365) -> None:
    """Where an extra MW of wind (and of nuclear) goes: src/wind_allocation.py on the hourly balance."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import numpy as np
    import wind_allocation as wa
    from analysis_window import default_window

    w = default_window(days=days)
    conn = _db()
    try:
        with open(os.path.join(ROOT, WIND_ALLOCATION_SQL), encoding="utf-8") as fh:
            rows = _rows(conn, fh.read(), w)
    finally:
        conn.close()
    if len(rows) < 24 * 300:
        raise SystemExit(f"wind-allocation: only {len(rows)} complete hours: run src/sync_fingrid.py first")

    def shares(fitted: dict, driver: str, parts: dict = WIND_ALLOCATION_PARTS) -> dict:
        # "pushed out" shares are minus the coefficient; consumption is the coefficient itself
        out = {}
        for response, name in parts.items():
            c = fitted["responses"][response][driver]
            sign = 1 if response == "consumption_mw" else -1
            lo, hi = sorted((sign * c["ci_low"], sign * c["ci_high"]))
            out[name] = {"share": round(sign * c["coef"], 3), "ci_low": round(lo, 3), "ci_high": round(hi, 3)}
        return out

    overall = wa.fit(rows, wa.RESPONSES + ("battery_mw",))
    seasons = wa.by_season(rows)
    measured = [(float(r["net_import_mw"]), float(r["net_import_measured_mw"])) for r in rows
                if r["net_import_measured_mw"] is not None]
    a, b = np.array(measured).T
    bat = overall["responses"]["battery_mw"]["wind_mw"]
    detail = wa.breakdown(rows)
    if detail is None:
        raise SystemExit("wind-allocation: too few hours with every border and plant: run src/sync_fingrid.py first")
    parents = {"net_import_mw": "imports", "other_mw": "other"}
    breakdown = {"hours": detail["hours"]}
    for driver, key in (("wind_mw", "wind"), ("nuclear_mw", "nuclear")):
        breakdown[key] = {"total": shares(detail, driver, parents),
                          "borders": shares(detail, driver, WIND_ALLOCATION_BORDERS),
                          "plants": shares(detail, driver, WIND_ALLOCATION_PLANTS)}
    breakdown["seasons"] = []
    for name, months in wa.SEASONS.items():
        f = wa.breakdown([r for r in rows if r["month_fi"] in months], min_hours=24 * 30)
        if f is not None:
            breakdown["seasons"].append({"season": name, "hours": f["hours"],
                                         "borders": shares(f, "wind_mw", WIND_ALLOCATION_BORDERS),
                                         "plants": shares(f, "wind_mw", WIND_ALLOCATION_PLANTS)})
    _write("wind_allocation.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0): consumption (124), production (74), wind (75), nuclear (188), "
                  "hydro (191), measured net export (194), battery discharge (398), temperatures (178, 182, 196, 185), "
                  "border flows (60, 61, 55, 57), CHP and reserve production (201, 202, 205)",
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
        "hours": overall["hours"],
        "model": "hourly OLS of imports, hydro, other production and consumption on wind, nuclear and "
                 f"max({wa.HEATING_BALANCE_C:g} C - temperature, 0), with Finnish hour-of-day, weekday and month fixed "
                 f"effects; 95 % intervals from Newey-West standard errors ({wa.HAC_LAGS} hourly lags). "
                 "Associations after controlling for weather and calendar, not proven causal effects.",
        "identity": "consumption = wind + nuclear + hydro + other + net imports (Fingrid's definition of consumption), "
                    "so the four shares of +1 MW add up to 1",
        "wind": shares(overall, "wind_mw"),
        "nuclear": shares(overall, "nuclear_mw"),
        "r2": {WIND_ALLOCATION_PARTS[k]: round(v["r2"], 3) for k, v in overall["responses"].items() if k in WIND_ALLOCATION_PARTS},
        "seasons": [{"season": name, "months": list(wa.SEASONS[name]), "hours": f["hours"], "wind": shares(f, "wind_mw")}
                    for name, f in seasons.items()],
        "breakdown": breakdown,
        "battery_per_mw_wind": {"coef": round(bat["coef"], 4), "ci_low": round(bat["ci_low"], 4), "ci_high": round(bat["ci_high"], 4)},
        "net_import_check": {"hours": len(measured), "r_identity_vs_measured_194": round(float(np.corrcoef(a, b)[0, 1]), 4),
                             "mean_difference_mw": round(float((a - b).mean()), 1)},
        "sql": [WIND_ALLOCATION_SQL],
        "code": "src/wind_allocation.py",
    })


FORECAST_RANGES_SQL = "sql/analysis/25_forecast_errors_hourly.sql"
RANGES_RECORD_DAYS = 14


def export_forecast_ranges() -> None:
    """Calibrated 80 % / 95 % ranges around Fingrid's day-ahead forecasts for tomorrow, and the backtest."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import numpy as np
    import forecast_ranges as fr
    from analysis_window import tomorrow_fi

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=3)
    conn = _db()
    try:
        with open(os.path.join(ROOT, FORECAST_RANGES_SQL), encoding="utf-8") as fh:
            rows = _rows(conn, fh.read(), {"start": end - timedelta(days=430), "end": end})
    finally:
        conn.close()

    tomorrow = tomorrow_fi()
    r1 = lambda v: None if v is None or not np.isfinite(v) else round(float(v), 1)
    out = {}
    for variable in ("wind", "consumption"):
        s = fr.Series([r for r in rows if r["variable"] == variable])
        known = sorted({d for d, a in zip(s.day, s.actual) if not np.isnan(a)})
        days = [d for d in known if s.known_days(s.calibration(d)) >= fr.MIN_CAL_DAYS]
        if len(days) < 60:
            raise SystemExit(f"forecast-ranges: only {len(days)} {variable} days to backtest: run src/sync_fingrid.py first")
        bt = fr.backtest(s, variable, days)
        future = sorted({d for d, a in zip(s.day, s.actual) if np.isnan(a) and d >= tomorrow - timedelta(days=1)})
        target = tomorrow if tomorrow in future else (future[-1] if future else None)
        r = fr.ranges_for_day(s, target, fr.PUBLISHED, bt["alphas"]) if target else None
        if r is None:
            raise SystemExit(f"forecast-ranges: no {variable} forecast to put ranges around")
        b = {lv: tuple(fr.clip(variable, x) for x in r["bounds"][lv]) for lv in fr.LEVELS}
        hours = [{"hour_fi": int(s.hour[i]), "forecast_mw": r1(s.forecast[i]),
                  "lo80_mw": r1(b[0.8][0][k]), "hi80_mw": r1(b[0.8][1][k]),
                  "lo95_mw": r1(b[0.95][0][k]), "hi95_mw": r1(b[0.95][1][k])} for k, i in enumerate(r["idx"])]
        record = []
        for d in days[-RANGES_RECORD_DAYS:]:
            p = bt["published"].get(d)
            if p is None:
                continue
            lo, hi = (fr.clip(variable, x) for x in p["bounds"][0.8])
            for k, i in enumerate(p["idx"]):
                record.append({"day_fi": d.isoformat(), "hour_fi": int(s.hour[i]), "actual_mw": r1(s.actual[i]),
                               "forecast_mw": r1(s.forecast[i]), "lo80_mw": r1(lo[k]), "hi80_mw": r1(hi[k])})
        hit = [x["lo80_mw"] <= x["actual_mw"] <= x["hi80_mw"] for x in record if x["actual_mw"] is not None]
        out[variable] = {
            "target_day": target.isoformat(),
            "hours": hours,
            "mean_width80_mw": r1(np.mean([h["hi80_mw"] - h["lo80_mw"] for h in hours])),
            "mean_width95_mw": r1(np.mean([h["hi95_mw"] - h["lo95_mw"] for h in hours])),
            "alphas": {str(lv): round(a, 4) for lv, a in bt["alphas"].items()},
            "backtest": {"first_day": days[0].isoformat(), "last_day": days[-1].isoformat(), "days": len(days),
                         "methods": {m: {str(lv): {k: (round(v, 4) if k == "coverage" else r1(v) if k != "hours" else v)
                                                   for k, v in per[lv].items()} for lv in fr.LEVELS}
                                     for m, per in bt["table"].items()}},
            "record_days": RANGES_RECORD_DAYS,
            "record_coverage80": round(sum(hit) / len(hit), 4) if hit else None,
            "record": record,
        }
    _write("forecast_ranges.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0): day-ahead forecasts of wind (246) and consumption (165), "
                  "measured wind (75) and consumption (124)",
        "target_is_tomorrow": all(v["target_day"] == tomorrow.isoformat() for v in out.values()),
        "method": f"{fr.PUBLISHED}: split conformal prediction on Fingrid's own recent errors, grouped by six-hour "
                  f"block and forecast-level tercile (Mondrian), with adaptive conformal inference (gamma {fr.GAMMA}) "
                  f"correcting the miss rate day by day. Each day is calibrated on the {fr.CAL_DAYS} days ending two "
                  "days before it, i.e. only on errors known when Fingrid issues its forecast.",
        "levels": list(fr.LEVELS),
        "methods_explained": {
            "global": "one set of quantiles from all recent errors",
            "by_hour": "quantiles per six-hour block of the Finnish day",
            "mondrian": "quantiles per six-hour block and forecast-level tercile",
            "adaptive": "mondrian, with the target miss rate adjusted after every known day (published)",
        },
        "wind": out["wind"],
        "consumption": out["consumption"],
        "sql": [FORECAST_RANGES_SQL],
        "code": "src/forecast_ranges.py",
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
HYDRO_STATE_SQL = "sql/analysis/27_hydrology_state.sql"
HYDRO_DAYS = 3 * 365
HYDRO_PART_NAMES = {"hydro_mw": "hydro", "net_import_mw": "imports", "other_mw": "other", "consumption_mw": "consumption"}


def export_hydro_flex() -> None:
    """Does hydro make more room for wind when the reservoirs are full? src/hydro_flex.py over three years."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import hydro_flex as hf
    from analysis_window import default_window

    w = default_window(days=HYDRO_DAYS)
    conn = _db()
    try:
        with open(os.path.join(ROOT, WIND_ALLOCATION_SQL), encoding="utf-8") as fh:
            panel = _rows(conn, fh.read(), w)
        with open(os.path.join(ROOT, HYDRO_STATE_SQL), encoding="utf-8") as fh:
            state = _rows(conn, fh.read(), {"start": (w["start"] - timedelta(days=2)).date(), "end": w["end"].date()})
        cur_state = _rows(conn, "SELECT series, max(day) AS last_day FROM hydrology_daily GROUP BY series ORDER BY series")
    finally:
        conn.close()
    rows = hf.join_state(panel, state)
    if len(rows) < 24 * 365 * 2:
        # Until the warehouse holds two years (a one-off `sync_fingrid.py --from`), keep the published file
        # rather than failing the whole daily refresh.
        print(f"::warning::hydro-flex: only {len(rows)} hours with a water state; hydro_flex.json left as it is. "
              "Run the refresh once with history_from to fill older Fingrid history.")
        return
    fitted = hf.fit(rows)
    r3 = lambda v: round(float(v), 3)
    # Shares on days that actually occurred (10th, 50th and 90th percentile of the storage index),
    # not at +/-1: the averaged index varies much less than its parts, so +1 is near the fullest day seen.
    import numpy as np
    days_z = np.array(sorted({(str(r["day"])[:10], r["storage_z"]) for r in state if r["storage_z"] is not None}))
    zs = days_z[:, 1].astype(float)
    at = []
    for q in (10, 50, 90):
        z = float(np.percentile(zs, q))
        at.append({"percentile": q, "storage_z": r3(z),
                   "shares": {HYDRO_PART_NAMES[k]: {kk: r3(vv) for kk, vv in hf.share_at(fitted, k, z).items()}
                              for k in hf.PARTS}})
    inter = {HYDRO_PART_NAMES[k]: {kk: (round(vv, 4) if kk == "p_value" else r3(vv))
                                   for kk, vv in hf.interaction(fitted, k).items()} for k in hf.PARTS}
    inflow = {HYDRO_PART_NAMES[k]: {kk: (round(vv, 4) if kk == "p_value" else r3(vv))
                                    for kk, vv in hf.interaction(fitted, k, "inflow_z").items()} for k in hf.PARTS}
    terciles = [{"tercile": t["tercile"], "hours": t["hours"], "storage_mean": r3(t["state_mean"]),
                 "shares": {HYDRO_PART_NAMES[k]: r3(v) for k, v in t["shares"].items()},
                 "hydro_ci": [r3(x) for x in t["hydro_ci"]]} for t in hf.by_tercile(rows)]
    daily = [{"day": str(r["day"])[:10], "storage_z": None if r["storage_z"] is None else r3(r["storage_z"]),
              "inflow_z": None if r["inflow_z"] is None else r3(r["inflow_z"])} for r in state]
    _write("hydro_flex.json", {
        "generated_at": _now(),
        "source": "Fingrid Open Data API (CC BY 4.0): the hourly balance of sql/analysis/24; SYKE Hydrology API "
                  "(Finnish Environment Institute, CC BY 4.0): water levels of Lokka, Porttipahta, Oulujärvi, Saimaa "
                  "and Näsijärvi and discharge of the unregulated Tornionjoki; NVE reservoir statistics (NLOD)",
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
        "hours": fitted["hours"],
        "model": "hourly OLS of hydro, imports, other production and consumption on wind, wind x storage and "
                 "wind x inflow (the day before, each against its 2000-2022 norm for the date), storage, inflow, "
                 "nuclear and heating degrees, with hour, weekday, month and year fixed effects; Newey-West 95 % "
                 "intervals. Associations, not proven causes.",
        "storage": "mean z-score of five reservoir and lake levels against the same calendar day in 2000-2022 "
                   "(0 = normal for the date; one unit = one standard deviation of a single reservoir's level)",
        "share_at_storage": at,
        "storage_range": {"min": r3(zs.min()), "max": r3(zs.max()), "sd": r3(zs.std())},
        "per_sd_storage": inter,
        "per_sd_inflow": inflow,
        "terciles": terciles,
        "daily_state": daily,
        "latest_data": {r["series"]: str(r["last_day"])[:10] for r in cur_state},
        "sql": [WIND_ALLOCATION_SQL, HYDRO_STATE_SQL],
        "code": ["src/hydro_flex.py", "src/hydrology.py"],
    })


PRICE_WIND_SQL = "sql/analysis/29_price_wind_panel.sql"


def export_price_wind() -> None:
    """Does wind make electricity cheaper? src/price_wind.py on three years of ENTSO-E prices."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import price_wind as pw
    from analysis_window import default_window

    w = default_window(days=HYDRO_DAYS)
    conn = _db()
    try:
        with open(os.path.join(ROOT, PRICE_WIND_SQL), encoding="utf-8") as fh:
            panel = _rows(conn, fh.read(), w)
        with open(os.path.join(ROOT, HYDRO_STATE_SQL), encoding="utf-8") as fh:
            state = _rows(conn, fh.read(), {"start": (w["start"] - timedelta(days=2)).date(), "end": w["end"].date()})
        latest = _rows(conn, "SELECT area, max(end_time) AS last_end FROM entsoe_price GROUP BY area ORDER BY area")
    finally:
        conn.close()
    rows = pw.join_state(panel, state)
    if len(rows) < 24 * 365:
        # No ENTSO-E token (a fork) or a fresh archive: keep the published file rather than fail the refresh.
        print(f"::warning::price-wind: only {len(rows)} hours with a price and a water state; price_wind.json left as it is.")
        return
    r1, r3 = (lambda v: round(float(v), 1)), (lambda v: round(float(v), 3))
    fitted = pw.fit(rows)
    eff = lambda f, s=0.0: {k: r1(v) for k, v in pw.per_gw(f, s).items()}
    inter = pw.storage_interaction(fitted)
    _write("price_wind.json", {
        "generated_at": _now(),
        "source": "ENTSO-E Transparency Platform: day-ahead prices for FI, SE1, SE3, EE and NO4; Fingrid Open Data "
                  "(CC BY 4.0): day-ahead wind (246) and consumption (165) forecasts, measured wind (75), nuclear (188) "
                  "and temperatures (178, 182, 196, 185); SYKE Hydrology API (CC BY 4.0): reservoir levels",
        "window_start": w["start"].strftime("%Y-%m-%d"),
        "window_end_exclusive": w["end"].strftime("%Y-%m-%d"),
        "hours": fitted["hours"],
        "r2": r3(fitted["r2"]),
        "model": "hourly OLS of the Finnish day-ahead price on Fingrid's day-ahead wind and consumption forecasts, "
                 "wind x storage, nuclear, heating degrees, reservoir storage and inflow of the day before (against "
                 "their 2000-2022 norm), with hour, weekday, month and year fixed effects; Newey-West 95 % intervals "
                 "(24 h). Associations, not proven causes.",
        "per_gw": eff(fitted),
        "per_gw_checks": {"prices_clipped_1_99": eff(pw.fit(rows, clip=(1, 99))),
                          "measured_wind": eff(pw.fit(rows, "wind_mw"))},
        "consumption_per_gw": {k: r1(v) for k, v in pw.consumption_effect(fitted).items()},
        "at_storage": [{"percentile": a["percentile"], "storage_z": r3(a["storage_z"]),
                        **{k: r1(a[k]) for k in ("eur_per_gw", "ci_low", "ci_high")}}
                       for a in pw.at_storage_percentiles(fitted, state)],
        "storage_interaction": {"per_unit": r1(inter["per_unit"]), "ci_low": r1(inter["ci_low"]),
                                "ci_high": r1(inter["ci_high"]), "p_value": round(inter["p_value"], 4)},
        "by_wind_bin": [{k: (r3(v) if k.startswith("share") else r1(v) if isinstance(v, float) else v)
                         for k, v in b.items()} for b in pw.by_wind_bin(rows)],
        "capture_by_year": [{"year": c["year"], "hours": c["hours"], "partial": c["hours"] < 24 * 360,
                             "average": r1(c["average"]), "wind_captured": r1(c["wind_captured"]),
                             "ratio": r3(c["ratio"])} for c in pw.capture_by_year(rows)],
        "latest_price": {r["area"]: r["last_end"] for r in latest},
        "sql": [PRICE_WIND_SQL, HYDRO_STATE_SQL],
        "code": ["src/price_wind.py", "src/entsoe_prices.py"],
    })


WEATHER_MODEL_SQL = "sql/analysis/26_weather_model_panel.sql"
WEATHER_RECORD_DAYS = 14


def export_weather_model() -> None:
    """Can public weather forecasts and the calendar beat Fingrid? Backtest, tomorrow, and Fingrid by kind of day."""
    sys.path.insert(0, os.path.join(ROOT, "src"))
    import weather_model as wm
    from analysis_window import tomorrow_fi

    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=3)
    conn = _db()
    try:
        with open(os.path.join(ROOT, WEATHER_MODEL_SQL), encoding="utf-8") as fh:
            rows = _rows(conn, fh.read(), {"start": end - timedelta(days=430), "end": end})
    finally:
        conn.close()
    if len(rows) < 24 * (wm.BACKTEST_DAYS + wm.MIN_TRAIN_DAYS):
        raise SystemExit(f"weather-model: only {len(rows)} hours of weather: run src/openmeteo_forecast.py fetch first")
    df = wm.panel(rows)
    r1 = lambda v: None if v is None or v != v else round(float(v), 1)          # v != v: NaN
    tomorrow = tomorrow_fi()
    out = {}
    for variable in ("wind", "consumption"):
        bt = wm.backtest(df, variable)
        if bt["days"] < 60:
            raise SystemExit(f"weather-model: only {bt['days']} {variable} days to backtest")
        rec = bt["rows"][bt["rows"]["day"] >= sorted(bt["rows"]["day"].unique())[-WEATHER_RECORD_DAYS]]
        future = sorted(d for d in df["day"].unique() if d >= tomorrow - timedelta(days=1))
        target, fc = None, None
        for d in ([tomorrow] if tomorrow in future else []) + future[::-1]:
            fc = wm.forecast_day(df, variable, d)
            if fc is not None:
                target = d
                break
        if fc is None:
            raise SystemExit(f"weather-model: no day with a Fingrid {variable} forecast and weather to forecast")
        local = fc["hour_start"].dt.tz_convert(wm.HELSINKI)
        out[variable] = {
            "target_day": target.isoformat(),
            "hours": [{"hour_fi": int(t.hour), "fingrid_mw": r1(f), "weather_mw": r1(w), "weather_fingrid_mw": r1(c)}
                      for t, f, w, c in zip(local, fc["fingrid"], fc["weather"], fc["weather_fingrid"])],
            "backtest": {k: bt[k] for k in ("days", "hours", "first_day", "last_day")}
                        | {"mae_mw": {k: r1(v) for k, v in bt["mae_mw"].items()},
                           "rmse_mw": {k: r1(v) for k, v in bt["rmse_mw"].items()},
                           "bias_mw": {k: r1(v) for k, v in bt["bias_mw"].items()},
                           "skill_vs_fingrid": {k: round(v, 4) for k, v in bt["skill_vs_fingrid"].items()},
                           "diebold_mariano": {m: {k: (round(v, 4) if isinstance(v, float) else v) for k, v in d.items()}
                                               for m, d in bt["diebold_mariano"].items()},
                           "by_month": [{k: (v if k == "month" else r1(v)) for k, v in m.items()} for m in bt["by_month"]]},
            "record_days": WEATHER_RECORD_DAYS,
            "record": [{"day_fi": str(r["day"]), "hour_fi": int(r["hour_fi"]), "actual_mw": r1(r["actual"]),
                        "fingrid_mw": r1(r["fingrid"]), "weather_mw": r1(r["weather"]),
                        "weather_fingrid_mw": r1(r["weather_fingrid"])} for _, r in rec.iterrows()],
        }
    _write("weather_model.json", {
        "generated_at": _now(),
        "source": "Open-Meteo Previous Runs API (CC BY 4.0): temperature and 100 m wind speed forecast 48 h ahead at "
                  "15 places; Fingrid Open Data API (CC BY 4.0): wind (75), consumption (124), day-ahead forecasts "
                  "(246, 165), wind capacity (268); Finnish public holidays computed",
        "target_is_tomorrow": all(v["target_day"] == tomorrow.isoformat() for v in out.values()),
        "models": {
            "fingrid": "Fingrid's own day-ahead forecast, issued at 12:00 Finnish time the day before",
            "weather": "gradient-boosted trees on the weather forecast 48 h earlier, the calendar (holidays, eves, "
                       "bridge days, Christmas period, July, sun elevation) and history known at issue time",
            "weather_fingrid": "Fingrid's forecast plus a heavily regularised learned correction from the same inputs",
        },
        "method": f"Rolling origin: the last {wm.BACKTEST_DAYS} days are forecast with models refitted every "
                  f"{wm.REFIT_DAYS} days on everything known two days before. Diebold-Mariano test on daily mean "
                  f"absolute errors with Newey-West variance ({wm.DM_LAGS} lags); a p-value above 0.05 means the "
                  "difference from Fingrid could be chance. Six settings of the correction model were tried on this "
                  "backtest and none beat Fingrid by more than 2 %; the most regularised one is published.",
        "wind": out["wind"],
        "consumption": out["consumption"],
        "fingrid_by_day_type": [{k: (r1(v) if k.endswith("_mw") else v) for k, v in d.items()}
                                for d in wm.errors_by_day_type(df[df["day"] < tomorrow - timedelta(days=1)])],
        "sql": [WEATHER_MODEL_SQL],
        "code": ["src/weather_model.py", "src/openmeteo_forecast.py", "src/finnish_calendar.py"],
    })


PAGE_SQL_FILES = [
    "sql/schema/13_fingrid_warehouse.sql",
    "sql/schema/14_co2_forecast.sql",
    "sql/schema/15_grid_events.sql",
    "sql/analysis/13_forecast_scorecard.sql",
    "sql/analysis/17_forecast_error_vs_balancing.sql",
    "sql/analysis/23_temperature_sensitivity.sql",
    "sql/analysis/24_wind_allocation_panel.sql",
    "src/wind_allocation.py",
    "sql/analysis/25_forecast_errors_hourly.sql",
    "src/forecast_ranges.py",
    "sql/analysis/26_weather_model_panel.sql",
    "src/weather_model.py",
    "sql/analysis/27_hydrology_state.sql",
    "src/hydro_flex.py",
    "sql/analysis/28_consumption_hourly.sql",
    "src/strike_effect.py",
    "sql/analysis/29_price_wind_panel.sql",
    "src/price_wind.py",
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
        datasets = _rows(conn, "SELECT count(*) AS n FROM fingrid_dataset")[0]["n"]
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
        "datasets": datasets,
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
    "temperature": export_temperature,
    "wind-allocation": export_wind_allocation,
    "forecast-ranges": export_forecast_ranges,
    "weather-model": export_weather_model,
    "hydro-flex": export_hydro_flex,
    "price-wind": export_price_wind,
    "fingrid-latest": export_fingrid_latest,
    "sql": export_sql_sources,
    "engineering": export_engineering,
}
DAILY_PARTS = ["fingrid-recent", "forecast-scorecard", "co2-forecast", "grid-events", "temperature", "wind-allocation",
               "forecast-ranges", "weather-model", "hydro-flex", "price-wind"]


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
