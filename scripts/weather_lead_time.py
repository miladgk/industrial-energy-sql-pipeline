"""
weather_lead_time.py
~~~~~~~~~~~~~~~~~~~~
Why does the public-weather model lose to Fingrid? A diagnostic, run by hand
(it calls Open-Meteo about 45 times), that writes
docs/data/weather_lead_time.json.

The published model must use weather forecast 48 hours earlier, the newest
that was out when Fingrid issued its forecast. This replays the same
backtest (src/weather_model.py, model 'weather') with weather forecast 24
hours earlier and with the newest forecast Open-Meteo has, which a real
forecaster could not have had. If the error falls steeply as the weather
gets fresher, the gap to Fingrid is mostly the age of the weather, not the
model.

Usage:
    python scripts/weather_lead_time.py
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import pandas as pd  # noqa: E402

import openmeteo_forecast as om  # noqa: E402
import weather_model as wm  # noqa: E402

PANEL_SQL = "sql/analysis/26_weather_model_panel.sql"
LEADS = {"48 h (published)": "_previous_day2", "24 h": "_previous_day1", "newest": ""}
SLUG = lambda place: (place.lower().replace("ä", "a").replace("ö", "o"))   # Lestijärvi -> lestijarvi
TOWN_TEMPS = {"Helsinki": "temp_helsinki", "Oulu": "temp_oulu", "Vaasa": "temp_vaasa"}
CITY_MEAN = ("Helsinki", "Jyväskylä", "Oulu", "Rovaniemi")


def fetch(lat: float, lon: float, suffix: str, start: str, end: str) -> dict:
    query = urllib.parse.urlencode({
        "latitude": lat, "longitude": lon, "hourly": f"temperature_2m{suffix},wind_speed_100m{suffix}",
        "wind_speed_unit": "ms", "timezone": "UTC", "start_date": start, "end_date": end,
    })
    req = urllib.request.Request(f"{om.API_URL}?{query}", headers={"User-Agent": om.USER_AGENT})
    # The URL is the fixed https om.API_URL, so B310 (file:// and custom schemes) cannot apply.
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
        return json.load(resp)


def with_weather(rows: list[dict], suffix: str, start: str, end: str) -> list[dict]:
    """The panel rows with every weather column replaced by the forecast of the given age."""
    series = {}
    for place, (lat, lon) in om.PLACES.items():
        d = fetch(lat, lon, suffix, start, end)
        idx = pd.to_datetime(d["hourly"]["time"]).tz_localize("UTC")
        series[place] = {v: pd.Series(d["hourly"][f"{v}{suffix}"], index=idx, dtype=float)
                         for v in ("temperature_2m", "wind_speed_100m")}
        time.sleep(1)
    out = []
    for r in rows:
        t = pd.Timestamp(r["hour_start"]).tz_convert("UTC")
        r = dict(r)
        get = lambda place, v: series[place][v].get(t, float("nan"))        # hours past the fetched range: NaN
        r["temp_c"] = sum(get(p, "temperature_2m") for p in CITY_MEAN) / len(CITY_MEAN)
        for place, col in TOWN_TEMPS.items():
            r[col] = get(place, "temperature_2m")
        for place in om.PLACES:
            col = f"farm_{SLUG(place)}" if f"farm_{SLUG(place)}" in r else f"wind_{SLUG(place)}"
            if col in r:
                r[col] = get(place, "wind_speed_100m")
        out.append(r)
    return out


def main() -> None:
    from db_connection import get_connection
    import psycopg2.extras

    # The same window as export_weather_model in scripts/export_dashboard_data.py, so the 48 h row
    # reproduces the published backtest exactly.
    end = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=3)
    w = {"start": end - timedelta(days=430), "end": end}
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur, \
                open(os.path.join(ROOT, PANEL_SQL), encoding="utf-8") as fh:
            cur.execute(fh.read(), w)
            rows = [dict(r) for r in cur.fetchall()]
    finally:
        conn.close()
    start = w["start"].strftime("%Y-%m-%d")
    end = min(w["end"] - timedelta(days=1), datetime.now(timezone.utc) + timedelta(days=1)).strftime("%Y-%m-%d")
    result = {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
              "what": "MAE of the public-weather model (no Fingrid input) in the same rolling backtest, "
                      "with weather forecasts of different ages. Only the 48 h one was available when "
                      "Fingrid issued its forecast; the others are for comparison, not forecasts anyone could make.",
              "source": "Open-Meteo Previous Runs API (CC BY 4.0); Fingrid Open Data (CC BY 4.0)",
              "code": "scripts/weather_lead_time.py", "variables": {}}
    for label, suffix in LEADS.items():
        df = wm.panel(with_weather(rows, suffix, start, end))
        for variable in ("wind", "consumption"):
            b = wm.backtest(df, variable)
            v = result["variables"].setdefault(variable, {"fingrid_mae_mw": round(b["mae_mw"]["fingrid"], 1),
                                                          "days": b["days"], "first_day": b["first_day"],
                                                          "last_day": b["last_day"], "leads": []})
            v["leads"].append({"lead": label, "mae_mw": round(b["mae_mw"]["weather"], 1)})
            print(f"{variable:12s} {label:18s} weather model {b['mae_mw']['weather']:.0f} MW  (Fingrid {b['mae_mw']['fingrid']:.0f} MW)")
    path = os.path.join(ROOT, "docs", "data", "weather_lead_time.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(result, fh, ensure_ascii=False, separators=(",", ":"))
    print(f"✓ wrote {path}")


if __name__ == "__main__":
    main()
