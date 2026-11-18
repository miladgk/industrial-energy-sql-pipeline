"""
test_ev_charging.py: electric cars and consumption (src/ev_charging.py, sql/analysis/31)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
  - Traficom's json-stat answers become the fleet and km per year
  - the energy estimate, the fleet between quarters and the windows are exact
  - on a synthetic year with a known evening-only increase, growth by hour finds it
    in the evening and the night-minus-evening contrast matches the scenario
  - the hourly panel mixes 1-minute boiler and 15-minute consumption data
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import ev_charging as ev  # noqa: E402
import strike_effect as se  # noqa: E402


def _jsonstat(dims: dict, value_of):
    import itertools
    ids = ["ContentsCode"] + list(dims)
    cats = [["x"]] + [list(v) for v in dims.values()]
    return {"id": ids, "dimension": {i: {"category": {"index": {c: k for k, c in enumerate(cs)}}}
                                     for i, cs in zip(ids, cats)},
            "value": [value_of(c[1:]) for c in itertools.product(*cats)]}


@pytest.mark.smoke
def test_fleet_and_km_from_traficom_answers(monkeypatch):
    stock = _jsonstat({"Maakunta": ["MA1"], "Ajoneuvoluokka": ["01", "02"], "Käyttövoima": ["YH", "04", "39", "44"],
                       "Vuosineljännes": ["2025Q4", "2026Q1"]},
                      lambda c: {"YH": 1000, "04": 100, "39": 50, "44": 5}[c[2]] * (2 if c[3] == "2026Q1" else 1)
                      * (1 if c[1] == "01" else 0.1))
    assert ev.fleet(post=lambda url, q: stock) == [
        {"quarter": "2025Q4", "bev": 110.0, "phev": 60.5, "all": 1100.0},
        {"quarter": "2026Q1", "bev": 220.0, "phev": 121.0, "all": 2200.0}]
    insp = _jsonstat({"Katsastusvuosi": ["2025"], "Ajoneuvoluokka": ["Henkilöauto"],
                      "Käyttövoima": ["Sähkö", "Bensiinihybridi (ladattava)"], "Ajoneuvon ikä": ["4"],
                      "Tiedot": ["Ka", "Ajon_kats_lkm"]},
                     lambda c: (80000 if c[2] == "Sähkö" else 60000) if c[4] == "Ka" else 7)
    meta = {"variables": [{"code": "Katsastusvuosi", "values": ["2024", "2025"]}]}

    class Resp:
        def read(self): return __import__("json").dumps(meta).encode()
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(ev.urllib.request, "urlopen", lambda req, timeout: Resp())
    km = ev.km_per_year(post=lambda url, q: insp)
    assert km["inspection_year"] == 2025 and km["bev"]["km_per_year"] == 20000 and km["phev"]["km_per_year"] == 15000
    with pytest.raises(ValueError):
        ev._post("https://example.com/x.px", {})


@pytest.mark.regression
def test_energy_fleet_between_quarters_and_windows():
    e = ev.energy(1000, 1000, {"bev": 20000, "phev": 10000})
    assert e["central"]["gwh_per_year"] == pytest.approx((1000 * 20000 * 0.20 + 1000 * 10000 * 0.20 * 0.35) / 1e6)
    assert e["low"]["mw"] < e["central"]["mw"] < e["high"]["mw"]
    rows = [{"quarter": "2025Q4", "bev": 100, "phev": 0}, {"quarter": "2026Q1", "bev": 190, "phev": 90}]
    assert ev.quarter_end("2026Q1") == date(2026, 3, 31) and ev.quarter_end("2025Q4") == date(2025, 12, 31)
    assert ev.fleet_at(rows, date(2026, 2, 14))["bev"] == pytest.approx(100 + 90 * 45 / 90)
    assert ev.fleet_at(rows, date(2027, 1, 1)) == {"bev": 190.0, "phev": 90.0}
    a, b = ev.windows(date(2026, 11, 17))
    assert b == (date(2025, 11, 18), date(2026, 11, 17)) and a == (date(2024, 11, 18), date(2025, 11, 17))
    assert ev.scenario_contrast(30, ev.EVENING) == pytest.approx(-30 * 24 / 5)
    assert ev.scenario_contrast(30, ev.NIGHT) == pytest.approx(30 * 24 / 8)


@pytest.mark.regression
def test_a_known_evening_increase_is_found_where_it_was_put():
    rng = np.random.default_rng(5)
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    rows = []
    for h in range(24 * 730):
        t = start + timedelta(hours=h)
        local = t.astimezone(se.HELSINKI)
        temp = 3 - 12 * np.cos(2 * np.pi * (local.timetuple().tm_yday - 15) / 365) + rng.normal(0, 3)
        later = h >= 24 * 365
        cons = 9000 + 150 * max(15 - temp, 0) + 500 * np.sin(np.pi * local.hour / 24) + rng.normal(0, 80) \
            + (100 if later else 0) + (120 if later and 17 <= local.hour <= 21 else 0)
        rows.append({"hour_start": t, "day_fi": local.date(), "hour_fi": local.hour, "consumption_mw": cons, "temp_c": temp})
    df = se.panel(rows)
    df["later"] = (np.arange(len(df)) >= 24 * 365).astype(int)
    f = ev.growth_by_hour(df, df["consumption_mw"])
    g = np.array(f["growth"])
    assert g[17:22].mean() == pytest.approx(220, abs=25) and g[0:6].mean() == pytest.approx(100, abs=25)
    c = ev.contrast(f)
    assert c["ci_low"] < -120 < c["ci_high"]
    assert ev.mean_growth(f)["estimate"] == pytest.approx(100 + 120 * 5 / 24, abs=20)


@pytest.mark.regression
def test_the_panel_mixes_minute_and_quarter_data(db):
    from fingrid_catalog import ensure_catalog

    ensure_catalog(db)
    t0 = datetime(2031, 2, 1, tzinfo=timezone.utc)
    obs = [(124, t0 + i * timedelta(minutes=15), t0 + (i + 1) * timedelta(minutes=15), 9000 + 100 * i) for i in range(4)]
    obs += [(371, t0 + i * timedelta(minutes=1), t0 + (i + 1) * timedelta(minutes=1), 300.0) for i in range(50)]
    obs += [(c, t0 + i * timedelta(minutes=3), t0 + (i + 1) * timedelta(minutes=3), -5.0)
            for c in (178, 182, 196, 185) for i in range(20)]
    with db.cursor() as cur:
        cur.executemany("INSERT INTO fingrid_observation (dataset_id, start_time, end_time, value) VALUES (%s, %s, %s, %s)", obs)
        with open(os.path.join(ROOT, "sql", "analysis", "31_consumption_boilers_hourly.sql"), encoding="utf-8") as fh:
            cur.execute(fh.read(), {"start": t0, "end": t0 + timedelta(hours=1)})
            rows = cur.fetchall()
    db.rollback()
    assert len(rows) == 1
    _, day, hour, cons, boilers, temp = rows[0]
    assert cons == pytest.approx(9150) and boilers == pytest.approx(300) and temp == pytest.approx(-5)
    assert hour == 2 and day == date(2031, 2, 1)
