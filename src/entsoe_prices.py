"""
entsoe_prices.py
~~~~~~~~~~~~~~~~
Day-ahead electricity prices from the ENTSO-E Transparency Platform
(https://transparency.entsoe.eu, document type A44) into entsoe_price
(sql/schema/19_entsoe_price.sql): Finland and the four bidding zones it is
connected to (SE1, SE3, EE, NO4: the borders of Fingrid's flow datasets).

Prices are stored at the resolution the auction cleared them: hourly until
the single day-ahead coupling moved to 15-minute products on 1 October 2025,
15 minutes since. Where the platform returns both for the same time, the
finer one is kept.

ENTSO-E answers in XML. Each TimeSeries holds Periods (an interval and a
resolution) of numbered Points; with curve type A03 a Point is omitted when
the price equals the previous one, so missing positions repeat the last value.
One request covers at most WINDOW_DAYS (the platform allows a year).

The first run fetches from HISTORY_FROM (the start of the Fingrid warehouse);
later runs re-fetch from REFETCH_DAYS before the newest stored slot up to the
day after tomorrow, which picks up tomorrow's prices once the auction has
published them (about 13:00 Finnish time). The table is dumped and restored
with the daily snapshot like the other archives.

The token is read from ENTSOE_TOKEN only, sent to the one fixed https API,
and never printed: errors name the area and window, not the request URL.
Without a token, fetch says so and does nothing (forks, local runs).

Usage:
    python src/entsoe_prices.py fetch
    python src/entsoe_prices.py dump    entsoe_price.csv.gz
    python src/entsoe_prices.py restore entsoe_price.csv.gz
"""

from __future__ import annotations

import argparse
import gzip
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from defusedxml import ElementTree
from psycopg2.extras import execute_values

API_URL = "https://web-api.tp.entsoe.eu/api"
AREAS = {                                  # bidding zone -> EIC code
    "FI": "10YFI-1--------U",
    "SE1": "10Y1001A1001A44P",
    "SE3": "10Y1001A1001A46L",
    "EE": "10Y1001A1001A39I",
    "NO4": "10YNO-4--------9",
}
HISTORY_FROM = datetime(2023, 11, 1, tzinfo=timezone.utc)
WINDOW_DAYS = 120
REFETCH_DAYS = 3
PAUSE_S = 1.0                              # the platform allows 400 requests a minute; one a second is plenty
USER_AGENT = "industrial-energy-sql-pipeline (open-source research project)"
NO_DATA = "999"                            # Acknowledgement reason: no matching data


class EntsoeError(RuntimeError):
    pass


def _tag(el) -> str:
    return el.tag.rsplit("}", 1)[-1]


def _child(el, name):
    return next((c for c in el if _tag(c) == name), None)


def _text(el, *path) -> str | None:
    for name in path:
        el = _child(el, name) if el is not None else None
    return el.text if el is not None else None


def _minutes(resolution: str) -> int:
    m = re.fullmatch(r"PT(\d+)M", resolution) or re.fullmatch(r"PT(\d+)H", resolution)
    if not m:
        raise EntsoeError(f"unexpected resolution {resolution}")
    return int(m.group(1)) * (60 if resolution.endswith("H") else 1)


def _time(s: str) -> datetime:
    return datetime.strptime(s, "%Y-%m-%dT%H:%MZ").replace(tzinfo=timezone.utc)


def parse(xml: bytes | str) -> list[tuple[datetime, datetime, float]]:
    """(start, end, EUR/MWh) slots in an A44 answer; [] when ENTSO-E has no data for the window."""
    root = ElementTree.fromstring(xml)
    if _tag(root) == "Acknowledgement_MarketDocument":
        code, text = _text(root, "Reason", "code"), _text(root, "Reason", "text")
        if code == NO_DATA:
            return []
        raise EntsoeError(f"ENTSO-E refused the request: {code} {text}")
    slots: dict[datetime, tuple[datetime, float, int]] = {}
    series = [ts for ts in root if _tag(ts) == "TimeSeries"]
    series.sort(key=lambda ts: int(_text(ts, "classificationSequence_AttributeInstanceComponent.position") or 1))
    for ts in series:
        currency, unit = _text(ts, "currency_Unit.name"), _text(ts, "price_Measure_Unit.name")
        if (currency, unit) != ("EUR", "MWH"):
            raise EntsoeError(f"prices in {currency}/{unit}, expected EUR/MWH")
        for period in (p for p in ts if _tag(p) == "Period"):
            start = _time(_text(period, "timeInterval", "start"))
            end = _time(_text(period, "timeInterval", "end"))
            step = timedelta(minutes=_minutes(_text(period, "resolution")))
            prices = {int(_text(p, "position")): float(_text(p, "price.amount"))
                      for p in period if _tag(p) == "Point"}
            n = int((end - start) / step)
            last = None
            for pos in range(1, n + 1):
                last = prices.get(pos, last)          # A03: an omitted point repeats the previous price
                if last is None:
                    continue
                s = start + (pos - 1) * step
                minutes = int(step.total_seconds() // 60)
                if s not in slots or minutes < slots[s][2]:   # finer resolution wins; first sequence wins ties
                    slots[s] = (s + step, last, minutes)
    # A coarse slot that finer slots fall inside is the same price at a lower resolution: drop it.
    finest = timedelta(minutes=min((m for _, _, m in slots.values()), default=60))
    out = []
    for s, (e, price, m) in sorted(slots.items()):
        inner = (slots.get(s + k * finest) for k in range(1, int((e - s) / finest)))
        if any(x is not None and x[2] < m for x in inner):
            continue
        out.append((s, e, price))
    return out


def _get(area: str, start: datetime, end: datetime, token: str, retries: int = 4) -> bytes:
    code = AREAS[area]
    query = urllib.parse.urlencode({
        "securityToken": token, "documentType": "A44", "in_Domain": code, "out_Domain": code,
        "periodStart": start.strftime("%Y%m%d%H%M"), "periodEnd": end.strftime("%Y%m%d%H%M"),
    })
    req = urllib.request.Request(f"{API_URL}?{query}", headers={"User-Agent": USER_AGENT})
    for attempt in range(retries + 1):
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:  # nosec B310 (fixed https URL above)
                return resp.read()
        except urllib.error.HTTPError as e:
            body = e.read()
            if e.code == 400 and b"Acknowledgement_MarketDocument" in body:
                return body                                       # parse() tells "no data" from a real refusal
            if e.code == 401:
                raise EntsoeError("ENTSO-E rejected the token (401): check the ENTSOE_TOKEN secret") from None
            if e.code in (429, 500, 502, 503, 504) and attempt < retries:
                wait = int(e.headers.get("Retry-After") or 0) or 15 * 2 ** attempt
                time.sleep(min(wait, 120))
                continue
            raise EntsoeError(f"ENTSO-E answered HTTP {e.code} for {area} {start:%Y-%m-%d}..{end:%Y-%m-%d}") from None
        except urllib.error.URLError as e:
            if attempt < retries:
                time.sleep(15 * 2 ** attempt)
                continue
            raise EntsoeError(f"ENTSO-E unreachable for {area}: {e.reason}") from None
    raise EntsoeError("unreachable")


def windows(start: datetime, end: datetime, days: int = WINDOW_DAYS):
    while start < end:
        stop = min(start + timedelta(days=days), end)
        yield start, stop
        start = stop


_UPSERT = ("INSERT INTO entsoe_price (area, start_time, end_time, eur_mwh) VALUES %s "
           "ON CONFLICT (area, start_time) DO UPDATE SET end_time = EXCLUDED.end_time, eur_mwh = EXCLUDED.eur_mwh "
           "WHERE (entsoe_price.end_time, entsoe_price.eur_mwh) IS DISTINCT FROM (EXCLUDED.end_time, EXCLUDED.eur_mwh) "
           "RETURNING 1")


def fetch(conn, token: str, getter=_get, now: datetime | None = None, pause: float = PAUSE_S) -> dict:
    """Bring every area up to date; returns {area: (slots received, rows new or changed)}."""
    now = now or datetime.now(timezone.utc)
    until = (now + timedelta(days=2)).replace(hour=0, minute=0, second=0, microsecond=0)
    counts = {}
    with conn.cursor() as cur:
        cur.execute("SELECT area, max(start_time) FROM entsoe_price GROUP BY area")
        last = dict(cur.fetchall())
        for area in AREAS:
            start = (last[area] - timedelta(days=REFETCH_DAYS)).replace(hour=0, minute=0, second=0, microsecond=0) \
                if area in last else HISTORY_FROM
            got = changed = 0
            for a, b in windows(start, until):
                rows = parse(getter(area, a, b, token))
                if rows:
                    changed += len(execute_values(cur, _UPSERT, [(area, s, e, p) for s, e, p in rows],
                                                  page_size=5000, fetch=True))
                got += len(rows)
                conn.commit()
                time.sleep(pause)
            # A slot left over from a coarser answer that finer slots now cover (the same time, re-published).
            cur.execute("""
                DELETE FROM entsoe_price c WHERE c.area = %s AND c.start_time >= %s
                  AND EXISTS (SELECT 1 FROM entsoe_price f WHERE f.area = c.area
                              AND f.start_time > c.start_time AND f.start_time < c.end_time)""", (area, start))
            conn.commit()
            counts[area] = (got, changed)
    return counts


def summary(conn) -> list[tuple]:
    with conn.cursor() as cur:
        cur.execute("""
            SELECT area, count(*), min(start_time), max(end_time),
                   round(avg(eur_mwh) FILTER (WHERE start_time >= now() - interval '30 days')::numeric, 1)
            FROM entsoe_price GROUP BY area ORDER BY area""")
        rows = cur.fetchall()
    conn.rollback()
    return rows


def dump(conn, path: str) -> int:
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM entsoe_price")
        n = cur.fetchone()[0]
        if n:
            with gzip.open(path, "wt", encoding="utf-8", newline="") as fh:
                cur.copy_expert("COPY (SELECT area, start_time, end_time, eur_mwh FROM entsoe_price "
                                "ORDER BY area, start_time) TO STDOUT WITH (FORMAT csv, HEADER true)", fh)
    conn.rollback()
    return n


def restore(conn, path: str) -> int:
    with conn.cursor() as cur, gzip.open(path, "rt", encoding="utf-8", newline="") as fh:
        cur.execute("CREATE TEMP TABLE entsoe_rows (LIKE entsoe_price) ON COMMIT DROP")
        cur.copy_expert("COPY entsoe_rows FROM STDIN WITH (FORMAT csv, HEADER true)", fh)
        cur.execute("INSERT INTO entsoe_price SELECT * FROM entsoe_rows ON CONFLICT DO NOTHING")
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

    if args.action != "fetch" and not args.path:
        sys.exit("dump and restore need a file path")
    token = os.environ.get("ENTSOE_TOKEN", "").strip()
    if args.action == "fetch" and not token:
        print("ENTSOE_TOKEN is not set: skipping the ENTSO-E prices.")
        return
    conn = get_connection()
    try:
        if args.action == "fetch":
            for area, (got, changed) in fetch(conn, token).items():
                print(f"  ✓ {area:4s} {got:7,} slots received, {changed:7,} new or changed")
            for area, n, first, last, mean30 in summary(conn):
                print(f"    {area:4s} {n:8,} rows  {first:%Y-%m-%d %H:%M} .. {last:%Y-%m-%d %H:%M} UTC  "
                      f"last 30 days mean {mean30} EUR/MWh")
        elif args.action == "dump":
            n = dump(conn, args.path)
            print(f"✓ wrote {n:,} price rows to {args.path}" if n else "No prices stored: nothing to dump.")
        else:
            print(f"✓ restored {restore(conn, args.path):,} price rows from {args.path}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
