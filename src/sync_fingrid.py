"""
sync_fingrid.py
~~~~~~~~~~~~~~~
Incremental, idempotent load of the Fingrid datasets in fingrid_catalog.py
into fingrid_observation.

For each dataset:
  * empty table   -> backfill the last --backfill-days (default 400) days
  * otherwise     -> re-fetch from (newest stored slot - --revision-days) to now,
                     because Fingrid revises recent values after publishing them
  * only slots that have already ended are stored, so a forecast is kept as it
    stood before its slot, never as a still-changing future value; the day-ahead
    forecasts in fingrid_catalog.STORE_FUTURE (published once, never revised) are
    the exception and are also stored up to two days ahead
  * rows are upserted on (dataset_id, start_time); an unchanged value is not
    rewritten, so running the sync twice changes nothing

Requests go month by month (one API page each) through fetch_dataset_chunk,
which spaces them 2 s apart and backs off on HTTP 429.

Usage:
    python src/sync_fingrid.py                    # all datasets
    python src/sync_fingrid.py --datasets 75 246  # only these
"""

import argparse
import os
import sys
from datetime import datetime, timedelta, timezone

from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fingrid_catalog import BY_ID, DATASETS, STORE_FUTURE, ensure_catalog  # noqa: E402

PAGE_SIZE = 20000          # fetch_dataset_chunk's pageSize; a month of 15-min data is <= 2,976 rows
API_TIME = "%Y-%m-%dT%H:%M:%SZ"

_UPSERT = """
    INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value)
    VALUES %s
    ON CONFLICT (dataset_id, start_time) DO UPDATE SET
        end_time = EXCLUDED.end_time,
        value = EXCLUDED.value,
        fetched_at = now()
    WHERE (fingrid_observation.value, fingrid_observation.end_time)
          IS DISTINCT FROM (EXCLUDED.value, EXCLUDED.end_time)
    RETURNING 1
"""


def plan_start(last_start, now: datetime, backfill_days: int, revision_days: int) -> datetime:
    """First instant to fetch: a backfill for an empty dataset, else a revision window."""
    if last_start is None:
        start = now - timedelta(days=backfill_days)
    else:
        start = min(last_start, now) - timedelta(days=revision_days)
    return start.replace(hour=0, minute=0, second=0, microsecond=0)


def month_windows(start: datetime, end: datetime) -> list:
    """Split [start, end) into windows that never cross a calendar month (UTC)."""
    windows, cur = [], start
    while cur < end:
        nxt = (cur.replace(day=1, hour=0, minute=0, second=0, microsecond=0) + timedelta(days=32)).replace(day=1)
        windows.append((cur, min(nxt, end)))
        cur = nxt
    return windows


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def sync_dataset(conn, api_key: str, dataset_id: int, now: datetime, fetch,
                 backfill_days: int = 400, revision_days: int = 7) -> dict:
    """Fetch and upsert one dataset; returns a summary dict."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(start_time) FROM fingrid_observation WHERE dataset_id = %s", (dataset_id,))
        last_start = cur.fetchone()[0]
    start = plan_start(last_start, now, backfill_days, revision_days)
    until = now + timedelta(days=2) if dataset_id in STORE_FUTURE else now

    fetched = changed = 0
    for w_start, w_end in month_windows(start, until):
        # The API keeps slots with startTime >= start and endTime <= end, so
        # consecutive windows neither overlap nor leave a gap.
        rows = fetch(dataset_id, api_key, w_start.strftime(API_TIME), w_end.strftime(API_TIME))
        if len(rows) >= PAGE_SIZE:
            raise RuntimeError(f"dataset {dataset_id}: {len(rows)} rows fill a whole page; use smaller windows")
        values = [
            (dataset_id, _parse(r["startTime"]), _parse(r["endTime"]), float(r["value"]))
            for r in rows
            if r.get("value") is not None and _parse(r["endTime"]) <= until
        ]
        fetched += len(values)
        if values:
            with conn.cursor() as cur:
                # execute_values sends pages of 1000 rows and cur.rowcount only covers the last
                # page, so count the RETURNING rows of every page instead.
                changed += len(execute_values(cur, _UPSERT, values, page_size=1000, fetch=True))
        conn.commit()
    return {"dataset_id": dataset_id, "from": start.isoformat(), "fetched": fetched, "changed": changed,
            "mode": "backfill" if last_start is None else "incremental"}


def sync(conn, api_key: str, dataset_ids=None, now: datetime | None = None, fetch=None,
         backfill_days: int = 400, revision_days: int = 7) -> list:
    """Sync every requested dataset; raises after trying them all if any failed."""
    if fetch is None:
        from fetch_grid_data import fetch_dataset_chunk as fetch
    now = now or datetime.now(timezone.utc)
    ids = list(dataset_ids or [d[0] for d in DATASETS])
    unknown = [i for i in ids if i not in BY_ID]
    if unknown:
        raise ValueError(f"not in fingrid_catalog.DATASETS: {unknown}")
    ensure_catalog(conn)

    results, failures = [], []
    for dataset_id in ids:
        try:
            res = sync_dataset(conn, api_key, dataset_id, now, fetch, backfill_days, revision_days)
            results.append(res)
            print(f"  ✓ {dataset_id:>3} {BY_ID[dataset_id][1]:<26} {res['mode']:<11} "
                  f"from {res['from'][:10]}: {res['fetched']:>6} rows fetched, {res['changed']:>6} new or changed")
        except Exception as exc:  # keep going; report every failure at the end
            conn.rollback()
            failures.append(f"{dataset_id}: {exc}")
            print(f"  ✗ {dataset_id:>3} {BY_ID[dataset_id][1]}: {exc}")
    if failures:
        raise RuntimeError("some datasets failed: " + "; ".join(failures))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", nargs="+", type=int, help="Dataset ids (default: all in fingrid_catalog)")
    parser.add_argument("--backfill-days", type=int, default=400)
    parser.add_argument("--revision-days", type=int, default=7)
    args = parser.parse_args()

    from db_connection import get_connection
    from fetch_grid_data import load_api_key

    api_key = load_api_key()
    if not api_key:
        sys.exit("No Fingrid API key: set FINGRID_API_KEY or fingrid_api_key in config.yaml.")
    conn = get_connection()
    try:
        print("Syncing Fingrid datasets into fingrid_observation …")
        sync(conn, api_key, args.datasets, backfill_days=args.backfill_days, revision_days=args.revision_days)
        with conn.cursor() as cur:
            cur.execute("SELECT count(*), min(start_time), max(end_time) FROM fingrid_observation")
            n, lo, hi = cur.fetchone()
        print(f"✓ fingrid_observation holds {n:,} rows ({lo} to {hi})")
    except Exception as exc:
        sys.exit(f"✗ Sync failed: {exc}")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
