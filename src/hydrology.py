"""
hydrology.py
~~~~~~~~~~~~
The state of the water behind hydropower, daily, into hydrology_daily
(sql/schema/17_hydrology.sql).

Finland (SYKE Hydrology API, https://rajapinnat.ymparisto.fi, CC BY 4.0, no key):
  - water levels of the large regulated reservoirs and lakes (storage)
  - discharge of the unregulated Tornionjoki (natural inflow in the north)
  - snow water equivalent over the main hydropower basins (water still to come)
Norway (NVE reservoir statistics, https://biapi.nve.no/magasinstatistikk, NLOD, no key):
  - weekly filling of the hydro reservoirs in each price area NO1-NO5

Discharge below the regulated plants is deliberately left out: it is the water the
plants chose to release, an outcome of the decisions the analysis studies.

The first run fetches every series from HISTORY_FROM (decades, for the seasonal
norms); later runs re-fetch the last REVISION_DAYS, because SYKE revises recent
values. The table is dumped and restored with the daily snapshot like the forecast
archives, so a normal day costs about a dozen requests.

Usage:
    python src/hydrology.py fetch
    python src/hydrology.py dump    hydrology.csv.gz
    python src/hydrology.py restore hydrology.csv.gz
"""

from __future__ import annotations

import argparse
import gzip
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import date, timedelta

SYKE_URL = "https://rajapinnat.ymparisto.fi/api/Hydrologiarajapinta/1.1/odata"
NVE_URL = "https://biapi.nve.no/magasinstatistikk/api/Magasinstatistikk/HentOffentligData"
HISTORY_FROM = date(2000, 1, 1)
REVISION_DAYS = 14
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"

# series -> (SYKE collection, station id, unit, what it is)
SERIES = {
    "level_lokka":       ("Vedenkorkeus", 2468, "cm", "Lokka reservoir, Kemijoki (largest reservoir in Finland)"),
    "level_porttipahta": ("Vedenkorkeus", 2458, "cm", "Porttipahta reservoir, Kemijoki"),
    "level_oulujarvi":   ("Vedenkorkeus", 2409, "cm", "Oulujärvi at Vaala, Oulujoki"),
    "level_saimaa":      ("Vedenkorkeus", 1900, "cm", "Saimaa at Lauritsala, Vuoksi"),
    "level_nasijarvi":   ("Vedenkorkeus", 2230, "cm", "Näsijärvi at Tampere, Kokemäenjoki"),
    "flow_tornionjoki":  ("Virtaama", 1406, "m3/s", "Tornionjoki at Karunki, unregulated"),
    "snow_kemijoki":     ("LumiAlue", 211, "mm", "snow water equivalent, Kemijoki basin"),
    "snow_oulujoki":     ("LumiAlue", 169, "mm", "snow water equivalent, Oulujoki basin"),
    "snow_iijoki":       ("LumiAlue", 188, "mm", "snow water equivalent, Iijoki basin"),
}
NVE_AREAS = (1, 2, 3, 4, 5)


def _get(url: str) -> dict | list:
    if not (url.startswith(SYKE_URL) or url.startswith(NVE_URL)):     # nextLinks must stay on the API
        raise ValueError(f"unexpected URL {url}")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
    # Only the two fixed https APIs above are ever opened, so B310 (file:// and custom schemes) cannot apply.
    with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310
        return json.load(resp)


def syke_rows(series: str, start: date, getter=_get, pause: float = 1.0) -> list[tuple]:
    """(series, day, value) for one SYKE series from *start*, following the 500-row pages."""
    collection, station, _, _ = SERIES[series]
    query = urllib.parse.urlencode({
        "$filter": f"Paikka_Id eq {station} and Aika ge datetime'{start.isoformat()}T00:00:00'",
        "$orderby": "Aika",
    })
    url, out = f"{SYKE_URL}/{collection}?{query}", []
    while url:
        page = getter(url)
        out += [(series, date.fromisoformat(r["Aika"][:10]), float(r["Arvo"]))
                for r in page["value"] if r.get("Arvo") not in (None, "")]
        url = page.get("odata.nextLink")
        if url:
            time.sleep(pause)
    return out


def nve_rows(getter=_get) -> list[tuple]:
    """(series, day, filling share) for every week and Norwegian price area."""
    return [(f"nve_no{r['omrnr']}", date.fromisoformat(r["dato_Id"][:10]), float(r["fyllingsgrad"]))
            for r in getter(NVE_URL)
            if r["omrType"] == "EL" and r["omrnr"] in NVE_AREAS and r.get("fyllingsgrad") is not None]


_UPSERT = ("INSERT INTO hydrology_daily (series, day, value) VALUES (%s, %s, %s) "
           "ON CONFLICT (series, day) DO UPDATE SET value = EXCLUDED.value "
           "WHERE hydrology_daily.value IS DISTINCT FROM EXCLUDED.value")


def fetch(conn, getter=_get, pause: float = 1.0) -> dict:
    """Bring every series up to date; returns rows offered per series."""
    counts = {}
    with conn.cursor() as cur:
        cur.execute("SELECT series, max(day) FROM hydrology_daily GROUP BY series")
        last = dict(cur.fetchall())
        for series in SERIES:
            start = last[series] - timedelta(days=REVISION_DAYS) if series in last else HISTORY_FROM
            rows = syke_rows(series, start, getter, pause)
            cur.executemany(_UPSERT, rows)
            conn.commit()
            counts[series] = len(rows)
            time.sleep(pause)
        rows = nve_rows(getter)                       # one answer holds the whole history
        cur.executemany(_UPSERT, rows)
        counts["nve"] = len(rows)
    conn.commit()
    return counts


def dump(conn, path: str) -> int:
    with conn.cursor() as cur, gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
        cur.copy_expert("COPY (SELECT series, day, value FROM hydrology_daily ORDER BY series, day) "
                        "TO STDOUT WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("SELECT count(*) FROM hydrology_daily")
        n = cur.fetchone()[0]
    conn.rollback()
    return n


def restore(conn, path: str) -> int:
    with conn.cursor() as cur, gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        cur.execute("CREATE TEMP TABLE hydrology_rows (LIKE hydrology_daily) ON COMMIT DROP")
        cur.copy_expert("COPY hydrology_rows FROM STDIN WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("INSERT INTO hydrology_daily SELECT * FROM hydrology_rows ON CONFLICT DO NOTHING")
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
            counts = fetch(conn)
            print("✓ hydrology: " + ", ".join(f"{k} {v:,}" for k, v in counts.items()))
        elif not args.path:
            sys.exit("dump and restore need a file path")
        elif args.action == "dump":
            print(f"✓ wrote {dump(conn, args.path):,} hydrology rows to {args.path}")
        else:
            print(f"✓ restored {restore(conn, args.path):,} hydrology rows from {args.path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
