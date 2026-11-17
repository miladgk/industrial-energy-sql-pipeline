"""
forecast_ranges.py
~~~~~~~~~~~~~~~~~~
How wrong will tomorrow's forecast be? Calibrated ranges around Fingrid's
day-ahead wind and consumption forecasts.

Fingrid publishes one number per quarter-hour for tomorrow. Its own history of
errors (sql/analysis/25_forecast_errors_hourly.sql) says how far reality tends
to land from that number, and conformal prediction turns that history into
80 % and 95 % ranges with a coverage guarantee: if the coming errors behave
like the recent ones, at least that share of hours falls inside.

Methods, from simplest to the one published:

  global     split conformal on all recent errors
             (quantiles with the finite-sample correction ceil((n+1)(1-a))/n)
  by_hour    the same per block of six Finnish hours
  mondrian   per (six-hour block x forecast-level tercile): the error of a
             high wind forecast is several times that of a low one
  adaptive   mondrian with adaptive conformal inference (Gibbs & Candès 2021):
             after each day the miss rate a_t moves by gamma * (a - misses),
             so the ranges widen after a run of misses and narrow again
             when the forecast settles  -> published

Honest by construction: a day D is forecast from the errors of the CAL_DAYS
days that ended two days before it (day D-1 is still running when Fingrid
issues the forecast for D at 12:00 Finnish time), and the backtest replays
exactly that, day by day.
"""

from __future__ import annotations

import math
from collections import defaultdict
from datetime import date, timedelta

import numpy as np

CAL_DAYS = 90            # errors used to calibrate each day's ranges
MIN_CAL_DAYS = 60        # fewer known days than this: no range
LEVELS = (0.80, 0.95)
GAMMA = 0.05             # ACI step per day
ALPHA_FLOOR = 0.25       # ACI may tighten the miss rate to at most a quarter of the nominal one
METHODS = ("global", "by_hour", "mondrian", "adaptive")
PUBLISHED = "adaptive"
HOUR_BLOCKS = 4          # 00-05, 06-11, 12-17, 18-23 Finnish time


def conformal_interval(residuals: np.ndarray, alpha: float) -> tuple[float, float]:
    """Lower and upper residual bounds that cover >= 1 - alpha of exchangeable new residuals."""
    r = np.sort(residuals)
    n = len(r)
    if n == 0:
        return -math.inf, math.inf
    lo_rank = math.floor((n + 1) * alpha / 2)              # 1-based order statistics
    hi_rank = math.ceil((n + 1) * (1 - alpha / 2))
    lo = r[lo_rank - 1] if lo_rank >= 1 else -math.inf
    hi = r[hi_rank - 1] if hi_rank <= n else math.inf
    return float(lo), float(hi)


class Series:
    """One variable's hourly forecast/actual history, indexed by Finnish day."""

    def __init__(self, rows: list[dict]):
        rows = sorted(rows, key=lambda r: r["hour_start"])
        as_date = lambda d: date.fromisoformat(d[:10]) if isinstance(d, str) else d
        self.day = np.array([as_date(r["day_fi"]) for r in rows])
        self.hour = np.array([r["hour_fi"] for r in rows])
        self.forecast = np.array([float(r["forecast_mw"]) for r in rows])
        self.actual = np.array([np.nan if r["actual_mw"] is None else float(r["actual_mw"]) for r in rows])
        self.residual = self.actual - self.forecast
        self.by_day = defaultdict(list)
        for i, d in enumerate(self.day):
            self.by_day[d].append(i)

    def calibration(self, target: date) -> np.ndarray:
        """Indices of known errors in the CAL_DAYS days ending two days before *target*."""
        last = target - timedelta(days=2)
        idx = [i for k in range(CAL_DAYS) for i in self.by_day.get(last - timedelta(days=k), [])]
        idx = np.array(idx, dtype=int)
        return idx[~np.isnan(self.residual[idx])] if len(idx) else idx

    def known_days(self, idx: np.ndarray) -> int:
        return len(set(self.day[idx].tolist()))


def _groups(s: Series, idx: np.ndarray, target_idx: np.ndarray, method: str):
    """Group label of each calibration row and each target row."""
    if method == "global":
        return np.zeros(len(idx), int), np.zeros(len(target_idx), int)
    block = lambda h: h * HOUR_BLOCKS // 24
    if method == "by_hour":
        return block(s.hour[idx]), block(s.hour[target_idx])
    cuts = np.quantile(s.forecast[idx], [1 / 3, 2 / 3])            # level terciles of the calibration window
    level = lambda f: np.searchsorted(cuts, f)
    return (block(s.hour[idx]) * 3 + level(s.forecast[idx]),
            block(s.hour[target_idx]) * 3 + level(s.forecast[target_idx]))


def ranges_for_day(s: Series, target: date, method: str, alphas: dict) -> dict | None:
    """{level: (lo, hi) arrays} for the hours of *target*, or None without enough history."""
    idx = s.calibration(target)
    tgt = np.array(s.by_day.get(target, []), dtype=int)
    if len(tgt) == 0 or s.known_days(idx) < MIN_CAL_DAYS:
        return None
    g_cal, g_tgt = _groups(s, idx, tgt, "mondrian" if method == "adaptive" else method)
    out = {}
    for level in LEVELS:
        alpha = alphas[level] if method == "adaptive" else 1 - level
        lo, hi = np.empty(len(tgt)), np.empty(len(tgt))
        for g in set(g_tgt.tolist()):
            ql, qh = conformal_interval(s.residual[idx][g_cal == g], alpha)
            if not (math.isfinite(ql) and math.isfinite(qh)):        # group too small for this level:
                ql, qh = conformal_interval(s.residual[idx], alpha)  # use every error in the window
            lo[g_tgt == g], hi[g_tgt == g] = ql, qh
        out[level] = (s.forecast[tgt] + lo, s.forecast[tgt] + hi)
    return {"idx": tgt, "bounds": out}


def _step(alpha: float, level: float, miss: float) -> float:
    """One ACI update: more misses than 1 - level lower alpha (wider ranges), fewer raise it."""
    return float(min(max(alpha + GAMMA * ((1 - level) - miss), ALPHA_FLOOR * (1 - level)), 0.5))


def interval_score(y, lo, hi, alpha) -> np.ndarray:
    """Winkler / interval score: width plus 2/alpha times the miss distance (lower is better)."""
    return (hi - lo) + (2 / alpha) * np.maximum(lo - y, 0) + (2 / alpha) * np.maximum(y - hi, 0)


def clip(variable: str, a: np.ndarray) -> np.ndarray:
    return np.maximum(a, 0.0) if variable == "wind" else a        # wind output cannot go below zero


def backtest(s: Series, variable: str, days: list[date]) -> dict:
    """Replay every day in *days*: ranges from what was known then, scored on what happened.
    Returns per-method scores, the adaptive alphas reached, and the per-day ranges of the published method."""
    alphas = {lv: 1 - lv for lv in LEVELS}
    scores = {m: {lv: {"hits": 0, "n": 0, "width": 0.0, "score": 0.0} for lv in LEVELS} for m in METHODS}
    published, pending = {}, []                  # ACI updates wait until their day is known at issue time
    for d in days:
        while pending and pending[0][0] <= d - timedelta(days=2):
            _, misses = pending.pop(0)
            for lv, miss in misses.items():
                alphas[lv] = _step(alphas[lv], lv, miss)
        for m in METHODS:
            r = ranges_for_day(s, d, m, alphas)
            if r is None:
                continue
            y = s.actual[r["idx"]]
            ok = ~np.isnan(y)
            for lv in LEVELS:
                lo, hi = (clip(variable, b) for b in r["bounds"][lv])
                inside = (y[ok] >= lo[ok]) & (y[ok] <= hi[ok])
                sc = scores[m][lv]
                sc["hits"] += int(inside.sum()); sc["n"] += int(ok.sum())
                sc["width"] += float((hi[ok] - lo[ok]).sum())
                sc["score"] += float(interval_score(y[ok], lo[ok], hi[ok], 1 - lv).sum())
            if m == PUBLISHED:
                published[d] = r
                if ok.any():
                    misses = {}
                    for lv in LEVELS:
                        lo, hi = (clip(variable, b) for b in r["bounds"][lv])
                        misses[lv] = float(1 - ((y[ok] >= lo[ok]) & (y[ok] <= hi[ok])).mean())
                    pending.append((d, misses))
    for day, misses in pending:                  # days known by now count for tomorrow's alphas
        for lv, miss in misses.items():
            alphas[lv] = _step(alphas[lv], lv, miss)
    table = {m: {lv: {"coverage": v["hits"] / v["n"] if v["n"] else None,
                      "mean_width_mw": v["width"] / v["n"] if v["n"] else None,
                      "interval_score": v["score"] / v["n"] if v["n"] else None,
                      "hours": v["n"]} for lv, v in per.items()} for m, per in scores.items()}
    return {"table": table, "alphas": alphas, "published": published}
