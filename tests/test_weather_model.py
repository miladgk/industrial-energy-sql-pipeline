"""
test_weather_model.py: public weather vs Fingrid (src/weather_model.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REGRESSION tests on a synthetic year with a known answer (no database):
  - a forecast never depends on actuals from after its training cut-off
  - with nothing to learn, the corrected forecast stays at Fingrid's level
  - when wind truly follows the weather, the model learns it and beats a noisy forecast
  - the Diebold-Mariano test tells a real difference from none

INTEGRATION test on the warehouse (skipped until the Open-Meteo archive is filled):
  - sql/analysis/26_weather_model_panel.sql gives one complete weather row per hour
"""

import os
import sys
from datetime import datetime, timedelta, timezone

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import weather_model as wm  # noqa: E402

START = datetime(2025, 1, 1, tzinfo=timezone.utc)


def _rows(days=240, seed=1, fingrid_noise=900.0):
    """Hourly rows shaped like the SQL panel. Wind output follows the farm-area wind speeds;
    Fingrid's forecasts are the truth plus noise."""
    rng = np.random.default_rng(seed)
    n = days * 24
    t = np.arange(n)
    speed = np.clip(7 + 3 * np.sin(t / 29.0) + 2 * np.sin(t / 7.3) + rng.normal(0, 1, n), 0, None)
    cap = 8000.0
    wind = cap * np.clip(speed, 0, 13) ** 3 / 13 ** 3 * 0.9
    temp = 5 + 10 * np.sin(2 * np.pi * t / (24 * 365)) + rng.normal(0, 2, n)
    cons = 9000 + 120 * np.maximum(15 - temp, 0) + 500 * np.sin(2 * np.pi * (t % 24) / 24) + rng.normal(0, 150, n)
    rows = []
    for i in range(n):
        r = {"hour_start": START + timedelta(hours=int(i)), "wind_mw": wind[i], "consumption_mw": cons[i],
             "fingrid_wind_mw": max(wind[i] + rng.normal(0, fingrid_noise), 0.0),
             "fingrid_consumption_mw": cons[i] + rng.normal(0, 300), "wind_capacity_mw": cap,
             "temp_c": temp[i], "temp_helsinki": temp[i], "temp_oulu": temp[i] - 4, "temp_vaasa": temp[i] - 1}
        for p in wm.WIND_PLACES:
            r[f"wind_{p}"] = speed[i] + rng.normal(0, 1.5)
        for p in wm.FARMS:
            r[f"farm_{p}"] = speed[i] + rng.normal(0, 0.3)
        rows.append(r)
    return rows


@pytest.fixture(scope="module")
def panel():
    return wm.panel(_rows())


@pytest.mark.regression
def test_forecast_ignores_actuals_after_its_cutoff(panel):
    day = sorted(panel["day"].unique())[-10]
    until = day - timedelta(days=2)
    before = wm.fit_predict(panel, "wind", "weather", until, [day])
    spoiled = panel.copy()
    late = spoiled["day"] > until
    spoiled.loc[late, ["wind_mw", "wind_cf", "consumption_mw"]] *= 10
    after = wm.fit_predict(spoiled, "wind", "weather", until, [day])
    assert len(before) >= 23
    np.testing.assert_allclose(before.to_numpy(), after.to_numpy())


@pytest.mark.regression
def test_learns_the_weather_and_beats_a_noisy_forecast(panel):
    bt = wm.backtest(panel, "wind", days=42, refit=14)
    assert bt["days"] == 42
    assert bt["mae_mw"]["weather"] < 0.5 * bt["mae_mw"]["fingrid"]
    assert bt["skill_vs_fingrid"]["weather"] > 0.5
    assert bt["diebold_mariano"]["weather"]["p_value"] < 0.01


@pytest.mark.regression
def test_correction_stays_at_fingrid_when_there_is_nothing_to_learn():
    rows = _rows(seed=4)
    rng = np.random.default_rng(9)
    for r in rows:                                   # actual consumption = Fingrid + pure noise
        r["consumption_mw"] = r["fingrid_consumption_mw"] + rng.normal(0, 300)
    bt = wm.backtest(wm.panel(rows), "consumption", days=42, refit=14)
    assert abs(bt["skill_vs_fingrid"]["weather_fingrid"]) < 0.03
    assert bt["diebold_mariano"]["weather_fingrid"]["p_value"] > 0.01


@pytest.mark.regression
def test_diebold_mariano_separates_real_differences_from_none():
    rng = np.random.default_rng(3)
    a = rng.gamma(2.0, 100.0, 200)
    same = wm.diebold_mariano(a, a)
    assert same["statistic"] == 0 and same["p_value"] == 1.0
    better = wm.diebold_mariano(a, a * 0.8)
    assert better["mean_difference"] > 0 and better["p_value"] < 0.001


@pytest.mark.integration
def test_weather_panel_has_complete_hours(db):
    from analysis_window import default_window

    with open(os.path.join(ROOT, "sql", "analysis", "26_weather_model_panel.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    with db.cursor() as cur:
        cur.execute(sql, default_window(days=60))
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    db.rollback()
    if len(rows) < 24 * 30:
        pytest.skip("the Open-Meteo archive (src/openmeteo_forecast.py) is not filled yet")
    weather = [c for c in cols if c.startswith(("temp_", "wind_", "farm_")) and c != "wind_mw" and c != "wind_capacity_mw"]
    assert all(r[c] is not None for r in rows for c in weather)
    hours = [r["hour_start"] for r in rows]
    assert len(hours) == len(set(hours))
