"""
finnish_calendar.py
~~~~~~~~~~~~~~~~~~~
The calendar features Finnish electricity demand follows, computed (no API):

  holidays(year)      Finland's public holidays, plus Christmas Eve and
                      Midsummer Eve, which are days off in practice
  day_features(d)     holiday, eve of a holiday, bridge day, Christmas
                      period (24 Dec - 6 Jan), July industrial holiday
  sun_elevation(t)    height of the sun over central Finland (62 N 25 E),
                      degrees: lighting demand and solar output follow it

Easter uses the anonymous Gregorian algorithm (Meeus); the rest are fixed
dates or the Saturday/Friday in a fixed window, as the Finnish law on
public holidays defines them.
"""

from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache

LAT, LON = 62.0, 25.0


def easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def _weekday_in(year: int, month: int, first_day: int, weekday: int) -> date:
    """The date with *weekday* (Mon=0) in the seven days starting at *first_day*."""
    d = date(year, month, first_day)
    return d + timedelta(days=(weekday - d.weekday()) % 7)


@lru_cache(maxsize=None)
def holidays(year: int) -> dict:
    e = easter(year)
    midsummer = _weekday_in(year, 6, 20, 5)                       # Saturday 20-26 June
    return {
        date(year, 1, 1): "New Year's Day", date(year, 1, 6): "Epiphany",
        e - timedelta(days=2): "Good Friday", e: "Easter Sunday", e + timedelta(days=1): "Easter Monday",
        date(year, 5, 1): "May Day", e + timedelta(days=39): "Ascension Day", e + timedelta(days=49): "Whit Sunday",
        midsummer - timedelta(days=1): "Midsummer Eve", midsummer: "Midsummer Day",
        _weekday_in(year, 10, 31, 5): "All Saints' Day",               # Saturday 31 Oct - 6 Nov
        date(year, 12, 6): "Independence Day", date(year, 12, 24): "Christmas Eve",
        date(year, 12, 25): "Christmas Day", date(year, 12, 26): "Boxing Day",
    }


def is_holiday(d: date) -> bool:
    return d in holidays(d.year)


def day_features(d: date) -> dict:
    off = lambda x: is_holiday(x) or x.weekday() >= 5
    return {
        "holiday": int(is_holiday(d)),
        "holiday_eve": int(not off(d) and is_holiday(d + timedelta(days=1))),
        # a working day squeezed between a holiday and a weekend: many take it off
        "bridge_day": int(not off(d) and off(d - timedelta(days=1)) and off(d + timedelta(days=1))),
        "christmas_period": int((d.month == 12 and d.day >= 24) or (d.month == 1 and d.day <= 6)),
        "july": int(d.month == 7),
    }


def sun_elevation(t: datetime) -> float:
    """Solar elevation in degrees at LAT/LON for the UTC instant *t* (accurate to about a degree)."""
    t = t.astimezone(timezone.utc)
    doy = t.timetuple().tm_yday
    decl = math.radians(23.44) * math.sin(2 * math.pi * (284 + doy) / 365)
    solar_hour = t.hour + t.minute / 60 + LON / 15
    hour_angle = math.radians(15 * (solar_hour - 12))
    lat = math.radians(LAT)
    s = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
    return math.degrees(math.asin(max(-1.0, min(1.0, s))))
