"""
fmi_forecast.py
~~~~~~~~~~~~~~~
Archive FMI weather forecasts for the places that drive Finnish demand
(temperature in four cities) and wind output (wind speed on the west coast).

FMI's open data (https://opendata.fmi.fi, CC BY 4.0, no key) serves only the
current forecasts. Models of tomorrow's power system must be tested with the
forecast that was available at the time, never with the weather that later
happened, so the daily GitHub Action calls this script and the archive in
weather_forecast (sql/schema/16_weather_forecast.sql) grows by one issue a day.
It is kept between runs as a release asset next to the warehouse snapshot.

Usage:
    python src/fmi_forecast.py fetch                   # store the current forecasts
    python src/fmi_forecast.py dump    weather_forecast.csv.gz
    python src/fmi_forecast.py restore weather_forecast.csv.gz
"""

from __future__ import annotations

import argparse
import gzip
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from defusedxml import ElementTree

WFS_URL = "https://opendata.fmi.fi/wfs"
MODELS = {
    "edited": "fmi::forecast::edited::weather::scandinavia::point::simple",   # FMI's own edited forecast
    "harmonie": "fmi::forecast::harmonie::surface::point::simple",           # the raw weather model
}
# Temperature cities match Fingrid's temperature datasets (178, 182, 196, 185);
# the wind places sit where most Finnish wind farms are (Ostrobothnia, Satakunta, Raahe).
PLACES = ["Helsinki", "Jyväskylä", "Oulu", "Rovaniemi", "Vaasa", "Kokkola", "Pori", "Raahe"]
PARAMETERS = ["temperature", "windspeedms"]
HORIZON = timedelta(days=3)
NS = {"wfs": "http://www.opengis.net/wfs/2.0", "BsWfs": "http://xml.fmi.fi/schema/wfs/2.0"}
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"


def parse(xml: bytes) -> list[tuple[str, datetime, float | None]]:
    """(parameter, valid_time, value) from an FMI 'simple' feature collection; NaN becomes None."""
    out = []
    for el in ElementTree.fromstring(xml).iter(f"{{{NS['BsWfs']}}}BsWfsElement"):
        t = el.findtext("BsWfs:Time", namespaces=NS)
        p = el.findtext("BsWfs:ParameterName", namespaces=NS)
        v = el.findtext("BsWfs:ParameterValue", namespaces=NS)
        value = None if v is None or v.strip().lower() == "nan" else float(v)
        out.append((p, datetime.fromisoformat(t.replace("Z", "+00:00")), value))
    return out


def fetch_place(model: str, place: str, now: datetime) -> bytes:
    query = urllib.parse.urlencode({
        "service": "WFS", "version": "2.0.0", "request": "getFeature", "storedquery_id": MODELS[model],
        "place": place, "parameters": ",".join(PARAMETERS), "timestep": 60,
        "starttime": now.strftime("%Y-%m-%dT%H:00:00Z"), "endtime": (now + HORIZON).strftime("%Y-%m-%dT%H:00:00Z"),
    })
    req = urllib.request.Request(f"{WFS_URL}?{query}", headers={"User-Agent": USER_AGENT})
    # The URL is the fixed https WFS_URL above, so B310 (file:// and custom schemes) cannot apply.
    with urllib.request.urlopen(req, timeout=60) as resp:  # nosec B310
        return resp.read()


def fetch(conn, now: datetime | None = None, getter=fetch_place, pause: float = 1.0) -> int:
    """Store the current forecast of every model and place; returns rows written."""
    now = (now or datetime.now(timezone.utc)).replace(second=0, microsecond=0)
    rows = 0
    with conn.cursor() as cur:
        for model in MODELS:
            for place in PLACES:
                values = parse(getter(model, place, now))
                cur.executemany(
                    "INSERT INTO weather_forecast (model, place, parameter, issued_at, valid_time, value) "
                    "VALUES (%s, %s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
                    [(model, place, p, now, t, v) for p, t, v in values])
                rows += len(values)
                time.sleep(pause)
    conn.commit()
    return rows


def dump(conn, path: str) -> int:
    with conn.cursor() as cur, gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        cur.execute("SET TIME ZONE 'UTC'")
        cur.copy_expert("COPY (SELECT model, place, parameter, issued_at, valid_time, value FROM weather_forecast "
                        "ORDER BY issued_at, model, place, parameter, valid_time) TO STDOUT WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("SELECT count(*) FROM weather_forecast")
        n = cur.fetchone()[0]
    conn.rollback()
    return n


def restore(conn, path: str) -> int:
    with conn.cursor() as cur, gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        cur.execute("CREATE TEMP TABLE forecast_rows (LIKE weather_forecast) ON COMMIT DROP")
        cur.copy_expert("COPY forecast_rows FROM STDIN WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("INSERT INTO weather_forecast SELECT * FROM forecast_rows ON CONFLICT DO NOTHING")
        added = cur.rowcount
    conn.commit()
    return added


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("action", choices=["fetch", "dump", "restore"])
    parser.add_argument("path", nargs="?")
    args = parser.parse_args()
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from db_connection import get_connection

    conn = get_connection()
    try:
        if args.action == "fetch":
            print(f"✓ stored {fetch(conn):,} FMI forecast values")
        elif not args.path:
            sys.exit("dump and restore need a file path")
        elif args.action == "dump":
            print(f"✓ wrote {dump(conn, args.path):,} forecast rows to {args.path}")
        else:
            print(f"✓ restored {restore(conn, args.path):,} forecast rows from {args.path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
