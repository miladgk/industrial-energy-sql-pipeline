"""
fetch_grid_data.py
~~~~~~~~~~~~~~~~~~
Pulls hourly electricity consumption and wind power production for Finland
from the Fingrid Open Data API (data.fingrid.fi). By default it fetches the
full year 2023 into data/raw/grid_data.csv; --start/--end/--output select
another window (used by scripts/export_dashboard_data.py for recent data).

The API key is read from the FINGRID_API_KEY environment variable (e.g. a
GitHub Actions secret) or from 'fingrid_api_key' in the git-ignored
config.yaml. The script fails loudly if no key is present or fetching fails.

To allow generating synthetic mock data for offline testing or CI, the caller
must explicitly provide the '--allow-mock' CLI flag. Every row is stamped
with a 'source' column ('fingrid' vs 'mock') so real vs fake data is
unambiguously queryable in the database.

API details:
  - Endpoint: https://data.fingrid.fi/api/datasets/{dataset_id}/data
  - Dataset ID 124: Electricity consumption in Finland (MW)
  - Dataset ID 75: Wind power generation - 15 min data (downsampled here to hourly)
  - x-api-key: HTTP header authentication
  - Rate limit: requests are spaced 2 s apart; HTTP 429 triggers exponential backoff.
"""

import os
import sys
import time
import argparse
import urllib.request
import urllib.parse
import urllib.error
import json
import yaml
import pandas as pd
import numpy as np

# Fingrid API configuration
API_URL = "https://data.fingrid.fi/api/datasets/{dataset_id}/data"
DATASETS = {
    124: "consumption",
    75: "wind_production"
}

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "..", "config.yaml")
OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "raw", "grid_data.csv")


def load_api_key() -> str:
    """Return the Fingrid API key from FINGRID_API_KEY, else from config.yaml."""
    env_key = os.environ.get("FINGRID_API_KEY", "").strip()
    if env_key:
        return env_key
    if not os.path.exists(CONFIG_PATH):
        return ""
    with open(CONFIG_PATH, "r") as fh:
        try:
            cfg = yaml.safe_load(fh)
            return (cfg.get("fingrid_api_key") or "").strip()
        except Exception:
            return ""


def get_mock_grid_data() -> pd.DataFrame:
    """
    Generate high-quality, realistic mock grid data for Finland for the full year of 2023.
    Stamps every row with source='mock'.
    """
    print("⚠ WARNING: Using explicit --allow-mock flag. Generating synthetic MOCK data with source='mock'...")
    
    timestamps = pd.date_range(
        start="2023-01-01 00:00:00+00:00",
        end="2023-12-31 23:00:00+00:00",
        freq="1h"
    )
    n_hours = len(timestamps)
    rng = np.random.default_rng(42)
    
    hour = timestamps.hour.values
    day_of_year = timestamps.dayofyear.values
    
    seasonal_factor = 9000 + 2000 * np.cos(2 * np.pi * (day_of_year - 15) / 365)
    diurnal_factor = 1000 * np.sin(2 * np.pi * (hour - 6) / 24) - 500 * np.cos(4 * np.pi * (hour - 18) / 24)
    weekday = timestamps.weekday.values
    weekend_factor = np.where(weekday >= 5, 0.90, 1.0)
    
    consumption_noise = rng.normal(0, 300, size=n_hours)
    consumption = ((seasonal_factor + diurnal_factor) * weekend_factor + consumption_noise).round(4)
    consumption = np.clip(consumption, 5000, 15000)

    wind_base = 1800 + 400 * np.cos(2 * np.pi * (day_of_year - 45) / 365)
    wind_noise = rng.normal(0, 450, size=n_hours)
    
    wind = np.zeros(n_hours)
    wind[0] = wind_base[0] + wind_noise[0]
    for t in range(1, n_hours):
        wind[t] = 0.92 * wind[t-1] + 0.08 * wind_base[t] + wind_noise[t]
        
    wind = wind.round(4)
    wind = np.clip(wind, 100, 5500)
    
    df_cons = pd.DataFrame({
        "dataset_id": 124,
        "country": "FI",
        "recorded_at": timestamps,
        "value": consumption,
        "metric": "consumption",
        "source": "mock"
    })
    
    df_wind = pd.DataFrame({
        "dataset_id": 75,
        "country": "FI",
        "recorded_at": timestamps,
        "value": wind,
        "metric": "wind_production",
        "source": "mock"
    })
    
    df_grid = pd.concat([df_cons, df_wind], ignore_index=True)
    return df_grid


def fetch_dataset_chunk(dataset_id: int, api_key: str, start_time: str, end_time: str) -> list:
    """Fetch data for a specific dataset ID and time chunk with retry logic and rate limit compliance."""
    params = {
        "startTime": start_time,
        "endTime": end_time,
        "pageSize": 20000
    }
    query_string = urllib.parse.urlencode(params)
    url = f"{API_URL.format(dataset_id=dataset_id)}?{query_string}"
    
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/json")
    req.add_header("x-api-key", api_key)
    
    max_retries = 3
    backoff = 2.0
    
    for attempt in range(max_retries):
        time.sleep(2.0)
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                if response.status == 200:
                    data = json.loads(response.read().decode("utf-8"))
                    return data.get("data", [])
                else:
                    print(f"  Warning: Received status code {response.status}. Retrying...")
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print(f"  [429 Too Many Requests] Rate limit hit. Backing off for {backoff}s...")
                time.sleep(backoff)
                backoff *= 2.0
            elif e.code in (401, 403):
                raise PermissionError("Fingrid API key is unauthorized or invalid (401/403).")
            else:
                print(f"  HTTP error: {e.code}. Retrying in {backoff}s...")
                time.sleep(backoff)
                backoff *= 2.0
        except Exception as e:
            print(f"  Network error: {e}. Retrying in {backoff}s...")
            time.sleep(backoff)
            backoff *= 2.0
            
    raise RuntimeError(f"Failed to fetch dataset {dataset_id} for range {start_time} to {end_time} after {max_retries} attempts.")


def _month_windows(start: str, end: str) -> list:
    """Split [start, end) into windows that never cross a month boundary."""
    start_ts, end_ts = pd.Timestamp(start), pd.Timestamp(end)
    edges = [start_ts] + [m for m in pd.date_range(start_ts, end_ts, freq="MS") if start_ts < m < end_ts] + [end_ts]
    return list(zip(edges[:-1], edges[1:]))


def fetch_fingrid_data(api_key: str, start: str = "2023-01-01", end: str = "2024-01-01") -> pd.DataFrame:
    """Fetch hourly grid data for [start, end) in month-sized requests."""
    print(f"Connecting to Fingrid Open Data API ({start} to {end}) ...")
    windows = _month_windows(start, end)
    all_chunks = []

    for dataset_id, metric in DATASETS.items():
        print(f"Fetching dataset {dataset_id} ({metric}) chunk-by-chunk ...")
        for win_start, win_end in windows:
            start_str = win_start.strftime("%Y-%m-%dT%H:%M:%SZ")
            end_str = (win_end - pd.Timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

            print(f"  -> Pulling chunk: {win_start.date()} to {win_end.date()} ...")
            chunk_data = fetch_dataset_chunk(dataset_id, api_key, start_str, end_str)
            if not chunk_data:
                raise RuntimeError(f"API returned empty data for {metric} from {win_start.date()} to {win_end.date()}.")
                
            df_chunk = pd.DataFrame(chunk_data)
            df_chunk["dataset_id"] = dataset_id
            df_chunk["metric"] = metric
            df_chunk["country"] = "FI"
            all_chunks.append(df_chunk)
            
    df_raw = pd.concat(all_chunks, ignore_index=True)
    df_raw["recorded_at"] = pd.to_datetime(df_raw["startTime"])
    df_raw["value"] = pd.to_numeric(df_raw["value"])
    
    print("Downsampling 15-minute readings to hourly average (mean) ...")
    df_raw = df_raw.set_index("recorded_at")
    df_hourly = df_raw.groupby(["dataset_id", "metric", "country"]).resample("1h")["value"].mean().reset_index()

    # --- Data quality: fill Fingrid source gaps ---
    # NaN = hours where Fingrid had no 15-min readings; interpolate linearly (max 3 consecutive).
    # Negatives = instrument noise near zero (e.g. DST correction artefacts); clamp to 0.
    nan_before = int(df_hourly["value"].isna().sum())
    if nan_before:
        df_hourly["value"] = df_hourly.groupby("metric")["value"].transform(
            lambda s: s.interpolate(method="linear", limit=3, limit_direction="both")
        )
        nan_after = int(df_hourly["value"].isna().sum())
        print(f"  → Interpolated {nan_before} NaN gap(s) in Fingrid source data"
              + (f"; {nan_after} gap(s) still unfilled (filled with 0)" if nan_after else "."))
        if nan_after:
            df_hourly["value"] = df_hourly["value"].fillna(0)

    neg_count = int((df_hourly["value"] < 0).sum())
    if neg_count:
        print(f"  → Clamped {neg_count} negative value(s) to 0 (measurement noise near zero).")
        df_hourly["value"] = df_hourly["value"].clip(lower=0)

    df_hourly["source"] = "fingrid"
    df_hourly = df_hourly[["dataset_id", "country", "recorded_at", "value", "metric", "source"]]
    return df_hourly


def main():
    parser = argparse.ArgumentParser(description="Fetch Fingrid hourly data or generate mock fallback.")
    parser.add_argument("--allow-mock", action="store_true", help="Allow generating synthetic mock data if API key is missing or fails")
    parser.add_argument("--start", default="2023-01-01", help="Window start date (inclusive), default 2023-01-01")
    parser.add_argument("--end", default="2024-01-01", help="Window end date (exclusive), default 2024-01-01")
    parser.add_argument("--output", default=OUTPUT_PATH, help="CSV output path (default data/raw/grid_data.csv)")
    args = parser.parse_args()

    api_key = load_api_key()
    
    if not api_key or api_key == "YOUR_ACTUAL_API_KEY":
        if not args.allow_mock:
            print("✗ ERROR: No valid 'fingrid_api_key' configured in config.yaml. Real Fingrid API data cannot be fetched.")
            print("If you wish to generate synthetic mock data for offline testing or CI, you must pass the explicit --allow-mock flag.")
            sys.exit(1)
        else:
            df_grid = get_mock_grid_data()
    else:
        try:
            df_grid = fetch_fingrid_data(api_key, args.start, args.end)
            print("✓ Successfully fetched actual data from Fingrid API (source='fingrid').")
        except Exception as exc:
            print(f"✗ ERROR: Fingrid API request failed: {exc}")
            if not args.allow_mock:
                print("Failing loudly because --allow-mock flag was not passed.")
                sys.exit(1)
            else:
                print("Falling back to generating synthetic mock grid data (source='mock') due to --allow-mock flag...")
                df_grid = get_mock_grid_data()
            
    os.makedirs(os.path.dirname(os.path.abspath(args.output)), exist_ok=True)
    df_grid.to_csv(args.output, index=False)
    print(f"✓ Wrote {len(df_grid):,} grid data rows to: {os.path.abspath(args.output)}")


if __name__ == "__main__":
    main()
