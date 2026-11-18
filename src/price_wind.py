"""
price_wind.py
~~~~~~~~~~~~~
Does wind make electricity cheaper in Finland, and when does it stop helping?

The day-ahead price is set at noon the day before, from bids that know the
weather forecast. So the hourly Finnish price (sql/analysis/29, ENTSO-E) is
regressed on what the auction could know: Fingrid's day-ahead wind and
consumption forecasts, nuclear production (mostly planned outages), heating
degrees, the water in the hydro reservoirs the day before (src/hydro_flex.py:
storage and the unregulated inflow, each against its 2000-2022 norm), and
wind x storage, with hour-of-day, weekday, month and year fixed effects:

    price = b_w * wind_gw + b_ws * wind_gw * storage + b_c * consumption_gw
            + nuclear_gw + heating + storage + inflow + fixed effects

-b_w - b_ws * s is how much one more GW of forecast wind takes off the price at
storage s. Intervals are Newey-West over 24 hours, as in src/wind_allocation.py.
Prices have spikes (1,896 EUR/MWh in January 2024) that pull an OLS line, so
the same fit is repeated with prices clipped to their 1st-99th percentile, and
with measured wind instead of the forecast.

Two things need no regression at all, so they come straight from the hours:
  - by_wind_bin: the price, the share of hours at or below zero, and how often
    Finland's price differs from northern Sweden's (SE1) and Estonia's, at each
    level of forecast wind. A separate price means a border was full: the
    cheap wind could not leave (or the cheap import could not come in).
  - capture_by_year: what wind earned per MWh (the price weighted by measured
    wind output) against the average price over all hours. Wind blows together
    across Finland, so it sells most when prices are lowest.

Associations: wind is set by the weather and close to exogenous, but windy
hours also differ in ways the model may not see (for example Swedish wind,
which blows on the same days).
"""

from __future__ import annotations

import math

import numpy as np

import hydro_flex as hf
import wind_allocation as wa

Z95 = wa.Z95
HEATING_BALANCE_C = wa.HEATING_BALANCE_C
SAME_PRICE = 0.005                         # EUR/MWh: half a cent (prices have two decimals)
WIND_BINS_GW = (0, 1, 2, 3, 4, 5, 6)       # last bin open-ended


def _col(rows, key, scale=1.0):
    return np.array([np.nan if r.get(key) is None else float(r[key]) / scale for r in rows])


def design(rows: list[dict], wind_key: str = "wind_fc_mw") -> tuple[np.ndarray, list[str]]:
    wind = _col(rows, wind_key, 1000)
    storage, inflow = _col(rows, "storage_z"), _col(rows, "inflow_z")
    cols = [np.ones(len(rows)), wind, wind * storage, _col(rows, "consumption_fc_mw", 1000),
            _col(rows, "nuclear_mw", 1000), np.maximum(HEATING_BALANCE_C - _col(rows, "temp_c"), 0.0),
            storage, inflow]
    names = ["const", "wind_gw", "wind_x_storage", "consumption_gw", "nuclear_gw", "heating_degc",
             "storage_z", "inflow_z"]
    for key in ("hour_fi", "isodow_fi", "month_fi", "year_fi"):
        d = wa._dummies(np.array([r[key] for r in rows]))
        cols += d
        names += [f"{key}_{i}" for i in range(len(d))]
    return np.column_stack(cols), names


def fit(rows: list[dict], wind_key: str = "wind_fc_mw", clip: tuple[float, float] | None = None) -> dict:
    """OLS of the Finnish price with HAC covariance of the wind and wind x storage coefficients."""
    X, names = design(rows, wind_key)
    y = _col(rows, "price_fi")
    keep = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    X, y = X[keep], y[keep]
    if clip:
        y = np.clip(y, *np.percentile(y, clip))
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    V = wa.newey_west(X, resid)
    idx = [names.index("wind_gw"), names.index("wind_x_storage"), names.index("consumption_gw")]
    return {"hours": int(keep.sum()), "r2": float(1 - resid.var() / y.var()),
            "beta": beta[idx].tolist(), "cov": V[np.ix_(idx, idx)].tolist()}


def per_gw(fitted: dict, storage: float = 0.0) -> dict:
    """EUR/MWh that one more GW of wind takes off the price at a storage level (positive = cheaper)."""
    g = np.array([1.0, storage, 0.0])
    est = -float(g @ np.array(fitted["beta"]))
    se = math.sqrt(float(g @ np.array(fitted["cov"]) @ g))
    return {"eur_per_gw": est, "ci_low": est - Z95 * se, "ci_high": est + Z95 * se}


def storage_interaction(fitted: dict) -> dict:
    """How the per-GW effect changes per unit of storage z, with its p-value."""
    b, se = -fitted["beta"][1], math.sqrt(fitted["cov"][1][1])
    return {"per_unit": b, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se,
            "p_value": math.erfc(abs(b / se) / math.sqrt(2)) if se > 0 else 1.0}


def consumption_effect(fitted: dict) -> dict:
    """EUR/MWh that one more GW of forecast consumption adds, for scale."""
    b, se = fitted["beta"][2], math.sqrt(fitted["cov"][2][2])
    return {"eur_per_gw": b, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se}


def by_wind_bin(rows: list[dict], wind_key: str = "wind_fc_mw") -> list[dict]:
    """Price and coupling at each level of forecast wind (GW bins)."""
    wind = _col(rows, wind_key, 1000)
    fi, se1, ee = _col(rows, "price_fi"), _col(rows, "price_se1"), _col(rows, "price_ee")
    out = []
    edges = list(WIND_BINS_GW) + [np.inf]
    for lo, hi in zip(edges, edges[1:]):
        m = (wind >= lo) & (wind < hi) & ~np.isnan(fi)
        if m.sum() == 0:
            continue
        p = fi[m]
        below, above = p < se1[m] - SAME_PRICE, p > se1[m] + SAME_PRICE
        out.append({"gw_from": lo, "gw_to": None if hi == np.inf else hi, "hours": int(m.sum()),
                    "median": float(np.median(p)), "p25": float(np.percentile(p, 25)),
                    "p75": float(np.percentile(p, 75)), "mean": float(p.mean()),
                    "share_zero_or_below": float((p <= 0).mean()),
                    "share_below_se1": float(below.mean()),
                    "share_same_as_se1": float((~below & ~above).mean()),
                    "share_above_se1": float(above.mean()),
                    "share_same_as_ee": float((np.abs(p - ee[m]) <= SAME_PRICE).mean())})
    return out


def capture_by_year(rows: list[dict]) -> list[dict]:
    """Wind-weighted price (what an average wind MWh sold for) against the plain hourly mean, per Finnish year."""
    out = []
    years = sorted({r["year_fi"] for r in rows})
    for y in years:
        part = [r for r in rows if r["year_fi"] == y and r.get("wind_mw") is not None and r.get("price_fi") is not None]
        if len(part) < 24 * 60:
            continue
        p, w = _col(part, "price_fi"), _col(part, "wind_mw")
        avg, cap = float(p.mean()), float((p * w).sum() / w.sum())
        out.append({"year": y, "hours": len(part), "average": avg, "wind_captured": cap,
                    "ratio": cap / avg if avg else None})
    return out


def at_storage_percentiles(fitted: dict, state_rows: list[dict], qs=(10, 50, 90)) -> list[dict]:
    zs = np.array([float(r["storage_z"]) for r in state_rows if r.get("storage_z") is not None])
    return [{"percentile": q, "storage_z": float(np.percentile(zs, q)), **per_gw(fitted, float(np.percentile(zs, q)))}
            for q in qs]


join_state = hf.join_state
