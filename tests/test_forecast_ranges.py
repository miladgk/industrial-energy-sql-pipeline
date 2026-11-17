"""
test_forecast_ranges.py: calibrated ranges around Fingrid's day-ahead forecasts
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REGRESSION tests on synthetic forecasts with a known error distribution (no database):
  - split conformal reaches its nominal coverage when errors are exchangeable
  - a day is calibrated only on days that were complete when its forecast was issued,
    and changing what happened on a day cannot change that day's or the next day's range
  - adaptive conformal inference widens the ranges after a run of misses
  - a level a group is too small for falls back to all errors instead of an infinite range
"""

import math
import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import forecast_ranges as fr  # noqa: E402

pytestmark = pytest.mark.regression
START = date(2001, 1, 1)


def _rows(days=200, seed=1, scale=lambda d: 300.0, missing_after=None):
    """Hourly forecasts with normal errors whose spread can change by day."""
    rng = np.random.default_rng(seed)
    rows = []
    for k in range(days):
        d = START + timedelta(days=k)
        for h in range(24):
            f = 3000 + 1500 * math.sin((k * 24 + h) / 40)
            actual = None if missing_after is not None and k >= missing_after else f + rng.normal(0, scale(k))
            rows.append({"hour_start": datetime(d.year, d.month, d.day, h, tzinfo=timezone.utc),
                         "day_fi": d, "hour_fi": h, "forecast_mw": f, "actual_mw": actual})
    return rows


def _replay(rows, variable="consumption"):
    s = fr.Series(rows)
    known = sorted({d for d, a in zip(s.day, s.actual) if not np.isnan(a)})
    days = [d for d in known if s.known_days(s.calibration(d)) >= fr.MIN_CAL_DAYS]
    return s, days, fr.backtest(s, variable, days)


def test_conformal_ranges_reach_their_coverage_on_exchangeable_errors():
    _, days, bt = _replay(_rows(days=260))
    for m in ("global", "by_hour", "mondrian"):
        assert bt["table"][m][0.8]["coverage"] >= 0.78, m
        assert bt["table"][m][0.95]["coverage"] >= 0.935, m


def test_conformal_interval_uses_the_finite_sample_rank():
    r = np.arange(1, 20, dtype=float)                       # n = 19: 90 % interval = 1st and 19th order statistic
    assert fr.conformal_interval(r, 0.1) == (1.0, 19.0)
    assert fr.conformal_interval(np.array([1.0, 2.0]), 0.05) == (-math.inf, math.inf)


def test_a_day_is_calibrated_only_on_days_complete_at_issue_time():
    s = fr.Series(_rows(days=120))
    target = START + timedelta(days=100)
    used = set(s.day[s.calibration(target)].tolist())
    assert max(used) == target - timedelta(days=2)
    assert len(used) == fr.CAL_DAYS


def test_what_happens_on_a_day_cannot_change_its_own_or_the_next_days_range():
    rows = _rows(days=150, seed=5)
    target = START + timedelta(days=120)
    shocked = [dict(r, actual_mw=r["actual_mw"] + 5000) if r["day_fi"] in (target, target - timedelta(days=1)) else r
               for r in rows]
    a = _replay(rows)[2]["published"][target]["bounds"]
    b = _replay(shocked)[2]["published"][target]["bounds"]
    for lv in fr.LEVELS:
        assert np.allclose(a[lv][0], b[lv][0]) and np.allclose(a[lv][1], b[lv][1])


def test_adaptive_ranges_widen_after_the_errors_grow():
    rows = _rows(days=220, seed=9, scale=lambda d: 300.0 if d < 160 else 900.0)
    _, _, bt = _replay(rows)
    assert bt["alphas"][0.8] < 0.2 and bt["alphas"][0.95] < 0.05        # target miss rate tightened
    late = [d for d in bt["published"] if d >= START + timedelta(days=190)]
    widths = lambda d: np.mean(bt["published"][d]["bounds"][0.8][1] - bt["published"][d]["bounds"][0.8][0])
    early = START + timedelta(days=150)
    assert np.mean([widths(d) for d in late]) > 1.5 * widths(early)
    assert bt["table"]["adaptive"][0.8]["coverage"] > bt["table"]["global"][0.8]["coverage"]


def test_thin_groups_fall_back_to_all_errors_instead_of_infinite_ranges():
    s = fr.Series(_rows(days=100))
    r = fr.ranges_for_day(s, START + timedelta(days=95), "mondrian", {0.8: 0.2, 0.95: 0.0125})
    for lv in fr.LEVELS:
        assert np.isfinite(r["bounds"][lv][0]).all() and np.isfinite(r["bounds"][lv][1]).all()


def test_wind_ranges_never_go_below_zero():
    assert (fr.clip("wind", np.array([-50.0, 10.0])) == [0.0, 10.0]).all()
    assert (fr.clip("consumption", np.array([-50.0])) == [-50.0]).all()
