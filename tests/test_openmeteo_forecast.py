"""
test_openmeteo_forecast.py: the two-day-old weather archive (src/openmeteo_forecast.py)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
No network: answers in Open-Meteo's format go through a fake fetcher.
  - hours whose two-day-old run cannot be out yet are never stored (no leak)
  - missing values are skipped; issued_at is 48 h before the hour
  - a second fetch adds nothing, and a new place is backfilled on its own
"""

import os
import sys
from datetime import date, datetime, timedelta, timezone

import pytest

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(ROOT, "src"))

import openmeteo_forecast as om  # noqa: E402

NOW = datetime(2001, 1, 1, 10, 30, tzinfo=timezone.utc)


def _payload(start: datetime, hours: int) -> dict:
    times = [(start + timedelta(hours=i)).strftime("%Y-%m-%dT%H:%M") for i in range(hours)]
    return {"hourly": {"time": times,
                       "temperature_2m_previous_day2": [float(i) for i in range(hours)],
                       "wind_speed_100m_previous_day2": [None if i == 0 else 5.0 for i in range(hours)]}}


@pytest.mark.smoke
def test_only_hours_whose_run_was_out_are_kept():
    until = om.last_valid(NOW)
    assert until == datetime(2001, 1, 3, 4, tzinfo=timezone.utc)          # now + 48 h - 6 h, whole hour
    rows = om.rows_from(_payload(datetime(2001, 1, 3, 0, tzinfo=timezone.utc), 10), "Vaasa", until)
    valid = sorted({r[4] for r in rows})
    assert valid[-1] == until and len(valid) == 5                          # 00:00 .. 04:00
    assert all(r[3] == r[4] - timedelta(hours=48) for r in rows)
    assert len(rows) == 5 + 4                                              # the first wind value is missing


@pytest.fixture
def archive(db, monkeypatch):
    monkeypatch.setattr(om, "MODEL", "test_openmeteo")
    yield db
    with db.cursor() as cur:
        cur.execute("DELETE FROM weather_forecast WHERE model = 'test_openmeteo'")
    db.commit()


@pytest.mark.integration
def test_fetch_backfills_each_place_and_is_idempotent(archive, monkeypatch):
    starts = []

    def fake(lat, lon, start, end):
        starts.append(start)
        return _payload(datetime(2001, 1, 2, 0, tzinfo=timezone.utc), 30)

    first = om.fetch(archive, now=NOW, getter=fake, pause=0)
    assert first == len(om.PLACES) * (29 + 28)                       # up to 04:00 on day 3, minus one missing wind
    assert set(starts) == {om.BACKFILL_FROM}
    assert om.fetch(archive, now=NOW, getter=fake, pause=0) == first  # offered again ...
    with archive.cursor() as cur:
        cur.execute("SELECT count(*) FROM weather_forecast WHERE model = 'test_openmeteo'")
        assert cur.fetchone()[0] == first                            # ... but stored once
    archive.rollback()

    starts.clear()
    monkeypatch.setitem(om.PLACES, "Testplace", (60.0, 25.0))
    om.fetch(archive, now=NOW, getter=fake, pause=0)
    assert starts.count(om.BACKFILL_FROM) == 1                       # only the new place backfills
    assert starts.count(date(2001, 1, 2)) == len(om.PLACES) - 1      # the rest resume a day before their last hour
