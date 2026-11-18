"""
test_price_wind.py: wind and the day-ahead price (sql/analysis/29, src/price_wind.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  - the panel averages hourly and 15-minute slots weighted by their length, and
    drops an hour whose price or readings do not cover it
  - on a synthetic market with a known answer, the regression recovers the price
    drop per GW of wind and how it changes with reservoir storage
  - the wind bins and the wind-weighted price are computed exactly
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import price_wind as pw  # noqa: E402

T0 = datetime(2031, 1, 15, tzinfo=timezone.utc)          # far from real data
Q, M3 = timedelta(minutes=15), timedelta(minutes=3)


@pytest.fixture
def known_hours(db):
    from fingrid_catalog import ensure_catalog

    ensure_catalog(db)
    obs = []
    obs.append((246, T0, T0 + timedelta(hours=1), 3000))                       # hour 0: one hourly forecast
    obs += [(246, T0 + timedelta(hours=1) + i * Q, T0 + timedelta(hours=1) + (i + 1) * Q, v)
            for i, v in enumerate([1000, 2000, 3000, 4000])]                   # hour 1: four quarters
    for h in range(3):
        base = T0 + timedelta(hours=h)
        obs += [(165, base + i * Q, base + (i + 1) * Q, 9000) for i in range(4)]
        obs += [(75, base + i * Q, base + (i + 1) * Q, 1000 * (i + 1)) for i in range(4)]
        n_nuclear = 20 if h == 0 else 14                                         # 14 x 3 min < 45 min
        obs += [(188, base + i * M3, base + (i + 1) * M3, 4000) for i in range(n_nuclear)]
        for city, t in ((178, 0.0), (182, -2.0), (196, -4.0), (185, -6.0)):
            obs += [(city, base + i * M3, base + (i + 1) * M3, t) for i in range(20)]
    prices = [("FI", T0, T0 + timedelta(hours=1), 50.0)]
    prices += [("FI", T0 + timedelta(hours=1) + i * Q, T0 + timedelta(hours=1) + (i + 1) * Q, 10.0 * (i + 1))
               for i in range(4)]
    prices += [("FI", T0 + timedelta(hours=2) + i * Q, T0 + timedelta(hours=2) + (i + 1) * Q, 1.0)
               for i in range(3)]                                                # hour 2: a quarter missing
    prices += [(a, T0 + timedelta(hours=h), T0 + timedelta(hours=h + 1), 40.0)
               for a in ("SE1", "SE3", "EE", "NO4") for h in range(3)]
    with db.cursor() as cur:
        cur.executemany("INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) "
                        "VALUES (%s, %s, %s, %s)", obs)
        cur.executemany("INSERT INTO entsoe_price (area, start_time, end_time, eur_mwh) VALUES (%s, %s, %s, %s)",
                        prices)
    yield db
    db.rollback()


@pytest.mark.regression
def test_the_panel_weights_slots_by_length_and_drops_partial_hours(known_hours):
    with open(os.path.join(ROOT, "sql", "analysis", "29_price_wind_panel.sql"), encoding="utf-8") as fh, \
            known_hours.cursor() as cur:
        cur.execute(fh.read(), {"start": T0, "end": T0 + timedelta(hours=3)})
        names = [c.name for c in cur.description]
        rows = [dict(zip(names, r)) for r in cur.fetchall()]
    assert [r["hour_start"] for r in rows] == [T0, T0 + timedelta(hours=1)]     # hour 2 has 45 min of price
    h0, h1 = rows
    assert (h0["price_fi"], h0["wind_fc_mw"], h0["wind_mw"]) == (pytest.approx(50), pytest.approx(3000),
                                                                   pytest.approx(2500))
    assert (h1["price_fi"], h1["wind_fc_mw"]) == (pytest.approx(25), pytest.approx(2500))
    assert h0["nuclear_mw"] == pytest.approx(4000) and h1["nuclear_mw"] is None   # 42 minutes of readings
    assert h0["temp_c"] == pytest.approx(-3.0) and h0["price_se1"] == pytest.approx(40)
    assert h0["hour_fi"] == 2 and h0["year_fi"] == 2031                          # Helsinki is UTC+2 in January


def _market(n_days=400, seed=3):
    """price = 120 - 20 wind - 4 wind x storage + 15 consumption + hour shape + noise (GW, EUR/MWh)."""
    rng = np.random.default_rng(seed)
    rows, start = [], datetime(2024, 1, 1, tzinfo=timezone.utc)
    storage_by_day = rng.normal(0, 0.4, n_days)
    for h in range(24 * n_days):
        t = start + timedelta(hours=h)
        wind, cons = rng.uniform(0, 6), rng.uniform(8, 13)
        s = storage_by_day[h // 24]
        price = 120 - 20 * wind - 4 * wind * s + 15 * (cons - 10) + 5 * np.sin(2 * np.pi * t.hour / 24) \
            + rng.normal(0, 10)
        rows.append({"hour_start": t, "hour_fi": t.hour, "isodow_fi": t.isoweekday(), "month_fi": t.month,
                     "year_fi": t.year, "wind_fc_mw": wind * 1000, "wind_mw": wind * 1000,
                     "consumption_fc_mw": cons * 1000, "nuclear_mw": 4000 + rng.normal(0, 100),
                     "temp_c": rng.uniform(-20, 20), "storage_z": s, "inflow_z": rng.normal(0, 1),
                     "price_fi": price, "price_se1": price + rng.choice([0.0, 5.0]), "price_ee": price})
    return rows


@pytest.mark.regression
def test_a_known_price_drop_per_gw_and_its_storage_dependence_are_recovered():
    f = pw.fit(_market())
    avg = pw.per_gw(f)
    assert avg["eur_per_gw"] == pytest.approx(20, abs=0.5) and avg["ci_low"] < 20 < avg["ci_high"]
    assert pw.per_gw(f, 0.5)["eur_per_gw"] == pytest.approx(22, abs=0.7)
    inter = pw.storage_interaction(f)
    assert inter["per_unit"] == pytest.approx(4, abs=1.5) and inter["p_value"] < 0.01
    assert pw.consumption_effect(f)["eur_per_gw"] == pytest.approx(15, abs=1)


@pytest.mark.regression
def test_wind_bins_and_the_wind_weighted_price_are_exact():
    rows = [{"wind_fc_mw": w, "price_fi": p, "price_se1": se1, "price_ee": p, "wind_mw": w, "year_fi": 2025}
            for w, p, se1 in ((500, 100.0, 100.0), (500, 60.0, 70.0), (6500, -1.0, 5.0), (6500, 0.0, 0.0))] * 720
    bins = {b["gw_from"]: b for b in pw.by_wind_bin(rows)}
    assert set(bins) == {0, 6} and bins[6]["gw_to"] is None
    assert bins[0]["median"] == pytest.approx(80) and bins[0]["share_below_se1"] == pytest.approx(0.5)
    assert bins[6]["share_zero_or_below"] == 1.0 and bins[6]["share_same_as_se1"] == pytest.approx(0.5)
    cap = pw.capture_by_year(rows)[0]
    assert cap["average"] == pytest.approx(39.75)
    assert cap["wind_captured"] == pytest.approx((500 * 160 + 6500 * -1) / 14000)
