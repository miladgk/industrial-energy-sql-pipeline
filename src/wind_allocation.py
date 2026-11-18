"""
wind_allocation.py
~~~~~~~~~~~~~~~~~~
Where does an extra MW of wind go? And an extra MW of nuclear?

Fingrid defines consumption as production + import - export, so every hour

    consumption = wind + nuclear + hydro + other + net_import

(sql/analysis/24_wind_allocation_panel.sql builds that hourly table). Each
part except wind and nuclear is regressed on

    wind, nuclear, heating = max(15 C - temperature, 0)
    + fixed effects for the Finnish hour of day, weekday and month

and the wind coefficients of net_import, hydro and other say how much of an
extra MW of wind pushes out imports, hydro and other production. Because of
the identity, 1 - (those three) is the extra consumption that goes with it;
it is also estimated directly, and the two agree to rounding.

Hourly power data is autocorrelated, so the 95 % intervals use Newey-West
(HAC) standard errors with a Bartlett kernel over 24 hourly lags; plain OLS
intervals would be several times too narrow.

breakdown() then asks which border the lower imports come from and which
plants make room: the same regression on each border's measured import and on
each kind of plant, fitted on the hours where all of them are known. OLS is
linear in the response, so the border shares add up to the import share and
the plant shares to the other-production share of those same hours exactly.

These are associations after controlling for weather and the calendar, not
proven causal effects: wind is close to exogenous (the weather decides it),
nuclear output less so (outages are planned around demand and prices).
"""

from __future__ import annotations

import numpy as np

HEATING_BALANCE_C = 15.0        # from the weekday fit in sql/analysis/23_temperature_sensitivity.sql
HAC_LAGS = 24
DRIVERS = ("wind_mw", "nuclear_mw")
RESPONSES = ("net_import_mw", "hydro_mw", "other_mw", "consumption_mw")
BORDERS = ("import_sweden_north_mw", "import_sweden_central_mw", "import_estonia_mw", "import_norway_mw",
           "import_unmeasured_mw")
PLANTS = ("chp_district_heating_mw", "chp_industrial_mw", "reserve_and_small_mw", "other_rest_mw")
SEASONS = {"winter": (12, 1, 2), "spring": (3, 4, 5), "summer": (6, 7, 8), "autumn": (9, 10, 11)}
Z95 = 1.959964


def _column(rows: list[dict], key: str) -> np.ndarray:
    return np.array([np.nan if r[key] is None else float(r[key]) for r in rows])


def _dummies(values: np.ndarray) -> list[np.ndarray]:
    """One column per level except the first (the constant absorbs it)."""
    levels = sorted(set(values.tolist()))
    return [(values == v).astype(float) for v in levels[1:]]


def design(rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    """Regressors: constant, wind, nuclear, heating, then hour/weekday/month dummies."""
    heating = np.maximum(HEATING_BALANCE_C - _column(rows, "temp_c"), 0.0)
    cols = [np.ones(len(rows)), _column(rows, "wind_mw"), _column(rows, "nuclear_mw"), heating]
    names = ["const", "wind_mw", "nuclear_mw", "heating_degc"]
    for key in ("hour_fi", "isodow_fi", "month_fi"):
        dummies = _dummies(np.array([r[key] for r in rows]))
        cols += dummies
        names += [f"{key}_{i}" for i in range(len(dummies))]
    return np.column_stack(cols), names


def newey_west(X: np.ndarray, resid: np.ndarray, lags: int = HAC_LAGS) -> np.ndarray:
    """HAC covariance of the OLS coefficients (Bartlett kernel)."""
    Z = X * resid[:, None]
    S = Z.T @ Z
    for lag in range(1, lags + 1):
        w = 1.0 - lag / (lags + 1.0)
        G = Z[lag:].T @ Z[:-lag]
        S += w * (G + G.T)
    XtX_inv = np.linalg.inv(X.T @ X)
    return XtX_inv @ S @ XtX_inv


def fit(rows: list[dict], responses=RESPONSES) -> dict:
    """OLS with HAC intervals for each response; rows with any missing value are dropped."""
    X, names = design(rows)
    out = {"hours": 0, "responses": {}}
    for response in responses:
        y = _column(rows, response)
        keep = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
        Xk, yk = X[keep], y[keep]
        beta, *_ = np.linalg.lstsq(Xk, yk, rcond=None)
        resid = yk - Xk @ beta
        se = np.sqrt(np.diag(newey_west(Xk, resid)))
        r2 = 1.0 - resid.var() / yk.var()
        coefs = {}
        for driver in DRIVERS:
            i = names.index(driver)
            coefs[driver] = {"coef": float(beta[i]), "se": float(se[i]),
                             "ci_low": float(beta[i] - Z95 * se[i]), "ci_high": float(beta[i] + Z95 * se[i])}
        out["responses"][response] = {"r2": float(r2), "hours": int(keep.sum()), **coefs}
        out["hours"] = max(out["hours"], int(keep.sum()))
    return out


def split(fitted: dict, driver: str) -> dict:
    """Shares of +1 MW of *driver*: pushed out of imports, hydro and other production, and the rest.
    The rest equals the directly estimated consumption response up to rounding (the identity)."""
    r = fitted["responses"]
    pushed = {k: -r[k][driver]["coef"] for k in ("net_import_mw", "hydro_mw", "other_mw")}
    return {**pushed, "consumption_rest": 1.0 - sum(pushed.values()),
            "consumption_direct": r["consumption_mw"][driver]["coef"]}


def by_season(rows: list[dict]) -> dict:
    out = {}
    for season, months in SEASONS.items():
        part = [r for r in rows if r["month_fi"] in months]
        if len(part) >= 24 * 30:
            out[season] = fit(part)
    return out


def breakdown(rows: list[dict], min_hours: int = 24 * 300) -> dict | None:
    """Wind and nuclear coefficients of every border and plant column, plus their parents
    (net_import_mw, other_mw), on the hours where all of them are present."""
    part = [r for r in rows if all(r.get(k) is not None for k in BORDERS + PLANTS)]
    if len(part) < min_hours:
        return None
    return fit(part, ("net_import_mw", "other_mw") + BORDERS + PLANTS)
