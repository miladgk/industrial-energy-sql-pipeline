"""
export_dashboard_data.py
~~~~~~~~~~~~~~~~~~~~~~~~
Rebuild the static data files used by the GitHub Pages dashboard (docs/data/).

  fingrid_2023_daily.json     Real Fingrid data (data/raw/grid_data.csv), daily means   [part: fingrid]
  wind_validation_2023.json   Real vs. synthetic wind, from the latest daily
                              outputs/08_real_vs_synthetic_comparison_*.csv           [part: validation]
  api_snapshot.json           Overview, trend and ranking from the API, shown
                              instantly while the free Render service wakes up        [part: snapshot]
  fingrid_recent_daily.json   Last 365 complete days fetched live from the Fingrid
                              API (needs FINGRID_API_KEY or config.yaml)              [part: fingrid-recent]

Usage (from the repository root):
    python scripts/export_dashboard_data.py                          # fingrid, validation, snapshot
    python scripts/export_dashboard_data.py --skip-snapshot          # local files only
    python scripts/export_dashboard_data.py --parts fingrid-recent   # what the weekly workflow runs
    python scripts/export_dashboard_data.py --api-url http://127.0.0.1:8000
"""

import argparse
import glob
import json
import math
import os
import sys
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


def export_fingrid() -> None:
    grid = pd.read_csv(os.path.join(ROOT, "data", "raw", "grid_data.csv"))
    _write("fingrid_2023_daily.json", _daily_grid_payload(grid, {"file": "data/raw/grid_data.csv"}))


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
    _write("wind_validation_2023.json", {
        "source": f"outputs/{os.path.basename(daily)} (sql/analysis/08_real_vs_synthetic_comparison.sql), "
                  "run on a full-year synthetic dataset",
        "n_days": n,
        "pearson_r": round(r, 4),
        "p_value": round(p, 3),
        "days": [{"day": d, "real_z": round(float(a), 3), "synthetic_z": round(float(b), 3)}
                 for d, a, b in zip(df.day_label, df.real_z, df.synthetic_z)],
    })


def export_snapshot(api_url: str) -> None:
    def get(path: str) -> dict:
        with urllib.request.urlopen(api_url + path, timeout=120) as resp:
            return json.load(resp)

    _write("api_snapshot.json", {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "api_url": api_url,
        "overview": get("/api/overview"),
        "trend": get("/api/output-trend?hours=24"),
        "ranking": get("/api/facilities/ranking"),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--api-url", default=DEFAULT_API, help="API base URL for the snapshot")
    parser.add_argument("--skip-snapshot", action="store_true", help="Do not call the API")
    parser.add_argument("--parts", nargs="+", choices=["fingrid", "validation", "snapshot", "fingrid-recent"],
                        help="Only build these files (default: fingrid validation snapshot)")
    parser.add_argument("--recent-days", type=int, default=365, help="Window for fingrid-recent (days)")
    args = parser.parse_args()

    parts = args.parts or ["fingrid", "validation"] + ([] if args.skip_snapshot else ["snapshot"])
    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Writing dashboard data to {os.path.relpath(OUT_DIR, ROOT)}/ ({', '.join(parts)})")
    if "fingrid" in parts:
        export_fingrid()
    if "validation" in parts:
        export_validation()
    if "snapshot" in parts:
        export_snapshot(args.api_url.rstrip("/"))
    if "fingrid-recent" in parts:
        export_fingrid_recent(args.recent_days)


if __name__ == "__main__":
    main()
