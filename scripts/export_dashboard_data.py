"""
export_dashboard_data.py
~~~~~~~~~~~~~~~~~~~~~~~~
Rebuild the static data files used by the GitHub Pages dashboard (docs/data/).

  fingrid_2023_daily.json    Real Fingrid data (data/raw/grid_data.csv), daily means
  wind_validation_2023.json  Real vs. synthetic wind, from the latest daily
                             outputs/08_real_vs_synthetic_comparison_*.csv
  api_snapshot.json          Overview, trend and ranking from the API, shown
                             instantly while the free Render service wakes up

Usage (from the repository root):
    python scripts/export_dashboard_data.py                 # all three files
    python scripts/export_dashboard_data.py --skip-snapshot # local files only
    python scripts/export_dashboard_data.py --api-url http://127.0.0.1:8000
"""

import argparse
import glob
import json
import math
import os
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


def export_fingrid() -> None:
    grid = pd.read_csv(os.path.join(ROOT, "data", "raw", "grid_data.csv"), parse_dates=["recorded_at"])
    grid["day"] = grid["recorded_at"].dt.tz_convert("UTC").dt.strftime("%Y-%m-%d")
    daily = grid.pivot_table(index="day", columns="metric", values="value", aggfunc="mean").sort_index()
    monthly = daily.groupby(daily.index.str[:7]).mean()
    _write("fingrid_2023_daily.json", {
        "source": "Fingrid Open Data API, dataset 75 (wind power production) and 124 "
                  "(electricity consumption), Finland, hourly values averaged per UTC day",
        "file": "data/raw/grid_data.csv",
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
            "windiest_month": monthly.wind_production.idxmax(),
            "calmest_month": monthly.wind_production.idxmin(),
            "wind_max_day": daily.wind_production.idxmax(),
            "wind_min_day": daily.wind_production.idxmin(),
        },
    })


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
    args = parser.parse_args()

    os.makedirs(OUT_DIR, exist_ok=True)
    print(f"Writing dashboard data to {os.path.relpath(OUT_DIR, ROOT)}/")
    export_fingrid()
    export_validation()
    if not args.skip_snapshot:
        export_snapshot(args.api_url.rstrip("/"))


if __name__ == "__main__":
    main()
