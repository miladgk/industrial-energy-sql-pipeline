"""
strike_effect.py
~~~~~~~~~~~~~~~~
How much electricity did Finland not use during the 2024 political strikes?
And does consumption that the weather cannot explain follow industrial output?

Event study with a counterfactual. A gradient-boosted model learns hourly
consumption (sql/analysis/28) from what the strikes did not change: measured
temperature (now, and its 24 h and 72 h means), the Finnish calendar (hour,
weekday, holidays, eves, bridge days, the Christmas period, July, the sun's
elevation, the time of year) and a slow time trend. It is trained on every
hour outside the strike periods (and BUFFER_DAYS around them), then asked what
the strike days would have used. The effect is what was used minus that.

Is the effect more than the model's ordinary error? A placebo test: the same
procedure, refitted each time, on N_PLACEBO periods of the same length and
starting weekday in the heating season of other years and months, with no
strike. The p-value is the share of placebo effects at least as large (in
absolute size) as the strike's; the 90 % band is their 5th-95th percentile.

Monthly link to industry. A second model without the time trend (weather and
calendar only) leaves, month by month, the consumption the weather and the
calendar do not explain; it is set against Statistics Finland's seasonally
adjusted volume index of manufacturing output (StatFin 14mh). Both drift upward
over these years, and two drifting series correlate whether or not they are
linked, so trend_check() also correlates their month-to-month changes and fits
the index with a linear trend beside it: only a link that survives those counts.

The model only measures a gap; that the strike caused it rests on the timing
and on the placebo test, not on proof. Strikes also hit transport and services,
so the effect is the whole economy's, not industry's alone.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import finnish_calendar as cal

HELSINKI = ZoneInfo("Europe/Helsinki")
BUFFER_DAYS = 3
N_PLACEBO = 40
SEED = 0
PARAMS = dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
              l2_regularization=1.0, early_stopping=False, random_state=0)

EVENTS = [
    {"key": "industry_feb", "name": "Industrial Union stoppage", "start": date(2024, 2, 1), "end": date(2024, 2, 2),
     "what": "two-day stoppage across Finnish industry, about 60,000 workers",
     "source": "https://www.teollisuusliitto.fi/en/2024/01/extensive-political-strike/"},
    {"key": "political_feb", "name": "Wide political strikes", "start": date(2024, 2, 12), "end": date(2024, 2, 16),
     "what": "coordinated strikes across sectors, power plants on 14-16 February",
     "source": "https://www.jhl.fi/en/news/jhls-political-strike-is-expanding-around-finland-dramatic-decrease-in-commuter-traffic-train-traffic-will-stop-power-plants-will-be-shut-down-three-day-strike-within-early-childhood-educ/"},
    {"key": "ports_mar_apr", "name": "Ports and transport strike", "start": date(2024, 3, 11), "end": date(2024, 4, 7),
     "what": "ports and rail stopped; paper and pulp mills shut for lack of transport",
     "source": "https://www.sak.fi/?p=31419"},
]

TREND_FEATURES = ["hour_fi", "isodow", "holiday", "holiday_eve", "bridge_day", "christmas_period", "july",
                  "sun_elevation", "doy_sin", "doy_cos", "temp_c", "heating", "temp_24h", "temp_72h", "days"]
NO_TREND_FEATURES = [f for f in TREND_FEATURES if f != "days"]


def panel(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    df["hour_start"] = pd.to_datetime(df["hour_start"], utc=True)
    df["day_fi"] = pd.to_datetime(df["day_fi"]).dt.date
    for c in ("consumption_mw", "temp_c"):
        df[c] = pd.to_numeric(df[c]).astype(float)
    df = df.sort_values("hour_start").reset_index(drop=True)
    local = df["hour_start"].dt.tz_convert(HELSINKI)
    df["isodow"] = local.dt.dayofweek + 1
    days = {d: cal.day_features(d) for d in df["day_fi"].unique()}
    for k in ("holiday", "holiday_eve", "bridge_day", "christmas_period", "july"):
        df[k] = df["day_fi"].map(lambda d: days[d][k])
    df["sun_elevation"] = [cal.sun_elevation(t.to_pydatetime()) for t in df["hour_start"]]
    doy = local.dt.dayofyear
    df["doy_sin"], df["doy_cos"] = np.sin(2 * np.pi * doy / 365.25), np.cos(2 * np.pi * doy / 365.25)
    df["heating"] = np.maximum(15.0 - df["temp_c"], 0.0)
    temp = df.set_index("hour_start")["temp_c"]
    df["temp_24h"] = temp.rolling("24h").mean().to_numpy()
    df["temp_72h"] = temp.rolling("72h").mean().to_numpy()
    df["days"] = (df["hour_start"] - df["hour_start"].min()).dt.total_seconds() / 86400
    return df


def _mask(df: pd.DataFrame, ranges, buffer: int = 0) -> np.ndarray:
    m = np.zeros(len(df), bool)
    for start, end in ranges:
        m |= ((df["day_fi"] >= start - timedelta(days=buffer)) & (df["day_fi"] <= end + timedelta(days=buffer))).to_numpy()
    return m


def fit_predict(df: pd.DataFrame, train: np.ndarray, features=TREND_FEATURES) -> np.ndarray:
    from sklearn.ensemble import HistGradientBoostingRegressor

    reg = HistGradientBoostingRegressor(**PARAMS).fit(df.loc[train, features], df.loc[train, "consumption_mw"])
    return reg.predict(df[features])


def gap(df: pd.DataFrame, start: date, end: date, exclude) -> dict:
    """Actual minus counterfactual over [start, end], with the model trained outside *exclude* (+ buffer)."""
    pred = fit_predict(df, ~_mask(df, exclude, BUFFER_DAYS))
    period = _mask(df, [(start, end)])
    diff = df.loc[period, "consumption_mw"].to_numpy() - pred[period]
    return {"mean_mw": float(diff.mean()), "gwh": float(diff.sum() / 1000), "hours": int(period.sum()),
            "share": float(diff.sum() / pred[period].sum()), "pred": pred, "period": period}


def placebo_starts(df: pd.DataFrame, event: dict, n: int = N_PLACEBO, seed: int = SEED) -> list[date]:
    """Starts of placebo periods: same length and starting weekday, October-April, data complete,
    clear of every event and its buffer."""
    length = (event["end"] - event["start"]).days
    blocked = _mask(df, [(e["start"], e["end"]) for e in EVENTS], BUFFER_DAYS + length + 1)
    have = df.groupby("day_fi").size()
    full = {d for d, k in have.items() if k >= 23}
    candidates = sorted({d for d, b in zip(df["day_fi"], blocked)
                         if not b and d.month in (10, 11, 12, 1, 2, 3, 4) and d.weekday() == event["start"].weekday()
                         and all(d + timedelta(days=i) in full for i in range(length + 1))})
    rng = np.random.default_rng(seed)
    return sorted(rng.choice(candidates, size=min(n, len(candidates)), replace=False).tolist())


def event_study(df: pd.DataFrame, event: dict, n_placebo: int = N_PLACEBO) -> dict:
    events = [(e["start"], e["end"]) for e in EVENTS]
    res = gap(df, event["start"], event["end"], events)
    period = res.pop("period")
    pred = res.pop("pred")
    days = (df.loc[period, ["day_fi", "consumption_mw"]].assign(pred=pred[period])
            .groupby("day_fi").agg(actual=("consumption_mw", "mean"), counterfactual=("pred", "mean")))
    length = (event["end"] - event["start"]).days
    placebos = []
    for s in placebo_starts(df, event, n_placebo):
        p = gap(df, s, s + timedelta(days=length), events + [(s, s + timedelta(days=length))])
        placebos.append(p["mean_mw"])
    placebos = np.array(placebos)
    return {**res, "daily": [{"day": str(d), "actual_mw": float(r.actual), "counterfactual_mw": float(r.counterfactual)}
                             for d, r in days.iterrows()],
            "placebo_n": len(placebos),
            "placebo_band_mw": [float(np.percentile(placebos, 5)), float(np.percentile(placebos, 95))] if len(placebos) else None,
            "placebo_p": float((np.abs(placebos) >= abs(res["mean_mw"])).mean()) if len(placebos) else None}


def monthly_residual(df: pd.DataFrame) -> pd.DataFrame:
    """Mean consumption the weather and calendar do not explain, per month (MW), from a model without trend."""
    pred = fit_predict(df, np.ones(len(df), bool), NO_TREND_FEATURES)
    month = pd.to_datetime(df["day_fi"]).dt.strftime("%Y-%m")
    out = pd.DataFrame({"month": month, "resid": df["consumption_mw"] - pred, "n": 1})
    return out.groupby("month").agg(resid_mw=("resid", "mean"), hours=("n", "sum")).reset_index()


def trend_check(x, y) -> dict:
    """Does y follow x beyond a shared trend? Correlation of levels, of month-to-month changes,
    and the slope of x in y ~ 1 + t + x with its t-statistic (plain OLS: few points)."""
    x, y = np.asarray(x, float), np.asarray(y, float)
    t = np.arange(len(x), dtype=float)
    X = np.column_stack([np.ones_like(t), t, x])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    se = math.sqrt(resid @ resid / (len(x) - 3) * np.linalg.inv(X.T @ X)[2, 2])
    return {"r_levels": float(np.corrcoef(x, y)[0, 1]), "r_changes": float(np.corrcoef(np.diff(x), np.diff(y))[0, 1]),
            "slope_with_trend": float(beta[2]), "slope_se": float(se), "slope_t": float(beta[2] / se), "n": len(x)}
