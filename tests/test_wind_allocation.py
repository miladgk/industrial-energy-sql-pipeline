"""
test_wind_allocation.py: the "where does an extra MW of wind go?" model
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REGRESSION tests on synthetic data with a known answer (no database):
  - the fixed-effects regression recovers the shares that generated the data
  - the shares of +1 MW add up to 1, as Fingrid's definition of consumption demands
  - Newey-West intervals are wider than plain OLS ones when errors are autocorrelated

INTEGRATION test on the warehouse (skipped until 191, 194 and 398 are synced):
  - sql/analysis/24_wind_allocation_panel.sql balances every hour exactly, and
    the measured net export (194) agrees with consumption - production
"""

import os
import sys

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import wind_allocation as wa  # noqa: E402

TRUE = {"net_import_mw": -0.5, "hydro_mw": -0.15, "other_mw": -0.15}     # consumption therefore +0.2


def _synthetic(hours=24 * 120, seed=7, rho=0.0):
    """An hourly panel whose parts react to wind exactly as TRUE says (plus noise)."""
    rng = np.random.default_rng(seed)
    t = np.arange(hours)
    wind = 3000 + 2000 * np.sin(t / 37.0) + rng.normal(0, 600, hours)
    nuclear = 4000 + rng.normal(0, 300, hours)
    temp = 5 + 10 * np.sin(t / 500.0) + rng.normal(0, 2, hours)

    def noise():
        e = np.zeros(hours)
        shocks = rng.normal(0, 150, hours)
        for i in range(hours):
            e[i] = (rho * e[i - 1] if i else 0.0) + shocks[i]
        return e
    heating = np.maximum(wa.HEATING_BALANCE_C - temp, 0)
    parts = {k: 2000 + b * wind - 0.3 * nuclear + 40 * heating + noise() for k, b in TRUE.items()}
    consumption = wind + nuclear + sum(parts.values())
    rows = []
    for i in range(hours):
        rows.append({"hour_fi": int(t[i] % 24), "isodow_fi": int(t[i] // 24 % 7 + 1), "month_fi": int(t[i] // (24 * 30) % 12 + 1),
                     "wind_mw": wind[i], "nuclear_mw": nuclear[i], "temp_c": temp[i], "consumption_mw": consumption[i],
                     **{k: v[i] for k, v in parts.items()}})
    return rows


@pytest.mark.regression
def test_regression_recovers_the_shares_that_generated_the_data():
    fitted = wa.fit(_synthetic())
    for response, beta in TRUE.items():
        c = fitted["responses"][response]["wind_mw"]
        assert c["coef"] == pytest.approx(beta, abs=0.02), response
        assert c["ci_low"] < beta < c["ci_high"], response
    split = wa.split(fitted, "wind_mw")
    assert split["consumption_rest"] == pytest.approx(0.2, abs=0.03)


@pytest.mark.regression
def test_shares_add_up_to_one_because_of_the_identity():
    split = wa.split(wa.fit(_synthetic(seed=3)), "wind_mw")
    assert split["consumption_rest"] == pytest.approx(split["consumption_direct"], abs=1e-6)


@pytest.mark.regression
def test_newey_west_widens_intervals_when_errors_are_autocorrelated():
    rows = _synthetic(rho=0.9, seed=11)
    X, _ = wa.design(rows)
    y = np.array([r["net_import_mw"] for r in rows])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    ols_se = np.sqrt(np.diag(np.linalg.inv(X.T @ X)) * resid.var())[1]
    hac_se = np.sqrt(np.diag(wa.newey_west(X, resid)))[1]
    assert hac_se > 1.5 * ols_se


@pytest.mark.integration
def test_hourly_panel_balances_every_hour(db):
    from analysis_window import default_window

    with open(os.path.join(ROOT, "sql", "analysis", "24_wind_allocation_panel.sql"), encoding="utf-8") as fh:
        sql = fh.read()
    with db.cursor() as cur:
        cur.execute(sql, default_window())
        cols = [c[0] for c in cur.description]
        rows = [dict(zip(cols, r)) for r in cur.fetchall()]
    db.rollback()
    if len(rows) < 24 * 30:
        pytest.skip("hydro (191), net export (194) or battery (398) not synced yet")
    for r in rows:
        parts = r["wind_mw"] + r["nuclear_mw"] + r["hydro_mw"] + r["other_mw"] + r["net_import_mw"]
        assert parts == pytest.approx(r["consumption_mw"], abs=1e-6)
    measured = [(r["net_import_mw"], r["net_import_measured_mw"]) for r in rows if r["net_import_measured_mw"] is not None]
    a, b = np.array(measured, dtype=float).T
    assert np.corrcoef(a, b)[0, 1] > 0.99
