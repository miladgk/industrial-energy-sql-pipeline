"""
openmeteo_forecast.py
~~~~~~~~~~~~~~~~~~~~~
Weather forecasts as they stood two days before, for every hour since the
warehouse began, from Open-Meteo's Previous Runs API
(https://open-meteo.com/en/docs/previous-runs-api, CC BY 4.0, no key).

The FMI archive (src/fmi_forecast.py) only grows from the day it started.
Open-Meteo keeps, for each hour, the value its models forecast 48 hours
earlier (the *_previous_day2 variables), which is exactly what a forecaster
could have known when Fingrid issued its day-ahead forecast at 12:00 Finnish
time the day before: the 48-hour-old run was already out for every hour of
that day. So src/weather_model.py can be trained and tested on a year of
honest weather forecasts today.

Only hours whose 48-hour-old run has certainly been published are stored
(valid_time <= now + 42 h: 48 h back, plus 6 h for the run to be computed).
For later hours the API returns values from newer runs instead, which would
leak information a forecaster did not have.

Rows go into weather_forecast (sql/schema/16_weather_forecast.sql) with
model 'openmeteo_d2' and issued_at = valid_time - 48 h, so the daily dump and
restore of that table keep them too.

Usage:
    python src/openmeteo_forecast.py fetch      # backfill, then the newest hours
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone

API_URL = "https://previous-runs-api.open-meteo.com/v1/forecast"
MODEL = "openmeteo_d2"
LEAD = timedelta(hours=48)
SAFETY = timedelta(hours=6)          # time for a run to be computed and served
BACKFILL_FROM = date(2025, 9, 1)     # a little before the warehouse's first day
# The FMI archive's places (temperature cities, then wind-farm coast towns), plus
# points inside the largest wind-farm areas: with them the wind model's error
# fell from 580 to 534 MW in the backtest.
PLACES = {
    "Helsinki": (60.17, 24.94), "Jyväskylä": (62.24, 25.75), "Oulu": (65.01, 25.47), "Rovaniemi": (66.50, 25.73),
    "Vaasa": (63.10, 21.62), "Kokkola": (63.84, 23.13), "Pori": (61.48, 21.80), "Raahe": (64.68, 24.48),
    "Kristinestad": (62.27, 21.38), "Kalajoki": (64.26, 23.95), "Lestijärvi": (63.52, 24.67), "Ii": (65.32, 25.37),
    "Tornio": (65.85, 24.15), "Kyyjärvi": (63.04, 24.56), "Pyhäjoki": (64.46, 24.26),
}
VARIABLES = {"temperature_2m_previous_day2": "temperature", "wind_speed_100m_previous_day2": "windspeed100"}
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"


def last_valid(now: datetime) -> datetime:
    """The latest hour whose two-day-old forecast has certainly been published."""
    return (now + LEAD - SAFETY).replace(minute=0, second=0, microsecond=0)


def fetch_place(lat: float, lon: float, start: date, end: date) -> dict:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": ",".join(VARIABLES), "wind_speed_unit": "ms",
        "timezone": "UTC", "start_date": start.isoformat(), "end_date": end.isoformat(),
    })
    req = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
    # The URL is the fixed https API_URL above, so B310 (file:// and custom schemes) cannot apply.
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
        return json.load(resp)


def rows_from(payload: dict, place: str, until: datetime) -> list[tuple]:
    """weather_forecast rows from one API answer, dropping missing values and hours after *until*."""
    hourly = payload["hourly"]
    out = []
    for i, t in enumerate(hourly["time"]):
        valid = datetime.fromisoformat(t).replace(tzinfo=timezone.utc)
        if valid > until:
            continue
        for var, parameter in VARIABLES.items():
            v = hourly[var][i]
            if v is not None:
                out.append((MODEL, place, parameter, valid - LEAD, valid, float(v)))
    return out


def fetch(conn, now: datetime | None = None, getter=fetch_place, pause: float = 1.0) -> int:
    """Store, per place, every hour from its last stored one (or BACKFILL_FROM) up to last_valid(now)."""
    now = now or datetime.now(timezone.utc)
    until = last_valid(now)
    rows = 0
    with conn.cursor() as cur:
        cur.execute("SELECT place, max(valid_time) FROM weather_forecast WHERE model = %s GROUP BY place", (MODEL,))
        last = dict(cur.fetchall())
        for place, (lat, lon) in PLACES.items():
            start = (last[place] - timedelta(days=1)).date() if place in last else BACKFILL_FROM   # new place: backfill
            values = rows_from(getter(lat, lon, start, until.date()), place, until)
            cur.executemany(
                "INSERT INTO weather_forecast (model, place, parameter, issued_at, valid_time, value) "
                "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", values)
            rows += len(values)
            time.sleep(pause)
    conn.commit()
    return rows


def main() -> None:
    if sys.argv[1:] != ["fetch"]:
        sys.exit(__doc__)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from db_connection import get_connection

    conn = get_connection()
    try:
        print(f"✓ stored up to {fetch(conn):,} Open-Meteo forecast values (two days ahead)")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
