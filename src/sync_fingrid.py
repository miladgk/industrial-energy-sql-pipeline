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
  * with --from DATE, older history is also filled in, backwards from the
    oldest stored slot to DATE, one committed window at a time: the stored
    history always stays contiguous, so a run that stops half-way (rate limit,
    timeout) is simply resumed by running it again. Two empty windows in a row
    mean the dataset did not exist yet (e.g. mFRR before 2025) and end it

Requests go month by month, or in shorter windows for datasets finer than
15 minutes, so each fits in one API page; fetch_dataset_chunk spaces them
2 s apart and backs off on HTTP 429. Some datasets were finer in the past than
the catalogue says today (kinetic energy was 1-minute in 2023), so a window
that still fills a whole page is halved until each part fits.

Older history comes in a second format: until spring 2024 the 3-minute and
1-minute series were published as "instant" readings (startTime = endTime, at
:01, :04, :07, ... for 3-minute data), and on the days the format changed both
formats appear side by side. An instant reading at t is stored as the slot
[t, t + resolution), unless a regular slot of the same answer already covers t,
in which case it is the same reading twice and is dropped (and counted); where
the formats meet, the instant's slot is cut short at the next reading, so no two
stored slots ever overlap.

Fingrid's history also has periods with two overlapping series of one dataset
(15-minute slots beside 5-minute ones, or a second 15-minute series shifted by
6 minutes). The warehouse keeps one series per dataset: after each sync,
remove_overlaps() deletes any slot that is off the dataset's grid or of another
length and overlaps a slot that is on it. Off-grid slots that overlap nothing
(the old instant readings, or a period with only finer data) are kept.

Usage:
    python src/sync_fingrid.py                    # all datasets
    python src/sync_fingrid.py --datasets 75 246  # only these
    python src/sync_fingrid.py --from 2023-11-01  # also fill older history
"""

import argparse
import os
import sys
from bisect import bisect_right
from datetime import date, datetime, timedelta, timezone

from psycopg2.extras import execute_values

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from fingrid_catalog import BY_ID, DATASETS, STORE_FUTURE, ensure_catalog, refresh_dataset_summary  # noqa: E402

PAGE_SIZE = 20000          # fetch_dataset_chunk's pageSize
WINDOW_ROWS = 19000        # aim below a full page; 1-minute data gives 13-day windows
API_TIME = "%Y-%m-%dT%H:%M:%SZ"
MIN_SPLIT = timedelta(hours=1)   # a window is never halved below this
HISTORY_EMPTY_STOP = 2           # consecutive empty windows that end a history fill

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


def request_windows(start: datetime, end: datetime, resolution: timedelta) -> list:
    """Month windows, each split further so that no window holds more than WINDOW_ROWS slots."""
    max_span = timedelta(days=max(1, int(WINDOW_ROWS * resolution / timedelta(days=1))))
    out = []
    for w_start, w_end in month_windows(start, end):
        while w_start < w_end:
            out.append((w_start, min(w_start + max_span, w_end)))
            w_start += max_span
    return out


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fetch_window(fetch, dataset_id: int, api_key: str, w_start: datetime, w_end: datetime) -> list:
    """Every row of one window. The API returns one page, so a window that fills it is halved
    (at a whole hour) until each part fits; the halves neither overlap nor leave a gap."""
    # The API keeps slots with startTime >= start and endTime <= end.
    rows = fetch(dataset_id, api_key, w_start.strftime(API_TIME), w_end.strftime(API_TIME))
    if len(rows) < PAGE_SIZE:
        return rows
    mid = (w_start + (w_end - w_start) / 2).replace(minute=0, second=0, microsecond=0)
    if w_end - w_start <= MIN_SPLIT or mid <= w_start:
        raise RuntimeError(f"dataset {dataset_id}: {len(rows)} rows in {w_start}..{w_end} still fill a whole page")
    return fetch_window(fetch, dataset_id, api_key, w_start, mid) + fetch_window(fetch, dataset_id, api_key, mid, w_end)


SKIPPED = {}                     # dataset_id -> instant readings dropped as duplicates in this process
INSTANTS = {}                    # dataset_id -> instant readings stored as slots in this process


def to_slots(rows: list, resolution: timedelta) -> tuple[list, int]:
    """(start, end, value) slots from one API answer: regular slots as they are, instant readings
    as [t, t + resolution) unless a regular slot covers t. Returns the slots and the dropped count."""
    regular, instants = [], []
    for r in rows:
        if r.get("value") is None:
            continue
        start, end = _parse(r["startTime"]), _parse(r["endTime"])
        (regular if end > start else instants).append((start, end, float(r["value"])))
    covered = sorted((s, e) for s, e, _ in regular)
    starts = [s for s, _ in covered]
    every_start = sorted(set(starts) | {t for t, _, _ in instants})
    out, dropped = list(regular), 0
    for t, _, v in instants:
        i = bisect_right(starts, t) - 1
        if i >= 0 and covered[i][0] <= t < covered[i][1]:
            dropped += 1
            continue
        # end at t + resolution, or earlier where the next reading of either kind begins
        j = bisect_right(every_start, t)
        nxt = every_start[j] if j < len(every_start) else t + resolution
        out.append((t, min(t + resolution, nxt), v))
    return out, dropped


def _store(conn, dataset_id: int, rows: list, w_start: datetime, w_end: datetime, until: datetime) -> tuple:
    """Upsert one window's rows and commit; returns (rows kept, rows new or changed)."""
    with conn.cursor() as cur:          # the monthly partitions this window writes into
        cur.execute("SELECT ensure_fingrid_partitions(%s::date, %s::date)", (w_start, w_end))
    slots, dropped = to_slots(rows, _resolution(dataset_id))
    n_instant = sum(1 for r in rows if r.get("value") is not None and r["startTime"] == r["endTime"]) - dropped
    values = [(dataset_id, s, e, v) for s, e, v in slots if e <= until]
    if dropped:
        SKIPPED[dataset_id] = SKIPPED.get(dataset_id, 0) + dropped
    if n_instant:
        INSTANTS[dataset_id] = INSTANTS.get(dataset_id, 0) + n_instant
    changed = 0
    if values:
        with conn.cursor() as cur:
            # execute_values sends pages of 1000 rows and cur.rowcount only covers the last
            # page, so count the RETURNING rows of every page instead.
            changed = len(execute_values(cur, _UPSERT, values, page_size=1000, fetch=True))
    conn.commit()
    return len(values), changed


def find_overlaps(slots: list, resolution: timedelta) -> list:
    """Start times of the slots to drop: off the grid (or of another length) and overlapping a slot
    that is on it. *slots* are (start, end) pairs sorted by start."""
    res_s = int(resolution.total_seconds())
    on = lambda s, e: e - s == resolution and int(s.timestamp()) % res_s == 0
    grid = [(s, e) for s, e in slots if on(s, e)]
    starts = [s for s, _ in grid]
    drop = []
    for s, e in slots:
        if on(s, e):
            continue
        i = bisect_right(starts, s) - 1                 # the on-grid slot starting at or before s ...
        if (i >= 0 and grid[i][1] > s) or (i + 1 < len(grid) and grid[i + 1][0] < e):   # ... or the next one
            drop.append(s)
    return drop


def remove_overlaps(conn, dataset_id: int, since: datetime) -> int:
    """Delete off-grid slots from *since* on that overlap an on-grid slot of the same dataset.
    One ordered read and one sweep: a per-row SQL lookup took minutes on three years of 1-minute rows."""
    with conn.cursor() as cur:
        cur.execute("SELECT start_time, end_time FROM fingrid_observation "
                    "WHERE dataset_id = %s AND start_time >= %s ORDER BY start_time", (dataset_id, since))
        drop = find_overlaps(cur.fetchall(), _resolution(dataset_id))
        if drop:
            cur.execute("DELETE FROM fingrid_observation WHERE dataset_id = %s AND start_time = ANY(%s)",
                        (dataset_id, drop))
    conn.commit()
    return len(drop)


def _resolution(dataset_id: int) -> timedelta:
    return BY_ID[dataset_id][5] if dataset_id in BY_ID else timedelta(minutes=15)   # tests use ids outside the catalogue


def fill_history(conn, api_key: str, dataset_id: int, history_from: datetime, fetch) -> dict:
    """Fill [history_from, oldest stored slot) backwards, newest window first, committing each,
    so the stored history stays contiguous whatever stops the run. Ends after
    HISTORY_EMPTY_STOP empty windows in a row: the dataset did not exist yet."""
    with conn.cursor() as cur:
        cur.execute("SELECT min(start_time) FROM fingrid_observation WHERE dataset_id = %s", (dataset_id,))
        first = cur.fetchone()[0]
    fetched = changed = empty = 0
    if first is not None and first > history_from:
        for w_start, w_end in reversed(request_windows(history_from, first, _resolution(dataset_id))):
            f, c = _store(conn, dataset_id, fetch_window(fetch, dataset_id, api_key, w_start, w_end),
                          w_start, w_end, first)
            fetched, changed = fetched + f, changed + c
            empty = empty + 1 if f == 0 else 0
            if empty >= HISTORY_EMPTY_STOP:
                break
    with conn.cursor() as cur:
        cur.execute("SELECT min(start_time) FROM fingrid_observation WHERE dataset_id = %s", (dataset_id,))
        oldest = cur.fetchone()[0]
    return {"history_fetched": fetched, "history_changed": changed, "oldest": oldest}


def sync_dataset(conn, api_key: str, dataset_id: int, now: datetime, fetch,
                 backfill_days: int = 400, revision_days: int = 7, history_from: datetime | None = None) -> dict:
    """Fetch and upsert one dataset (and, with history_from, its older history); returns a summary dict."""
    with conn.cursor() as cur:
        cur.execute("SELECT max(start_time) FROM fingrid_observation WHERE dataset_id = %s", (dataset_id,))
        last_start = cur.fetchone()[0]
    start = plan_start(last_start, now, backfill_days, revision_days)
    until = now + timedelta(days=2) if dataset_id in STORE_FUTURE else now

    fetched = changed = 0
    for w_start, w_end in request_windows(start, until, _resolution(dataset_id)):
        f, c = _store(conn, dataset_id, fetch_window(fetch, dataset_id, api_key, w_start, w_end), w_start, w_end, until)
        fetched, changed = fetched + f, changed + c
    out = {"dataset_id": dataset_id, "from": start.isoformat(), "fetched": fetched, "changed": changed,
           "mode": "backfill" if last_start is None else "incremental"}
    if history_from is not None:
        out.update(fill_history(conn, api_key, dataset_id, history_from, fetch))
    out["overlaps_removed"] = remove_overlaps(conn, dataset_id, history_from if history_from is not None else start)
    return out


def sync(conn, api_key: str, dataset_ids=None, now: datetime | None = None, fetch=None,
         backfill_days: int = 400, revision_days: int = 7, history_from: datetime | None = None) -> list:
    """Sync every requested dataset; raises after trying them all if any failed."""
    if fetch is None:
        from fingrid_api import fetch_dataset_chunk as fetch
    now = now or datetime.now(timezone.utc)
    ids = list(dataset_ids or [d[0] for d in DATASETS])
    unknown = [i for i in ids if i not in BY_ID]
    if unknown:
        raise ValueError(f"not in fingrid_catalog.DATASETS: {unknown}")
    ensure_catalog(conn)

    results, failures = [], []
    for dataset_id in ids:
        try:
            res = sync_dataset(conn, api_key, dataset_id, now, fetch, backfill_days, revision_days, history_from)
            results.append(res)
            print(f"  ✓ {dataset_id:>3} {BY_ID[dataset_id][1]:<26} {res['mode']:<11} "
                  f"from {res['from'][:10]}: {res['fetched']:>6} rows fetched, {res['changed']:>6} new or changed", flush=True)
            if history_from is not None:
                print(f"      history: {res['history_fetched']:>7} older rows, {res['history_changed']:>7} new; "
                      f"oldest stored slot now {res['oldest']}", flush=True)
            if res["overlaps_removed"]:
                print(f"      removed {res['overlaps_removed']} off-grid slots overlapping the dataset's own grid", flush=True)
            if INSTANTS.get(dataset_id) or SKIPPED.get(dataset_id):
                print(f"      instant readings: {INSTANTS.get(dataset_id, 0)} stored as slots, "
                      f"{SKIPPED.get(dataset_id, 0)} dropped as duplicates of a regular slot", flush=True)
        except Exception as exc:  # keep going; report every failure at the end
            conn.rollback()
            failures.append(f"{dataset_id}: {exc}")
            print(f"  ✗ {dataset_id:>3} {BY_ID[dataset_id][1]}: {exc}")
    refresh_dataset_summary(conn)          # what was stored counts even if some datasets failed
    if failures:
        raise RuntimeError("some datasets failed: " + "; ".join(failures))
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--datasets", nargs="+", type=int, help="Dataset ids (default: all in fingrid_catalog)")
    parser.add_argument("--backfill-days", type=int, default=400)
    parser.add_argument("--revision-days", type=int, default=7)
    parser.add_argument("--from", dest="history_from", type=date.fromisoformat, metavar="YYYY-MM-DD",
                        help="Also fill older history back to this UTC date")
    args = parser.parse_args()
    history_from = (datetime.combine(args.history_from, datetime.min.time(), tzinfo=timezone.utc)
                    if args.history_from else None)

    from db_connection import get_connection
    from fingrid_api import load_api_key

    api_key = load_api_key()
    if not api_key:
        sys.exit("No Fingrid API key: set FINGRID_API_KEY or fingrid_api_key in config.yaml.")
    conn = get_connection()
    try:
        print("Syncing Fingrid datasets into fingrid_observation …")
        sync(conn, api_key, args.datasets, backfill_days=args.backfill_days, revision_days=args.revision_days,
             history_from=history_from)
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
