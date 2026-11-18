"""
test_fingrid_warehouse.py: INTEGRATION TESTS for the Fingrid warehouse
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
src/sync_fingrid.py and src/warehouse_snapshot.py against a real PostgreSQL,
with a fake Fingrid API:

  - a backfill stores exactly the slots that have ended, month by month
  - running the sync again changes nothing (idempotent)
  - a revised value inside the revision window is picked up
  - a snapshot dump + restore gives back the same rows
  - only day-ahead forecasts are stored before their slot has ended

The tests use a dataset id that Fingrid does not have and delete it afterwards.
The hand-computed SQL results are in test_regression.py.
"""

import os
from datetime import datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.integration

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
Q = timedelta(minutes=15)
UTC = timezone.utc
TEST_ID = 990075
TEST_DATASET = (TEST_ID, "test_series", "Test series", "MW", "actual", Q)


def _iso(t: datetime) -> str:
    return t.strftime("%Y-%m-%dT%H:%M:%S.000Z")


class FakeAPI:
    """Serves 15-minute slots like data.fingrid.fi: startTime >= start and endTime <= end."""

    def __init__(self, first: datetime, last: datetime):
        self.values, t = {}, first
        while t < last:
            self.values[t] = 100.0
            t += Q
        self.calls = []

    def __call__(self, dataset_id, api_key, start, end):
        s = datetime.strptime(start, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        e = datetime.strptime(end, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)
        self.calls.append((s, e))
        return [{"datasetId": dataset_id, "startTime": _iso(t), "endTime": _iso(t + Q), "value": v}
                for t, v in sorted(self.values.items()) if t >= s and t + Q <= e]


@pytest.fixture
def test_dataset(db):
    from fingrid_catalog import ensure_catalog

    ensure_catalog(db, [TEST_DATASET])
    yield TEST_ID
    with db.cursor() as cur:
        cur.execute("DELETE FROM fingrid_observation WHERE dataset_id = %s", (TEST_ID,))
        cur.execute("DELETE FROM fingrid_dataset WHERE dataset_id = %s", (TEST_ID,))
        # The sync created monthly partitions for the test's year 2001; drop them again.
        cur.execute("SELECT c.relname FROM pg_inherits i JOIN pg_class c ON c.oid = i.inhrelid "
                    "WHERE i.inhparent = 'fingrid_observation'::regclass AND c.relname LIKE 'fingrid_observation_2001_%%'")
        for (name,) in cur.fetchall():
            cur.execute(f'DROP TABLE "{name}"')          # name comes from the catalogue, pattern-checked above
    db.commit()


def _stored(db, dataset_id):
    with db.cursor() as cur:
        cur.execute("SELECT start_time, end_time, value FROM fingrid_observation "
                    "WHERE dataset_id = %s ORDER BY start_time", (dataset_id,))
        rows = cur.fetchall()
    db.rollback()
    return rows


# ── Sync ───────────────────────────────────────────────────────

def test_month_windows_cover_the_range_without_gaps():
    from sync_fingrid import month_windows

    start, end = datetime(2001, 1, 20, tzinfo=UTC), datetime(2001, 4, 2, 6, 7, tzinfo=UTC)
    windows = month_windows(start, end)
    assert windows[0][0] == start and windows[-1][1] == end
    assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))
    assert [w[0].month for w in windows] == [1, 2, 3, 4]
    assert all(w[0].month == (w[1] - timedelta(microseconds=1)).month for w in windows)


def test_request_windows_fit_one_api_page():
    from sync_fingrid import PAGE_SIZE, request_windows

    start, end = datetime(2001, 1, 1, tzinfo=UTC), datetime(2001, 3, 1, tzinfo=UTC)
    for resolution, longest in ((timedelta(minutes=1), timedelta(days=13)), (Q, timedelta(days=31))):
        windows = request_windows(start, end, resolution)
        assert windows[0][0] == start and windows[-1][1] == end
        assert all(a[1] == b[0] for a, b in zip(windows, windows[1:]))
        assert max(w[1] - w[0] for w in windows) == longest
        assert all((w[1] - w[0]) / resolution < PAGE_SIZE for w in windows)


def test_backfill_stores_only_ended_slots_and_rerun_changes_nothing(db, test_dataset):
    from sync_fingrid import sync_dataset

    now = datetime(2001, 3, 10, 6, 7, tzinfo=UTC)
    api = FakeAPI(datetime(2001, 1, 1, tzinfo=UTC), datetime(2001, 3, 12, tzinfo=UTC))

    first = sync_dataset(db, "key", test_dataset, now, api, backfill_days=30, revision_days=7)
    rows = _stored(db, test_dataset)
    # from 2001-02-08 00:00 (now - 30 days, floored) to the slot ending 06:00
    assert first["mode"] == "backfill"
    assert len(rows) == 30 * 96 + 6 * 4 == first["fetched"] == first["changed"]
    assert rows[0][0] == datetime(2001, 2, 8, tzinfo=UTC)
    assert max(r[1] for r in rows) <= now
    assert [c[0].month for c in api.calls] == [2, 3]          # one request per calendar month

    second = sync_dataset(db, "key", test_dataset, now, api, backfill_days=30, revision_days=7)
    assert second["mode"] == "incremental" and second["changed"] == 0
    assert _stored(db, test_dataset) == rows


def test_revised_values_inside_the_window_are_updated(db, test_dataset):
    from sync_fingrid import sync_dataset

    now = datetime(2001, 3, 10, 6, 7, tzinfo=UTC)
    api = FakeAPI(datetime(2001, 1, 1, tzinfo=UTC), datetime(2001, 3, 12, tzinfo=UTC))
    sync_dataset(db, "key", test_dataset, now, api, backfill_days=30, revision_days=7)

    recent, old = datetime(2001, 3, 8, 12, tzinfo=UTC), datetime(2001, 2, 15, 12, tzinfo=UTC)
    api.values[recent] = 123.0      # inside the 7-day revision window
    api.values[old] = 456.0         # outside it: not re-fetched
    res = sync_dataset(db, "key", test_dataset, now, api, backfill_days=30, revision_days=7)
    stored = {r[0]: r[2] for r in _stored(db, test_dataset)}
    assert res["changed"] == 1
    assert stored[recent] == 123.0 and stored[old] == 100.0


def test_snapshot_round_trip(db, test_dataset, tmp_path):
    from sync_fingrid import sync_dataset
    from warehouse_snapshot import dump, restore

    now = datetime(2001, 3, 2, tzinfo=UTC)
    sync_dataset(db, "key", test_dataset, now, FakeAPI(datetime(2001, 2, 27, tzinfo=UTC), now),
                 backfill_days=2, revision_days=1)
    before = _stored(db, test_dataset)
    path = str(tmp_path / "snapshot.csv.gz")
    dump(db, path)

    with db.cursor() as cur:
        cur.execute("DELETE FROM fingrid_observation WHERE dataset_id = %s", (test_dataset,))
    db.commit()
    assert restore(db, path) == len(before)
    assert _stored(db, test_dataset) == before
    assert restore(db, path) == 0                              # restoring twice adds nothing


def test_restore_skips_datasets_the_catalogue_does_not_know(db, tmp_path):
    import gzip
    from warehouse_snapshot import restore

    path = str(tmp_path / "newer.csv.gz")
    with gzip.open(path, "wt") as fh:   # as if written by newer code with an extra dataset
        fh.write("dataset_id,start_time,end_time,value\n999999,2001-01-01 00:00:00+00,2001-01-01 00:15:00+00,1.0\n")
    assert restore(db, path) == 0


def test_day_ahead_forecasts_are_stored_ahead_others_only_once_ended(db, test_dataset, monkeypatch):
    import sync_fingrid

    now = datetime(2001, 3, 10, 6, 7, tzinfo=UTC)
    api = FakeAPI(datetime(2001, 3, 1, tzinfo=UTC), datetime(2001, 3, 15, tzinfo=UTC))
    monkeypatch.setattr(sync_fingrid, "STORE_FUTURE", {test_dataset})
    sync_fingrid.sync_dataset(db, "key", test_dataset, now, api, backfill_days=2, revision_days=1)
    assert max(r[1] for r in _stored(db, test_dataset)) == now.replace(minute=0) + timedelta(days=2)

    monkeypatch.setattr(sync_fingrid, "STORE_FUTURE", set())
    with db.cursor() as cur:
        cur.execute("DELETE FROM fingrid_observation WHERE dataset_id = %s", (test_dataset,))
    db.commit()
    sync_fingrid.sync_dataset(db, "key", test_dataset, now, api, backfill_days=2, revision_days=1)
    assert max(r[1] for r in _stored(db, test_dataset)) <= now


# ── Older history (--from) ─────────────────────────────────────

class FlakyAPI(FakeAPI):
    """A FakeAPI that fails every call after the first *ok* ones, like a run cut short by a rate limit."""

    def __init__(self, first, last, ok):
        super().__init__(first, last)
        self.ok = ok

    def __call__(self, *args):
        if len(self.calls) >= self.ok:
            self.calls.append(None)
            raise RuntimeError("rate limited")
        return super().__call__(*args)


def _contiguous(rows):
    return all(a[1] == b[0] for a, b in zip(rows, rows[1:]))


def test_history_fills_backwards_and_a_cut_short_run_resumes(db, test_dataset):
    from sync_fingrid import sync_dataset

    now = datetime(2001, 3, 10, 6, 7, tzinfo=UTC)
    history = datetime(2001, 1, 1, tzinfo=UTC)
    sync_dataset(db, "key", test_dataset, now, FakeAPI(history, now), backfill_days=5, revision_days=1)
    assert _stored(db, test_dataset)[0][0] == datetime(2001, 3, 5, tzinfo=UTC)

    # The forward step takes one call; the history then gets its newest window (1-5 March)
    # before the "rate limit" stops it.
    flaky = FlakyAPI(history, now, ok=2)
    with pytest.raises(RuntimeError):
        sync_dataset(db, "key", test_dataset, now, flaky, backfill_days=5, revision_days=1, history_from=history)
    rows = _stored(db, test_dataset)
    assert rows[0][0] == datetime(2001, 3, 1, tzinfo=UTC) and _contiguous(rows)   # no hole left behind

    res = sync_dataset(db, "key", test_dataset, now, FakeAPI(history, now), backfill_days=5, revision_days=1,
                       history_from=history)
    rows = _stored(db, test_dataset)
    assert rows[0][0] == history and res["oldest"] == history and _contiguous(rows)
    assert len(rows) == (datetime(2001, 3, 10, 6, tzinfo=UTC) - history) / Q
    again = sync_dataset(db, "key", test_dataset, now, FakeAPI(history, now), backfill_days=5, revision_days=1,
                         history_from=history)
    assert again["history_fetched"] == 0                                           # nothing older is asked for


def test_history_stops_where_the_dataset_begins(db, test_dataset):
    from sync_fingrid import sync_dataset

    now = datetime(2001, 4, 10, tzinfo=UTC)
    api = FakeAPI(datetime(2001, 4, 1, tzinfo=UTC), now)           # the series starts on 1 April
    sync_dataset(db, "key", test_dataset, now, api, backfill_days=5, revision_days=1)
    api.calls.clear()
    res = sync_dataset(db, "key", test_dataset, now, api, backfill_days=5, revision_days=1,
                       history_from=datetime(2001, 1, 1, tzinfo=UTC))
    history_calls = [c for c in api.calls if c[1] <= datetime(2001, 4, 5, tzinfo=UTC)]
    assert [c[0].month for c in history_calls] == [4, 3, 2]          # newest first; March and February empty
    assert res["oldest"] == datetime(2001, 4, 1, tzinfo=UTC)


def test_a_window_that_fills_a_page_is_halved(monkeypatch):
    import sync_fingrid

    monkeypatch.setattr(sync_fingrid, "PAGE_SIZE", 200)          # as if the data were finer than expected
    start, end = datetime(2001, 1, 1, tzinfo=UTC), datetime(2001, 1, 8, tzinfo=UTC)
    api = FakeAPI(start, end)
    rows = sync_fingrid.fetch_window(api, TEST_ID, "key", start, end)
    times = [r["startTime"] for r in rows]
    assert len(rows) == 7 * 96 and len(set(times)) == len(times) and times == sorted(times)
    assert len(api.calls) > 1


def test_instant_readings_become_slots_unless_a_regular_slot_covers_them(db, test_dataset):
    import sync_fingrid

    resolution = timedelta(minutes=3)
    t0 = datetime(2001, 3, 1, tzinfo=UTC)
    iso = lambda t: t.strftime("%Y-%m-%dT%H:%M:%S.000Z")
    # Old format (instants at :01, :04, ...) for the first hour, both formats in the second
    # (Fingrid's 2024-04-20 pattern), then regular slots only.
    old = [{"startTime": iso(t0 + timedelta(minutes=1 + 3 * i)), "endTime": iso(t0 + timedelta(minutes=1 + 3 * i)),
            "value": 7.0} for i in range(40)]
    new = [{"startTime": iso(t0 + timedelta(hours=1, minutes=3 * i)),
            "endTime": iso(t0 + timedelta(hours=1, minutes=3 * i + 3)), "value": 8.0} for i in range(40)]
    slots, dropped = sync_fingrid.to_slots(old + new, resolution)
    assert dropped == 20                                       # the second hour's instants repeat the slots
    assert len(slots) == 60
    first_hour = sorted(s for s in slots if s[0] < t0 + timedelta(hours=1))
    assert len(first_hour) == 20 and first_hour[0][:2] == (t0 + timedelta(minutes=1), t0 + timedelta(minutes=4))
    assert all(a[1] <= b[0] for a, b in zip(sorted(slots), sorted(slots)[1:]))      # no two slots overlap

    def api(dataset_id, api_key, start, end):                 # like the API: rows inside the window
        s_, e_ = (datetime.strptime(x, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC) for x in (start, end))
        return [r for r in old + new if s_ <= datetime.strptime(r["startTime"], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=UTC)
                and datetime.strptime(r["endTime"], "%Y-%m-%dT%H:%M:%S.000Z").replace(tzinfo=UTC) <= e_]
    res = sync_fingrid.sync_dataset(db, "key", test_dataset, t0 + timedelta(hours=3), api, backfill_days=1, revision_days=1)
    rows = _stored(db, test_dataset)
    assert len(rows) == 60 and all(r[1] > r[0] for r in rows) and res["fetched"] == 60
    assert all(a[1] <= b[0] for a, b in zip(rows, rows[1:]))                     # none overlap in the table


def test_overlapping_series_keep_the_slot_on_the_grid(db, test_dataset):
    """Fingrid's 2024 pattern: a second 15-minute series shifted by 6 minutes, and 5-minute slots
    beside 15-minute ones. One series stays: the one on the dataset's own grid."""
    from sync_fingrid import remove_overlaps

    t0 = datetime(2001, 3, 1, tzinfo=UTC)
    rows = [(TEST_ID, t0 + i * Q, t0 + (i + 1) * Q, 1.0) for i in range(8)]                        # on the grid
    rows += [(TEST_ID, t0 + i * Q + timedelta(minutes=6), t0 + (i + 1) * Q + timedelta(minutes=6), 2.0)
             for i in range(4)]                                                                    # shifted
    rows += [(TEST_ID, t0 + timedelta(hours=2, minutes=5 * i), t0 + timedelta(hours=2, minutes=5 * i + 5), 3.0)
             for i in range(6)]                                                                    # finer, alone
    with db.cursor() as cur:
        cur.execute("SELECT ensure_fingrid_partitions('2001-03-01', '2001-03-02')")
        cur.executemany("INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) "
                        "VALUES (%s, %s, %s, %s)", rows)
    db.commit()
    assert remove_overlaps(db, TEST_ID, t0) == 4
    stored = _stored(db, TEST_ID)
    assert [r[2] for r in stored] == [1.0] * 8 + [3.0] * 6          # finer data with nothing to clash with stays
    assert all(a[1] <= b[0] for a, b in zip(stored, stored[1:]))
