"""
test_regression.py: REGRESSION TESTS (golden datasets)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Small hand-made datasets whose correct answers are known exactly, run through
the real SQL: the forecast scorecard (sql/analysis/13-17), the CO2 model
(sql/schema/14_co2_forecast.sql) and the grid event detector
(sql/schema/15_grid_events.sql). Any change to that SQL that alters a result
fails here. Every fixture inserts into a transaction that is rolled back, in
the year 2001, so real data is never touched.

Run only these:  pytest -m regression
"""

import os
from datetime import date, datetime, timedelta, timezone

import pytest

pytestmark = pytest.mark.regression

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
Q = timedelta(minutes=15)
UTC = timezone.utc

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


# ── CO2 forecast (sql/schema/14_co2_forecast.sql) on exact hand-made data ──

CO2_FIRST = datetime(2001, 1, 1, tzinfo=UTC)          # winter: Helsinki is UTC+2
CO2_DAYS = 70


def _residual_load(t: datetime) -> float:
    return 6000 + 1000 * ((t.hour * 7 + t.day * 3) % 11)          # varies by hour and day


@pytest.fixture
def exact_co2(db):
    """co2 = 10 + 0.002 * residual load, exactly, for 70 days (wind on the last day is huge)."""
    from fingrid_catalog import ensure_catalog
    from psycopg2.extras import execute_values

    ensure_catalog(db)
    rows, t = [], CO2_FIRST
    while t < CO2_FIRST + timedelta(days=CO2_DAYS):
        rl = _residual_load(t)
        wind = 2000.0 + (20000.0 if t >= CO2_FIRST + timedelta(days=CO2_DAYS - 1) else 0.0)
        co2 = 10 + 0.002 * (rl - (wind - 2000.0))
        for ds, v in ((165, rl + 2000.0), (246, wind), (247, 0.0), (396, co2)):
            rows.append((ds, t, t + Q, v))
        t += Q
    with db.cursor() as cur:
        execute_values(cur, "INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) VALUES %s",
                       rows, page_size=5000)
    yield db
    db.rollback()


def _co2_rows(db, first_day, last_day):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM co2_forecast(%s, %s) ORDER BY hour_start", (first_day, last_day))
        names = [c.name for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def test_co2_forecast_recovers_an_exact_line(exact_co2):
    rows = _co2_rows(exact_co2, date(2001, 3, 5), date(2001, 3, 6))
    assert len(rows) == 24
    assert [r["hour_fi"] for r in rows] == list(range(24))          # Finnish hours, not UTC
    assert rows[0]["hour_start"] == datetime(2001, 3, 4, 22, tzinfo=UTC)
    for r in rows:
        assert r["co2_forecast"] == pytest.approx(r["co2_actual"], abs=1e-6)
        naive_time = r["hour_start"] - timedelta(hours=48)
        assert r["co2_naive"] == pytest.approx(10 + 0.002 * _residual_load(naive_time), abs=1e-6)


def test_co2_forecast_never_goes_below_the_training_minimum(exact_co2):
    windy_day = date(2001, 3, 11)        # the last UTC day (index 69) carries 20 GW of extra wind
    rows = _co2_rows(exact_co2, windy_day, windy_day + timedelta(days=1))
    with exact_co2.cursor() as cur:
        cur.execute("SELECT min(co2_actual) FROM co2_hourly WHERE day_fi >= %s AND day_fi < %s",
                    (windy_day - timedelta(days=61), windy_day - timedelta(days=1)))
        floor = cur.fetchone()[0]
    windy = [r for r in rows if r["hour_start"] >= datetime(2001, 3, 11, tzinfo=UTC)]
    assert len(windy) == 22                                       # 00-22 UTC of the windy day, inside Finnish 11 March
    assert all(r["co2_unclamped"] < floor for r in windy), "the line must extrapolate below anything seen"
    assert all(r["co2_forecast"] == pytest.approx(floor) for r in windy)


def test_co2_backtest_scores_a_perfect_model(exact_co2):
    with open(os.path.join(ROOT, "sql", "analysis", "19_co2_forecast_backtest.sql"), encoding="utf-8") as fh, \
            exact_co2.cursor() as cur:
        cur.execute(fh.read(), {"start": datetime(2001, 3, 5, tzinfo=UTC), "end": datetime(2001, 3, 9, tzinfo=UTC)})
        r = dict(zip([c.name for c in cur.description], cur.fetchone()))
    assert r["days"] == 4
    assert r["mae_model_g"] == pytest.approx(0, abs=1e-6)
    assert r["mae_naive_g"] > 0
    assert r["pick_in_top3_pct"] == 100
    assert r["co2_at_pick_g"] == pytest.approx(r["best_hour_g"])


# ── Grid events (sql/schema/15_grid_events.sql) on hand-made data ──

EV0 = datetime(2001, 4, 1, tzinfo=UTC)
M = timedelta(minutes=1)


@pytest.fixture
def known_events(db):
    """Two hours of data with every event placed by hand (see the comments)."""
    from fingrid_catalog import ensure_catalog
    from psycopg2.extras import execute_values

    ensure_catalog(db)
    rows = []
    freq = {10: 49.85, 11: 49.80,        # one low event (consecutive minutes)
            30: 0.0,                     # invalid sample (Fingrid writes gaps as 0): ignored
            40: 50.15,                   # one high event
            50: 49.88}                   # a second low event, 39 minutes after the first
    for m in range(120):
        rows.append((177, EV0 + m * M, EV0 + (m + 1) * M, freq.get(m, 50.0)))
    for k in range(40):                  # nuclear, 3-minute: 500 MW drop at minute 60 for three samples
        t = EV0 + k * 3 * M
        rows.append((188, t, t + 3 * M, 2500.0 if 60 <= k * 3 < 69 else 3000.0))
    for q in range(8):                   # 15-minute series: one low-inertia quarter, a two-quarter price spike
        t = EV0 + q * Q
        rows.append((260, t, t + Q, 50.0 if q == 3 else 200.0))
        rows.append((319, t, t + Q, 1200.0 if q in (5, 6) else 40.0))
    with db.cursor() as cur:
        execute_values(cur, "INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) VALUES %s", rows)
    yield db
    db.rollback()


def _events(db):
    with db.cursor() as cur:
        cur.execute("SELECT * FROM grid_events(%s, %s) ORDER BY kind, start_time",
                    (EV0, EV0 + timedelta(hours=2)))
        names = [c.name for c in cur.description]
        return [dict(zip(names, r)) for r in cur.fetchall()]


def test_grid_events_finds_and_merges_each_kind(known_events):
    ev = _events(known_events)
    by_kind = {}
    for e in ev:
        by_kind.setdefault(e["kind"], []).append(e)
    assert {k: len(v) for k, v in by_kind.items()} == {
        "frequency_low": 2, "frequency_high": 1, "nuclear_drop": 1, "low_inertia": 1, "price_spike": 1}

    low = by_kind["frequency_low"]
    assert (low[0]["start_time"], low[0]["samples"], low[0]["peak"]) == (EV0 + 10 * M, 2, 49.80)
    assert low[1]["start_time"] == EV0 + 50 * M
    assert by_kind["frequency_high"][0]["peak"] == 50.15

    drop = by_kind["nuclear_drop"][0]
    assert drop["start_time"] == EV0 + 60 * M and drop["peak"] == -500 and drop["samples"] == 3
    assert drop["freq_min_nearby"] == 49.88             # minute 50 lies within 15 min of the drop (60-69)
    assert all(e["freq_min_nearby"] is None for e in ev if e["kind"] != "nuclear_drop")

    assert by_kind["low_inertia"][0]["peak"] == 50
    spike = by_kind["price_spike"][0]
    assert (spike["start_time"], spike["end_time"], spike["samples"]) == (EV0 + 5 * Q, EV0 + 7 * Q, 2)


def test_grid_events_ignores_invalid_zero_frequency(known_events):
    assert all(not (e["kind"] == "frequency_low" and e["peak"] < 45) for e in _events(known_events))
