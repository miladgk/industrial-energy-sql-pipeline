"""
generate_data.py
~~~~~~~~~~~~~~~~
Generates synthetic operational data for a fictional network of energy
facilities and saves three CSV files to data/raw/.

Data volume (Upgrade 2 — realistic scale):
  • facilities : 20 rows
  • sensors    : 60 rows  (3 per facility)
  • readings   : ~6.3 million rows
      60 sensors × 365 days × 288 readings/day (every 5 min) ≈ 6,307,200 rows

Running at this scale means chunked ingestion and database indexes
actually matter — you can demonstrate and discuss the performance impact.

Reproducibility: numpy seed(42) throughout.
"""

import os
import sys
import numpy as np
import pandas as pd

SEED = 42
rng  = np.random.default_rng(SEED)

RAW_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
os.makedirs(RAW_DIR, exist_ok=True)


# ──────────────────────────────────────────────────────────────
# 1. Facilities
# ──────────────────────────────────────────────────────────────

FACILITY_TYPES  = ["wind", "solar", "substation"]
COUNTRIES       = ["Finland", "Sweden", "Norway", "Denmark"]

def generate_facilities(n: int = 20) -> pd.DataFrame:
    """Return a DataFrame of n fictional energy facilities."""
    types = rng.choice(FACILITY_TYPES, size=n)
    names = [
        f"{'WindFarm' if t == 'wind' else 'SolarPlant' if t == 'solar' else 'Substation'}"
        f"_{rng.choice(['North','South','East','West','Central'])}_{i+1:02d}"
        for i, t in enumerate(types)
    ]
    return pd.DataFrame({
        "facility_id"       : range(1, n + 1),
        "facility_name"     : names,
        "facility_type"     : types,
        "country"           : rng.choice(COUNTRIES, size=n),
        "capacity_mw"       : rng.uniform(10.0, 500.0, size=n).round(2),
        "commissioned_year" : rng.integers(2005, 2021, size=n),
    })


# ──────────────────────────────────────────────────────────────
# 2. Sensors  (3 per facility, fixed sensor_type order)
# ──────────────────────────────────────────────────────────────

SENSOR_META = [
    ("power_output", "MW"),
    ("temperature",  "Celsius"),
    ("wind_speed",   "m/s"),
]

def generate_sensors(facilities: pd.DataFrame) -> pd.DataFrame:
    """Return 3 sensors per facility."""
    rows = []
    sensor_id = 1
    for _, fac in facilities.iterrows():
        for sensor_type, unit in SENSOR_META:
            rows.append({
                "sensor_id"  : sensor_id,
                "facility_id": int(fac["facility_id"]),
                "sensor_type": sensor_type,
                "unit"       : unit,
            })
            sensor_id += 1
    return pd.DataFrame(rows)


# ──────────────────────────────────────────────────────────────
# 3. Readings  (every 5 minutes, full year 2023)
# ──────────────────────────────────────────────────────────────

ANOMALY_RATE    = 0.02   # 2 % of readings are anomalous
INTERVAL_MINS   = 5      # reading frequency

def _value_range(sensor_type: str, capacity_mw: float):
    """Return (low, high) for normal value generation."""
    if sensor_type == "power_output":
        return 0.0, float(capacity_mw)
    if sensor_type == "temperature":
        return -20.0, 35.0
    # wind_speed
    return 0.0, 25.0

def generate_readings(
    sensors: pd.DataFrame,
    facilities: pd.DataFrame,
    interval_minutes: int = INTERVAL_MINS,
    rows_limit: int = None,
    target_date: str = None,
    days: int = None,
) -> pd.DataFrame:
    """
    Generate time-series readings at *interval_minutes* resolution.

    Priority of mode selection (first match wins):
      1. ``target_date`` — single day, used for incremental loads.
      2. ``days``        — explicit window starting 2023-01-01 (e.g. 30 days).
      3. ``rows_limit``  — back-calculates the number of timestamps per sensor.
      4. default         — full calendar year 2023.

    Returns a DataFrame with columns:
        reading_id, sensor_id, recorded_at, value, is_anomaly
    """
    if target_date is not None:
        start_ts = f"{target_date} 00:00"
        end_ts   = f"{target_date} 23:55"
        timestamps = pd.date_range(start=start_ts, end=end_ts, freq=f"{interval_minutes}min")
        n_timestamps = len(timestamps)
    elif days is not None:
        # Build a clean date-range window: 2023-01-01 00:00 … 2023-01-<days> 23:55
        from datetime import timedelta, date
        end_date = date(2023, 1, 1) + timedelta(days=days - 1)
        timestamps = pd.date_range(
            start="2023-01-01 00:00",
            end=f"{end_date} 23:55",
            freq=f"{interval_minutes}min",
        )
        n_timestamps = len(timestamps)
    elif rows_limit is not None:
        n_timestamps = max(1, rows_limit // len(sensors))
        timestamps = pd.date_range(
            start="2023-01-01 00:00",
            periods=n_timestamps,
            freq=f"{interval_minutes}min",
        )
    else:
        timestamps = pd.date_range(
            start="2023-01-01 00:00",
            end  ="2023-12-31 23:55",
            freq =f"{interval_minutes}min",
        )
        n_timestamps = len(timestamps)

    # Pre-build the facility lookup: facility_id → capacity_mw
    cap_map = facilities.set_index("facility_id")["capacity_mw"].to_dict()

    all_chunks = []
    reading_id = 1

    for _, sensor in sensors.iterrows():
        sid          = int(sensor["sensor_id"])
        sensor_type  = sensor["sensor_type"]
        capacity_mw  = cap_map[sensor["facility_id"]]

        low, high = _value_range(sensor_type, capacity_mw)

        # Normal values
        values = rng.uniform(low, high, size=n_timestamps).round(4)

        # Inject anomalies: ~2 % of readings
        anomaly_mask = rng.random(size=n_timestamps) < ANOMALY_RATE
        n_anom       = anomaly_mask.sum()

        if n_anom > 0:
            # Randomly choose between 0 (under-read) and 3× max (over-read)
            extremes = rng.choice([0.0, high * 3.0], size=n_anom).round(4)
            values[anomaly_mask] = extremes

        chunk = pd.DataFrame({
            "reading_id" : range(reading_id, reading_id + n_timestamps),
            "sensor_id"  : sid,
            "recorded_at": timestamps,
            "value"      : values,
            "is_anomaly" : anomaly_mask,
        })
        all_chunks.append(chunk)
        reading_id += n_timestamps

    df = pd.concat(all_chunks, ignore_index=True)
    # reading_id needs to be globally unique and sequential
    df["reading_id"] = range(1, len(df) + 1)
    return df


# ──────────────────────────────────────────────────────────────
# Entry point
# ──────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Generate synthetic operational data.")
    parser.add_argument("--rows", type=int, default=None, help="Limit total row count (e.g. 50000 for CI)")
    parser.add_argument("--days", type=int, default=365, help="Number of days of data to generate (if rows not set)")
    parser.add_argument("--interval", type=int, default=INTERVAL_MINS, help="Interval in minutes (default: 5)")
    parser.add_argument("--incremental", action="store_true", help="Generate incremental batch for a specific date")
    parser.add_argument("--date", type=str, default="2024-01-01", help="Target date for incremental mode (YYYY-MM-DD)")
    args = parser.parse_args()

    fac_path = os.path.join(RAW_DIR, "facilities.csv")
    sen_path = os.path.join(RAW_DIR, "sensors.csv")

    if args.incremental:
        if not os.path.exists(fac_path) or not os.path.exists(sen_path):
            print("Error: Incremental mode requires existing facilities.csv and sensors.csv.")
            sys.exit(1)
        print("Loading existing facilities and sensors for incremental mode...")
        facilities = pd.read_csv(fac_path)
        sensors = pd.read_csv(sen_path)
        
        print(f"Generating incremental readings for {args.date} ...")
        readings = generate_readings(sensors, facilities, interval_minutes=args.interval, target_date=args.date)
        red_path = os.path.join(RAW_DIR, "readings_incremental.csv")
        readings.to_csv(red_path, index=False)
        print(f"  ✓ {len(readings):,} rows → {red_path}")
        
    else:
        print("Generating facilities …")
        facilities = generate_facilities(20)
        facilities.to_csv(fac_path, index=False)
        print(f"  ✓ {len(facilities):,} rows → {fac_path}")

        print("Generating sensors …")
        sensors = generate_sensors(facilities)
        sensors.to_csv(sen_path, index=False)
        print(f"  ✓ {len(sensors):,} rows → {sen_path}")

        print("Generating readings (this may take a few seconds) …")
        rows_limit = args.rows
        # ``--days`` builds a clean calendar window; ``--rows`` overrides it.
        days_window = None if args.rows is not None else (
            args.days if args.days != 365 else None
        )

        readings = generate_readings(
            sensors,
            facilities,
            interval_minutes=args.interval,
            rows_limit=rows_limit,
            days=days_window,
        )
        red_path = os.path.join(RAW_DIR, "readings.csv")
        readings.to_csv(red_path, index=False)
        print(f"  ✓ {len(readings):,} rows → {red_path}")

    actual_anomaly_pct = readings["is_anomaly"].mean() * 100
    print(f"\nSummary")
    print(f"  Facilities : {len(facilities):>10,}")
    print(f"  Sensors    : {len(sensors):>10,}")
    print(f"  Readings   : {len(readings):>10,}")
    print(f"  Anomaly %  : {actual_anomaly_pct:.2f}%  (target ~2.00%)")

if __name__ == "__main__":
    main()

