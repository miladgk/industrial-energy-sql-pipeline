"""
test_finnish_calendar.py: Finnish holidays and the sun (src/finnish_calendar.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
REGRESSION tests against dates anyone can look up:
  - Easter, Midsummer and All Saints' Day for several years
  - eves and bridge days around Ascension Day and Christmas
  - the sun at noon on midsummer and midwinter over central Finland
"""

import os
import sys
from datetime import date, datetime, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import finnish_calendar as cal  # noqa: E402


@pytest.mark.regression
@pytest.mark.parametrize("year, easter", [(2024, date(2024, 3, 31)), (2025, date(2025, 4, 20)),
                                          (2026, date(2026, 4, 5)), (2027, date(2027, 3, 28))])
def test_easter_matches_the_church_calendar(year, easter):
    assert cal.easter(year) == easter


@pytest.mark.regression
def test_moving_holidays_land_on_their_days():
    h = cal.holidays(2026)
    assert h[date(2026, 6, 19)] == "Midsummer Eve" and h[date(2026, 6, 20)] == "Midsummer Day"
    assert h[date(2026, 10, 31)] == "All Saints' Day"
    assert h[date(2026, 5, 14)] == "Ascension Day"
    assert cal.holidays(2025)[date(2025, 11, 1)] == "All Saints' Day"
    assert len(h) == 15


@pytest.mark.regression
def test_eves_and_bridge_days():
    assert cal.day_features(date(2026, 5, 13))["holiday_eve"] == 1        # Wednesday before Ascension Day
    assert cal.day_features(date(2026, 5, 15))["bridge_day"] == 1         # Friday between it and the weekend
    assert cal.day_features(date(2026, 5, 12)) == {"holiday": 0, "holiday_eve": 0, "bridge_day": 0,
                                                    "christmas_period": 0, "july": 0}
    assert cal.day_features(date(2026, 12, 25))["holiday"] == 1
    assert cal.day_features(date(2027, 1, 4))["christmas_period"] == 1


@pytest.mark.regression
def test_sun_elevation_at_noon_on_the_solstices():
    # Solar noon at 25 E is about 10:20 UTC; 90 - 62 +/- 23.44 degrees.
    assert cal.sun_elevation(datetime(2026, 6, 21, 10, 20, tzinfo=timezone.utc)) == pytest.approx(51.4, abs=1.0)
    assert cal.sun_elevation(datetime(2026, 12, 21, 10, 20, tzinfo=timezone.utc)) == pytest.approx(4.6, abs=1.0)
    assert cal.sun_elevation(datetime(2026, 12, 21, 22, 0, tzinfo=timezone.utc)) < -30
