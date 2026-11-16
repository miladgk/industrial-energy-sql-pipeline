"""
test_fingrid_warehouse.py: INTEGRATION TESTS for the Fingrid warehouse
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
src/sync_fingrid.py, src/warehouse_snapshot.py and the forecast analyses
(sql/analysis/13-17) against a real PostgreSQL, with a fake Fingrid API:

  - a backfill stores exactly the slots that have ended, month by month
  - running the sync again changes nothing (idempotent)
  - a revised value inside the revision window is picked up
  - a snapshot dump + restore gives back the same rows
  - the forecast SQL returns hand-computed MAE, bias, RMSE, WAPE, local hours
    and balancing bins for a tiny known dataset

The sync tests use a dataset id that Fingrid does not have and delete it
afterwards; the SQL tests run in a transaction that is rolled back.
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


# ── Forecast SQL on a tiny known dataset ───────────────────────

T0 = datetime(2001, 6, 1, tzinfo=UTC)                       # 03:00 in Helsinki (EEST, UTC+3)
SERIES = {
    75:  [100, 200, 300, 400],      # wind actual
    246: [110, 190, 330, 400],      # wind day-ahead: errors -10, +10, -30, 0
    245: [100, 200, 300, 400],      # wind intraday: perfect
    124: [1000, 1000, 1000, 1000],  # consumption actual
    165: [900, 900, 900, 900],      # consumption day-ahead: errors +100 each
    166: [1000, 1000, 1000, 1000],  # consumption intraday: perfect
    377: [30, 30, 30, 30],          # mFRR need
    375: [50, 50, 50, 50],          # mFRR up (published >= 0)
    376: [-20, -20, -20, -20],      # mFRR down (published <= 0)
    319: [10, 20, 30, 40],          # imbalance price
}
WINDOW = {"start": T0, "end": T0 + timedelta(hours=1)}


@pytest.fixture
def known_forecasts(db):
    from fingrid_catalog import ensure_catalog

    ensure_catalog(db)
    with db.cursor() as cur:
        for dataset_id, values in SERIES.items():
            for i, v in enumerate(values):
                cur.execute("INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) "
                            "VALUES (%s, %s, %s, %s)", (dataset_id, T0 + i * Q, T0 + (i + 1) * Q, v))
        cur.execute("INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) "
                    "VALUES (268, %s, %s, 1000)", (T0, T0 + timedelta(hours=1)))   # wind capacity
    yield db
    db.rollback()


def _query(db, name):
    with open(os.path.join(ROOT, "sql", "analysis", name), encoding="utf-8") as fh, db.cursor() as cur:
        cur.execute(fh.read(), WINDOW)
        names = [c.name for c in cur.description]
        return [dict(zip(names, row)) for row in cur.fetchall()]


def test_scorecard_matches_hand_computed_errors(known_forecasts):
    rows = {(r["variable"], r["product"]): r for r in _query(known_forecasts, "13_forecast_scorecard.sql")}
    assert set(rows) == {("wind", "day_ahead"), ("wind", "intraday"),
                         ("consumption", "day_ahead"), ("consumption", "intraday")}
    wind = rows[("wind", "day_ahead")]
    assert wind["slots"] == 4
    assert wind["mae_mw"] == pytest.approx(12.5)
    assert wind["bias_mw"] == pytest.approx(-7.5)
    assert wind["rmse_mw"] == pytest.approx(275 ** 0.5)
    assert wind["wape_pct"] == pytest.approx(5.0)                 # 50 / 1000
    assert wind["mae_pct_of_capacity"] == pytest.approx(1.25)     # 12.5 / 1000
    assert rows[("wind", "intraday")]["mae_mw"] == 0
    cons = rows[("consumption", "day_ahead")]
    assert cons["mae_mw"] == pytest.approx(100) and cons["bias_mw"] == pytest.approx(100)
    assert cons["mae_pct_of_capacity"] is None                    # capacity is wind-only


def test_error_by_hour_uses_finnish_time(known_forecasts):
    rows = _query(known_forecasts, "14_forecast_error_by_hour.sql")
    assert {r["hour_fi"] for r in rows} == {3}                     # 00:00 UTC in June = 03:00 EEST
    assert len(rows) == 4


def test_balancing_bins_group_the_net_surprise(known_forecasts):
    rows = _query(known_forecasts, "17_forecast_error_vs_balancing.sql")
    # net surprise = wind error - consumption error = -110, -90, -130, -100: all in [-500, 0)
    assert len(rows) == 1
    b = rows[0]
    assert (b["bin_from_mw"], b["bin_to_mw"], b["slots"]) == (-500, 0, 4)
    assert b["mean_net_surprise_mw"] == pytest.approx(-107.5)
    assert b["mean_mfrr_need_mw"] == pytest.approx(30)
    assert b["mean_mfrr_up_mw"] == pytest.approx(50) and b["mean_mfrr_down_mw"] == pytest.approx(-20)
    assert b["median_imbalance_price"] == pytest.approx(25)


def test_biggest_misses_skip_incomplete_days(known_forecasts):
    assert _query(known_forecasts, "16_forecast_biggest_misses.sql") == []   # 4 slots < 90
