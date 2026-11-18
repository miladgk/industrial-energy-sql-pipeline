"""
weather_model.py
~~~~~~~~~~~~~~~~
Can a model built on public weather forecasts and the calendar beat
Fingrid's own day-ahead forecasts of wind output and consumption?

Inputs per hour (sql/analysis/26_weather_model_panel.sql), all known when
Fingrid issues its forecast for day D at 12:00 Finnish time on D-1:

  weather     temperatures and 100 m wind speeds forecast 48 h earlier at
              eight towns and seven wind-farm areas (Open-Meteo,
              src/openmeteo_forecast.py)
  calendar    Finnish hour and weekday, holidays, eves, bridge days, the
              Christmas period, July, the sun's elevation
              (src/finnish_calendar.py)
  history     consumption at the same hour a week earlier and the mean of
              day D-2; wind capacity as it stood at the end of D-2

Two gradient-boosted tree models per variable (scikit-learn
HistGradientBoostingRegressor):

  weather            the inputs above only
  weather_fingrid    Fingrid's forecast plus a learned correction: a
                     heavily regularised model of Fingrid's error on the
                     same inputs (and Fingrid's forecast itself). With
                     nothing to learn it returns Fingrid's forecast, so it
                     asks whether the weather and the calendar still know
                     something Fingrid's forecast missed.

The tree settings were fixed before the published backtest; six settings of
the correction model were tried on it, and none beat Fingrid by more than
2 % (the published one is the most regularised).

Wind is modelled as a capacity factor (output / capacity) so that a growing
fleet does not look like a windier year.

Backtest (rolling origin): the last BACKTEST_DAYS days with actuals are
forecast one at a time with a model refitted every REFIT_DAYS days on
everything known two days before the first day it forecasts. Scores are
mean absolute errors next to Fingrid's; the Diebold-Mariano test (daily
loss differences, Newey-West variance) says whether a difference is more
than luck.
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd

import finnish_calendar as cal

HELSINKI = ZoneInfo("Europe/Helsinki")
BACKTEST_DAYS = 182
REFIT_DAYS = 7
MIN_TRAIN_DAYS = 120
DM_LAGS = 7
MODELS = ("weather", "weather_fingrid")
WIND_PLACES = ("vaasa", "kokkola", "pori", "raahe", "oulu", "helsinki")
FARMS = ("kristinestad", "kalajoki", "lestijarvi", "ii", "tornio", "kyyjarvi", "pyhajoki")
PARAMS = {
    "weather": dict(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=40,
                    l2_regularization=1.0, early_stopping=False, random_state=0),
    "weather_fingrid": dict(max_iter=100, learning_rate=0.02, max_depth=3, min_samples_leaf=400,
                            l2_regularization=10.0, early_stopping=False, random_state=0),
}


def panel(rows: list[dict]) -> pd.DataFrame:
    """The SQL rows with Finnish calendar columns, known-history columns and the capacity factor."""
    df = pd.DataFrame(rows)
    df["hour_start"] = pd.to_datetime(df["hour_start"], utc=True)
    for c in df.columns:
        if c != "hour_start":
            df[c] = pd.to_numeric(df[c], errors="coerce").astype(float)
    local = df["hour_start"].dt.tz_convert(HELSINKI)
    df["day"] = local.dt.date
    df["hour_fi"] = local.dt.hour
    df["isodow"] = local.dt.dayofweek + 1
    days = {d: cal.day_features(d) for d in df["day"].unique()}
    for k in ("holiday", "holiday_eve", "bridge_day", "christmas_period", "july"):
        df[k] = df["day"].map(lambda d: days[d][k])
    df["sun_elevation"] = [cal.sun_elevation(t.to_pydatetime()) for t in df["hour_start"]]
    df["heating"] = np.maximum(15.0 - df["temp_c"], 0.0)
    df["temp_day_mean"] = df.groupby("day")["temp_c"].transform("mean")
    speeds = df[[f"wind_{p}" for p in WIND_PLACES]]
    df["wind_mean"] = speeds.mean(axis=1)
    df["wind_spread"] = speeds.std(axis=1)
    farms = df[[f"farm_{p}" for p in FARMS]]
    df["farm_mean"] = farms.mean(axis=1)
    df["farm_cube"] = (farms.clip(0, 13) ** 3).mean(axis=1)    # turbine output flattens above ~13 m/s

    # History that was known at issue time (noon of D-1): days up to D-2.
    by_day = df.groupby("day")
    daily_cons = by_day["consumption_mw"].mean()
    last_cap = by_day["wind_capacity_mw"].last().ffill()
    df["cons_d2_mean"] = df["day"].map(lambda d: daily_cons.get(d - timedelta(days=2), np.nan))
    df["cap_known"] = df["day"].map(lambda d: last_cap.get(d - timedelta(days=2), np.nan))
    week = df.set_index("hour_start")["consumption_mw"]
    df["cons_week_ago"] = df["hour_start"].map(lambda t: week.get(t - pd.Timedelta(days=7), np.nan))
    df["wind_cf"] = df["wind_mw"] / df["cap_known"]
    df["fingrid_wind_cf"] = df["fingrid_wind_mw"] / df["cap_known"]
    return df


CALENDAR = ["hour_fi", "isodow", "holiday", "holiday_eve", "bridge_day", "christmas_period", "july", "sun_elevation"]
FEATURES = {
    "consumption": CALENDAR + ["temp_c", "temp_helsinki", "temp_oulu", "heating", "temp_day_mean",
                               "wind_helsinki", "cons_d2_mean", "cons_week_ago"],
    "wind": ["hour_fi", "sun_elevation", "temp_vaasa", "wind_mean", "wind_spread", "farm_mean", "farm_cube"]
            + [f"wind_{p}" for p in WIND_PLACES] + [f"farm_{p}" for p in FARMS],
}
TARGET = {"consumption": "consumption_mw", "wind": "wind_cf"}
FINGRID = {"consumption": "fingrid_consumption_mw", "wind": "fingrid_wind_cf"}


def features(variable: str, model: str) -> list[str]:
    return FEATURES[variable] + ([FINGRID[variable]] if model == "weather_fingrid" else [])


def _to_mw(variable: str, df: pd.DataFrame, pred: np.ndarray) -> np.ndarray:
    if variable == "wind":
        return np.clip(pred, 0, None) * df["cap_known"].to_numpy()
    return pred


def fit_predict(df: pd.DataFrame, variable: str, model: str, train_until: date, target_days) -> pd.Series:
    """Fit on hours of days <= train_until with a known target; predict the hours of target_days (MW)."""
    from sklearn.ensemble import HistGradientBoostingRegressor

    cols = features(variable, model)
    target, fingrid = TARGET[variable], FINGRID[variable]
    train = df[(df["day"] <= train_until) & df[target].notna() & df[fingrid].notna()]
    test = df[df["day"].isin(set(target_days)) & df[fingrid].notna()]
    if train["day"].nunique() < MIN_TRAIN_DAYS or test.empty:
        return pd.Series(dtype=float)
    if model == "weather_fingrid":            # learn Fingrid's error, add the correction to its forecast
        reg = HistGradientBoostingRegressor(**PARAMS[model]).fit(train[cols], train[target] - train[fingrid])
        pred = test[fingrid].to_numpy() + reg.predict(test[cols])
    else:
        pred = HistGradientBoostingRegressor(**PARAMS[model]).fit(train[cols], train[target]).predict(test[cols])
    return pd.Series(_to_mw(variable, test, pred), index=test.index)


def diebold_mariano(loss_a: np.ndarray, loss_b: np.ndarray, lags: int = DM_LAGS) -> dict:
    """DM test of equal mean loss on daily loss series; positive mean = b is better. Two-sided p-value."""
    d = np.asarray(loss_a) - np.asarray(loss_b)
    n = len(d)
    u = d - d.mean()
    var = u @ u / n
    for k in range(1, lags + 1):
        var += 2 * (1 - k / (lags + 1)) * (u[k:] @ u[:-k]) / n
    stat = d.mean() / math.sqrt(var / n) if var > 0 else 0.0
    p = math.erfc(abs(stat) / math.sqrt(2))
    return {"mean_difference": float(d.mean()), "statistic": float(stat), "p_value": float(p), "days": int(n)}


def backtest(df: pd.DataFrame, variable: str, days: int = BACKTEST_DAYS, refit: int = REFIT_DAYS) -> dict:
    """Rolling-origin replay of the last *days* days that have actuals and a Fingrid forecast."""
    target, fingrid_mw = (("consumption_mw", "fingrid_consumption_mw") if variable == "consumption"
                          else ("wind_mw", "fingrid_wind_mw"))
    known = df[df[target].notna() & df[fingrid_mw].notna() & df["cap_known"].notna()]
    complete = known.groupby("day").size()
    test_days = sorted(d for d, n in complete.items() if n >= 23)[-days:]
    preds = {m: pd.Series(dtype=float) for m in MODELS}
    for i in range(0, len(test_days), refit):
        block = test_days[i:i + refit]
        for m in MODELS:
            p = fit_predict(df, variable, m, block[0] - timedelta(days=2), block)
            preds[m] = pd.concat([preds[m], p])
    idx = preds[MODELS[0]].index
    for m in MODELS:
        idx = idx.intersection(preds[m].index)
    rows = df.loc[idx].copy()
    rows["actual"] = rows[target]
    rows["fingrid"] = rows[fingrid_mw]
    for m in MODELS:
        rows[m] = preds[m].loc[idx]
    errs = {k: (rows[k] - rows["actual"]).abs() for k in ("fingrid",) + MODELS}
    out = {"days": int(rows["day"].nunique()), "hours": int(len(rows)),
           "first_day": str(min(rows["day"])) if len(rows) else None,
           "last_day": str(max(rows["day"])) if len(rows) else None,
           "mae_mw": {k: float(e.mean()) for k, e in errs.items()},
           "rmse_mw": {k: float(np.sqrt(((rows[k] - rows["actual"]) ** 2).mean())) for k in errs},
           "bias_mw": {k: float((rows[k] - rows["actual"]).mean()) for k in errs}}
    out["skill_vs_fingrid"] = {m: 1 - out["mae_mw"][m] / out["mae_mw"]["fingrid"] for m in MODELS}
    daily = pd.DataFrame({k: e for k, e in errs.items()}).groupby(rows["day"]).mean()
    out["diebold_mariano"] = {m: diebold_mariano(daily["fingrid"].to_numpy(), daily[m].to_numpy()) for m in MODELS}
    month = pd.to_datetime(rows["day"]).dt.strftime("%Y-%m")
    by_month = pd.DataFrame({k: e for k, e in errs.items()}).groupby(month).mean()
    out["by_month"] = [{"month": mo, **{k: float(v) for k, v in r.items()}} for mo, r in by_month.iterrows()]
    out["rows"] = rows
    return out


def forecast_day(df: pd.DataFrame, variable: str, day: date) -> pd.DataFrame | None:
    """Both models' forecasts for every hour of *day*, trained on what was known two days before it."""
    fingrid_mw = "fingrid_consumption_mw" if variable == "consumption" else "fingrid_wind_mw"
    hours = df[(df["day"] == day) & df[fingrid_mw].notna() & df["cap_known"].notna()]
    if len(hours) < 23:
        return None
    out = hours[["hour_start", fingrid_mw]].rename(columns={fingrid_mw: "fingrid"}).copy()
    for m in MODELS:
        p = fit_predict(df, variable, m, day - timedelta(days=2), [day])
        if p.empty:
            return None
        out[m] = p
    return out


DAY_TYPES = ("holiday", "holiday_eve", "bridge_day", "christmas_period", "july")


def day_type(row) -> str:
    """The most specific calendar label of an hour, in DAY_TYPES order, else weekend / weekday."""
    for k in DAY_TYPES:
        if row[k] == 1:
            return k
    return "weekend" if row["isodow"] >= 6 else "weekday"


def errors_by_day_type(df: pd.DataFrame) -> list[dict]:
    """Fingrid's day-ahead consumption error by kind of day, over every hour with both values."""
    known = df[df["consumption_mw"].notna() & df["fingrid_consumption_mw"].notna()].copy()
    known["err"] = known["fingrid_consumption_mw"] - known["consumption_mw"]
    known["kind"] = known.apply(day_type, axis=1)
    out = []
    for kind in ("weekday", "weekend") + DAY_TYPES:
        part = known[known["kind"] == kind]
        if len(part):
            out.append({"kind": kind, "days": int(part["day"].nunique()), "hours": int(len(part)),
                        "mae_mw": float(part["err"].abs().mean()), "bias_mw": float(part["err"].mean())})
    return out
