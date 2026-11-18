"""
ember.py
~~~~~~~~
Ember's monthly electricity data for Europe into ember_area, ember_generation
and ember_price (sql/schema/20_ember.sql): the input of "Finland in Europe"
(sql/analysis/30).

Two public CSV files (https://ember-energy.org/data/, CC BY 4.0, no key):
  - monthly generation and emissions by source, every country in the world
    (about 30 MB, 4.5 MB compressed): only the countries in the price file and
    the EU aggregate are kept
  - monthly wholesale day-ahead prices for 34 European countries, from ENTSO-E
    as cleaned by Ember

Ember keeps the whole history, so every run replaces the three tables in one
transaction; if a download fails, the tables keep what they had (on the daily
runner: nothing, and the export keeps the published file).

Usage:
    python src/ember.py fetch
"""

from __future__ import annotations

import csv
import gzip
import io
import os
import sys
import time
import urllib.error
import urllib.request

BASE = "https://files.ember-energy.org/public-downloads/"
GENERATION_URL = BASE + "generation/outputs/release_generation_monthly_global.csv"
PRICE_URL = BASE + "price/outputs/european_wholesale_electricity_price_data_monthly.csv"
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"
EU = "EU"


def _get(url: str, retries: int = 3) -> str:
    if not url.startswith(BASE):
        raise ValueError(f"unexpected URL {url}")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=180) as resp:  # nosec B310 (fixed https BASE above)
                raw = resp.read()
                if resp.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.decompress(raw)
                return raw.decode("utf-8-sig")
        except (urllib.error.URLError, TimeoutError) as e:
            transient = not isinstance(e, urllib.error.HTTPError) or e.code in (429, 500, 502, 503, 504)
            if not transient or attempt == retries:
                raise
            time.sleep(15 * 2 ** attempt)
    raise RuntimeError("unreachable")


def _num(s: str) -> float | None:
    return float(s) if s not in ("", None) else None


def parse_prices(text: str) -> list[tuple]:
    """(country, iso3, month, EUR/MWh)."""
    return [(r["Country"], r["ISO3 Code"] or None, r["Date"], float(r["Price (EUR/MWhe)"]))
            for r in csv.DictReader(io.StringIO(text)) if r["Price (EUR/MWhe)"] not in ("", None)]


def parse_generation(text: str, areas: set[str]) -> tuple[dict, list[tuple]]:
    """({area: (iso3, eu_member)}, [(area, month, source, TWh, MtCO2e)]) for *areas* and the EU aggregate."""
    meta, rows = {}, []
    for r in csv.DictReader(io.StringIO(text)):
        area = r["Area"]
        if area not in areas and area != EU:
            continue
        if area != EU and not r["Area type"].startswith("Country"):          # "Country or economy"
            continue
        meta.setdefault(area, (r["ISO 3 code"] or None, r["EU member"] == "True"))
        rows.append((area, r["Date"], r["Electricity source"], _num(r["Generation (TWh)"]),
                     _num(r["Emissions (MtCO2e)"])))
    return meta, rows


def load(conn, getter=_get, commit: bool = True) -> dict:
    """Download both files and replace the tables (one transaction); returns row counts."""
    prices = parse_prices(getter(PRICE_URL))
    countries = {p[0] for p in prices}
    meta, gen = parse_generation(getter(GENERATION_URL), countries)
    for country, iso3, *_ in prices:                     # a price country Ember has no generation rows for
        meta.setdefault(country, (iso3, False))
    with conn.cursor() as cur:
        cur.execute("TRUNCATE ember_price, ember_generation, ember_area")
        cur.executemany("INSERT INTO ember_area (area, iso3, eu_member) VALUES (%s, %s, %s)",
                        [(a, iso3, eu) for a, (iso3, eu) in sorted(meta.items())])
        cur.executemany("INSERT INTO ember_generation (area, month, source, generation_twh, emissions_mt) "
                        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING", gen)
        cur.executemany("INSERT INTO ember_price (area, month, eur_mwh) VALUES (%s, %s, %s) "
                        "ON CONFLICT DO NOTHING", [(c, m, p) for c, _, m, p in prices])
    if commit:
        conn.commit()
    return {"areas": len(meta), "generation_rows": len(gen), "price_rows": len(prices)}


def main() -> None:
    if sys.argv[1:] != ["fetch"]:
        sys.exit(__doc__)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from db_connection import get_connection

    conn = get_connection()
    try:
        n = load(conn)
        with conn.cursor() as cur:
            cur.execute("SELECT (SELECT max(month) FROM ember_generation WHERE area = 'Finland'), "
                        "(SELECT max(month) FROM ember_price WHERE area = 'Finland')")
            gen_last, price_last = cur.fetchone()
        conn.rollback()
        print(f"✓ Ember: {n['areas']} areas, {n['generation_rows']:,} generation rows (Finland to {gen_last}), "
              f"{n['price_rows']:,} prices (Finland to {price_last})")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
