"""
hydro_flex.py
~~~~~~~~~~~~~
Does Finnish hydropower make more room for wind when its reservoirs are full?

The wind chapter (src/wind_allocation.py) finds that only about a tenth of an
extra MW of wind is absorbed by Finnish hydro. Hydro plants can only hold water
back if there is room to store it and they must release it if too much is coming
in, so the share should depend on the state of the water. This module lets it:

    part = b_wind * wind + b_ws * wind * storage + b_wi * wind * inflow
           + storage + inflow + nuclear + heating degrees
           + hour-of-day, weekday, month and year fixed effects

on the hourly balance panel (sql/analysis/24) joined with the water state of the
day before (sql/analysis/27: reservoir levels and the unregulated Tornionjoki's
discharge, each against its 2000-2022 norm for the date). The day before is used
because today's levels are partly the result of today's hydro decisions.

The share of +1 MW of wind that a part absorbs at storage s (inflow at its mean)
is -(b_wind + b_ws * s); its 95 % interval comes from the Newey-West covariance
of the two coefficients. As a check that does not assume a straight line, the
plain wind regression is also fitted separately in the driest, middle and
fullest third of days.

Associations, not proven causes: the water state also moves with things the
model does not see (Swedish hydro, prices).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import numpy as np

import wind_allocation as wa

PARTS = ("hydro_mw", "net_import_mw", "other_mw", "consumption_mw")
STATES = ("storage_z", "inflow_z")
Z95 = wa.Z95
HELSINKI = ZoneInfo("Europe/Helsinki")


def _as_date(d):
    return date.fromisoformat(d[:10]) if isinstance(d, str) else d


def join_state(panel_rows: list[dict], state_rows: list[dict]) -> list[dict]:
    """Each hour gets the water state of the previous Finnish day (and its Finnish year);
    hours without a complete state are dropped."""
    state = {_as_date(r["day"]): r for r in state_rows}
    out = []
    for r in panel_rows:
        t = r["hour_start"]
        t = datetime.fromisoformat(t.replace("Z", "+00:00")) if isinstance(t, str) else t
        local = t.astimezone(HELSINKI)
        s = state.get(local.date() - timedelta(days=1))
        if s is None or s["storage_z"] is None or s["inflow_z"] is None:
            continue
        out.append({**r, "year_fi": local.year, "storage_z": float(s["storage_z"]), "inflow_z": float(s["inflow_z"])})
    return out


def design(rows: list[dict]) -> tuple[np.ndarray, list[str]]:
    X, names = wa.design(rows)
    wind = X[:, names.index("wind_mw")]
    cols, extra = [], []
    for k in STATES:
        v = np.array([r[k] for r in rows], dtype=float)
        cols += [v, wind * v]
        extra += [k, f"wind_x_{k}"]
    years = np.array([r["year_fi"] for r in rows])
    for y in sorted(set(years.tolist()))[1:]:
        cols.append((years == y).astype(float))
        extra.append(f"year_{y}")
    return np.column_stack([X] + cols), names + extra


def fit(rows: list[dict], parts=PARTS) -> dict:
    """Coefficients and HAC covariances of wind and its interactions for every part."""
    X, names = design(rows)
    iw, iws, iwi = (names.index(n) for n in ("wind_mw", "wind_x_storage_z", "wind_x_inflow_z"))
    out = {"hours": len(rows), "parts": {}}
    for part in parts:
        y = np.array([r[part] for r in rows], dtype=float)
        keep = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
        Xk, yk = X[keep], y[keep]
        beta, *_ = np.linalg.lstsq(Xk, yk, rcond=None)
        V = wa.newey_west(Xk, yk - Xk @ beta)
        idx = [iw, iws, iwi]
        out["parts"][part] = {"beta": beta[idx].tolist(), "cov": V[np.ix_(idx, idx)].tolist(), "hours": int(keep.sum())}
    return out


def share_at(fitted: dict, part: str, storage: float, inflow: float = 0.0) -> dict:
    """Share of +1 MW of wind absorbed by *part* (pushed out; for consumption: added) at a water state."""
    p = fitted["parts"][part]
    g = np.array([1.0, storage, inflow])
    sign = 1.0 if part == "consumption_mw" else -1.0
    est = sign * float(g @ np.array(p["beta"]))
    se = float(np.sqrt(g @ np.array(p["cov"]) @ g))
    return {"share": est, "ci_low": est - Z95 * se, "ci_high": est + Z95 * se}


def interaction(fitted: dict, part: str, which: str = "storage_z") -> dict:
    """How much the share moves per standard deviation of the state, with its 95 % interval and p-value."""
    import math

    p = fitted["parts"][part]
    i = 1 if which == "storage_z" else 2
    sign = 1.0 if part == "consumption_mw" else -1.0
    b, se = sign * p["beta"][i], math.sqrt(p["cov"][i][i])
    return {"per_sd": b, "ci_low": b - Z95 * se, "ci_high": b + Z95 * se,
            "p_value": math.erfc(abs(b / se) / math.sqrt(2)) if se > 0 else 1.0}


def by_tercile(rows: list[dict], key: str = "storage_z") -> list[dict]:
    """The plain wind regression (src/wind_allocation.py) in each third of days by *key*."""
    vals = np.array([r[key] for r in rows])
    cuts = np.quantile(vals, [1 / 3, 2 / 3])
    out = []
    for i, (lo, hi) in enumerate(((-np.inf, cuts[0]), (cuts[0], cuts[1]), (cuts[1], np.inf))):
        part = [r for r, v in zip(rows, vals) if lo < v <= hi]
        f = wa.fit(part, PARTS)
        out.append({"tercile": i + 1, "hours": f["hours"], "state_mean": float(np.mean([r[key] for r in part])),
                    "shares": {k: (1.0 if k == "consumption_mw" else -1.0) * f["responses"][k]["wind_mw"]["coef"]
                               for k in PARTS},
                    "hydro_ci": sorted((-f["responses"]["hydro_mw"]["wind_mw"]["ci_high"],
                                        -f["responses"]["hydro_mw"]["wind_mw"]["ci_low"]))})
    return out
