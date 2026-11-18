"""
test_strike_effect.py: the strike counterfactual (src/strike_effect.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REGRESSION tests on a synthetic year with a known answer (no database):
  - a drop of known size injected into a period is measured back, and the
    placebo test calls it significant
  - with no drop, the effect is small and the placebo test does not call it
  - the model never trains on the event it is asked about
  - two series that only share a trend correlate in levels but not in changes
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import strike_effect as se  # noqa: E402

START = datetime(2023, 11, 1, tzinfo=timezone.utc)
EVENT = {"key": "test", "name": "Test strike", "start": date(2024, 3, 11), "end": date(2024, 3, 24)}
DROP_MW = 800.0


def _rows(drop: float, days: int = 500, seed: int = 4):
    rng = np.random.default_rng(seed)
    rows = []
    for h in range(24 * days):
        t = START + timedelta(hours=h)
        local = t.astimezone(se.HELSINKI)
        temp = 3 - 12 * np.cos(2 * np.pi * (local.timetuple().tm_yday - 15) / 365) + rng.normal(0, 3)
        cons = 9000 + 150 * max(15 - temp, 0) + 600 * np.sin(np.pi * local.hour / 24) \
            - (700 if local.weekday() >= 5 else 0) + rng.normal(0, 120)
        if EVENT["start"] <= local.date() <= EVENT["end"]:
            cons -= drop
        rows.append({"hour_start": t, "day_fi": local.date(), "hour_fi": local.hour, "consumption_mw": cons, "temp_c": temp})
    return rows


@pytest.fixture(scope="module")
def events(monkeypatch_module):
    monkeypatch_module.setattr(se, "EVENTS", [EVENT])
    return [EVENT]


@pytest.fixture(scope="module")
def monkeypatch_module():
    mp = pytest.MonkeyPatch()
    yield mp
    mp.undo()


@pytest.mark.regression
def test_a_known_drop_is_measured_and_called_significant(events):
    res = se.event_study(se.panel(_rows(DROP_MW)), EVENT, n_placebo=12)
    assert res["mean_mw"] == pytest.approx(-DROP_MW, abs=150)
    assert res["placebo_p"] == 0.0
    assert res["placebo_band_mw"][0] > -DROP_MW / 2


@pytest.mark.regression
def test_no_drop_is_not_called_significant(events):
    res = se.event_study(se.panel(_rows(0.0)), EVENT, n_placebo=12)
    assert abs(res["mean_mw"]) < 200
    assert res["placebo_p"] > 0.05


@pytest.mark.regression
def test_the_event_is_never_in_the_training_data(events):
    df = se.panel(_rows(DROP_MW, days=300))
    base = se.gap(df, EVENT["start"], EVENT["end"], [(EVENT["start"], EVENT["end"])])["mean_mw"]
    spoiled = df.copy()
    inside = ((spoiled["day_fi"] >= EVENT["start"] - timedelta(days=se.BUFFER_DAYS))
              & (spoiled["day_fi"] <= EVENT["end"] + timedelta(days=se.BUFFER_DAYS)))
    spoiled.loc[inside, "consumption_mw"] -= 5000           # whatever happens inside must not change the model
    again = se.gap(spoiled, EVENT["start"], EVENT["end"], [(EVENT["start"], EVENT["end"])])["mean_mw"]
    assert again == pytest.approx(base - 5000, abs=1e-6)


@pytest.mark.regression
def test_a_shared_trend_correlates_levels_but_not_changes():
    rng = np.random.default_rng(1)
    t = np.arange(36)
    x = 95 + 0.3 * t + rng.normal(0, 1, 36)                    # an index that drifts up
    y = -150 + 8 * t + rng.normal(0, 30, 36)                    # consumption that drifts up, unrelated otherwise
    check = se.trend_check(x, y)
    assert check["r_levels"] > 0.5
    assert abs(check["r_changes"]) < 0.4 and abs(check["slope_t"]) < 2
    linked = se.trend_check(x, y + 40 * (x - x.mean()))         # now y truly follows x
    assert linked["slope_t"] > 2
